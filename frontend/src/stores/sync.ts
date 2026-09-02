/**
 * The offline queue.
 *
 * `lib/db.ts` has always had the storage for this — a Dexie table keyed by a
 * client-generated UUID, with attempt counts and a human-readable summary — and
 * `offline.sync_invoices` has always been on the server, keyed on the same UUID so a
 * replayed batch cannot double-post. Nothing was joining the two, so going offline
 * mid-sale simply failed the submit and lost the basket.
 *
 * This store is that join. Three rules shape it:
 *
 *   A queued sale is a completed sale. The cashier has taken the money and handed
 *   over the goods, so the queue must never silently drop an entry — a failed one
 *   stays visible and retryable rather than disappearing.
 *
 *   Only genuine connectivity failures queue. A 417 from ERPNext because the stock
 *   is negative is a real answer and must reach the cashier; queueing it would just
 *   fail again every retry, forever.
 *
 *   Draining is serial. The server caps a batch at 25, and invoices in one shift can
 *   consume the same stock, so replaying them in the order they were taken is the
 *   only order that behaves like the day did.
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api, FrappeError, OfflineError } from "@/lib/api";
import {
	enqueueInvoice,
	listQueue,
	pruneQueue,
	removeQueueEntry,
	updateQueueEntry,
	type QueuedInvoice,
} from "@/lib/db";
import { uid } from "@/lib/uid";
import { useSessionStore } from "./session";
import { useUiStore } from "./ui";

/** The server refuses more than this in one call. */
const BATCH_SIZE = 25;
/** Give the network a moment to settle before draining on reconnect. */
const RECONNECT_DELAY_MS = 1200;

export interface SyncResult {
	uuid: string | null;
	status: "synced" | "duplicate" | "error";
	name?: string;
	error?: string;
}

export const useSyncStore = defineStore("sync", () => {
	const session = useSessionStore();
	const ui = useUiStore();

	const entries = ref<QueuedInvoice[]>([]);
	const draining = ref(false);
	const lastDrainAt = ref<number | null>(null);

	const pending = computed(() => entries.value.filter((row) => row.status === "pending"));
	const failed = computed(() => entries.value.filter((row) => row.status === "failed"));
	/** What the operator is owed a number for: anything not yet accepted. */
	const outstanding = computed(() => pending.value.length + failed.value.length);
	const hasOutstanding = computed(() => outstanding.value > 0);
	const oldest = computed(() =>
		[...pending.value, ...failed.value].sort((a, b) => a.created_at - b.created_at)[0] ?? null,
	);

	async function refresh() {
		entries.value = (await listQueue(session.profile?.name)).sort(
			(a, b) => a.created_at - b.created_at,
		);
	}

	/**
	 * Decide whether a failed submit belongs in the queue.
	 *
	 * A transport failure means we never learned what the server thought, so the sale
	 * is replayable. Anything the server answered — a validation error, a permission
	 * refusal — is a decision, and replaying it changes nothing.
	 */
	function isConnectivityFailure(error: unknown): boolean {
		if (error instanceof OfflineError) return true;
		// fetch() rejects with TypeError when the request never completed.
		if (error instanceof TypeError) return true;
		if (error instanceof FrappeError) {
			// 502/503/504 are a proxy or a restarting worker, not an answer.
			return error.status === 0 || error.status >= 502;
		}
		return false;
	}

	/**
	 * Flatten reactive state into plain data.
	 *
	 * IndexedDB stores by structured clone, and a Vue reactive Proxy is not cloneable
	 * — `DataCloneError: could not be cloned`. `toInvoicePayload()` passes some arrays
	 * (posa_offers, posa_coupons) straight out of the store, and even an *empty*
	 * reactive array is still a Proxy, so every queued sale failed on the write. The
	 * payload is pure JSON data by construction, so a round trip through JSON is both
	 * sufficient and exact — and it drops the `undefined`s a wire payload should not
	 * carry anyway.
	 */
	function plain<T>(value: T): T {
		return JSON.parse(JSON.stringify(value ?? null)) as T;
	}

	/** Park a completed-but-unsent sale. Returns the queue id. */
	async function enqueue(payload: {
		invoice: Record<string, unknown>;
		data: Record<string, unknown>;
		summary: QueuedInvoice["summary"];
	}): Promise<string> {
		await refresh();
		const limit = Math.max(Number(session.profile?.posa_offline_max_queue ?? 200), 1);
		if (outstanding.value >= limit) {
			throw new Error(
				`This terminal already has ${outstanding.value} unsent invoices. Reconnect and sync before taking another offline sale.`,
			);
		}
		const now = Date.now();
		const entry: QueuedInvoice = {
			uuid: uid("offline"),
			profile: session.profile?.name ?? "",
			shift: session.shiftName,
			created_at: now,
			updated_at: now,
			status: "pending",
			attempts: 0,
			summary: plain(payload.summary),
			payload: plain({
				invoice: payload.invoice,
				data: payload.data,
			}),
		};
		await enqueueInvoice(entry);
		await refresh();
		return entry.uuid;
	}

	/**
	 * Send everything queued, oldest first, in server-sized batches.
	 *
	 * Failed entries are retried alongside pending ones: whatever broke was usually
	 * the connection, and the operator should not have to pick entries by hand.
	 */
	async function drain(options: { silent?: boolean } = {}): Promise<SyncResult[]> {
		if (draining.value) return [];
		await refresh();

		const queue = [...pending.value, ...failed.value].sort((a, b) => a.created_at - b.created_at);
		if (!queue.length) return [];
		if (!(await session.probe())) {
			if (!options.silent) ui.warn("Still offline", "The queue will send itself when the connection returns.");
			return [];
		}

		draining.value = true;
		const all: SyncResult[] = [];
		try {
			for (let index = 0; index < queue.length; index += BATCH_SIZE) {
				const slice = queue.slice(index, index + BATCH_SIZE);
				await Promise.all(slice.map((row) => updateQueueEntry(row.uuid, { status: "syncing" })));

				let results: SyncResult[];
				try {
					results = (await api.syncInvoices(
						slice.map((row) => ({ uuid: row.uuid, ...row.payload })),
					)) as SyncResult[];
				} catch (error) {
					// The batch never landed. Put it back as pending, not failed — nothing
					// about these invoices is wrong.
					await Promise.all(
						slice.map((row) =>
							updateQueueEntry(row.uuid, {
								status: "pending",
								last_error: error instanceof Error ? error.message : String(error),
							}),
						),
					);
					await refresh();
					if (!options.silent) {
						ui.fail("Could not send the queue", error instanceof Error ? error.message : String(error));
					}
					return all;
				}

				const answered = new Set<string>();
				for (const result of results ?? []) {
					if (!result?.uuid) continue;
					answered.add(result.uuid);
					const row = slice.find((entry) => entry.uuid === result.uuid);
					if (result.status === "synced" || result.status === "duplicate") {
						// Accepted, so it can go. `duplicate` means a previous attempt got
						// through before the connection dropped — also a success.
						await removeQueueEntry(result.uuid);
					} else {
						await updateQueueEntry(result.uuid, {
							status: "failed",
							attempts: (row?.attempts ?? 0) + 1,
							last_error: result.error,
						});
					}
					all.push(result);
				}

				// An entry the server did not mention is still unsent, and would otherwise
				// sit at "syncing" forever — counted as neither pending nor failed, so the
				// operator would see an empty queue while a sale had never landed.
				for (const row of slice) {
					if (answered.has(row.uuid)) continue;
					await updateQueueEntry(row.uuid, {
						status: "pending",
						last_error: "The server did not report on this entry; it will be retried.",
					});
				}
			}
		} finally {
			draining.value = false;
			lastDrainAt.value = Date.now();
			await refresh();
			void pruneQueue();
		}

		report(all, options.silent);
		return all;
	}

	function report(results: SyncResult[], silent?: boolean) {
		if (silent || !results.length) return;
		const sent = results.filter((row) => row.status === "synced" || row.status === "duplicate").length;
		const broke = results.filter((row) => row.status === "error");

		if (sent) {
			ui.success(
				sent === 1 ? "1 offline sale sent" : `${sent} offline sales sent`,
				broke.length ? `${broke.length} still need attention` : undefined,
			);
		}
		if (broke.length) {
			ui.fail(
				broke.length === 1 ? "An offline sale was rejected" : `${broke.length} offline sales were rejected`,
				broke[0]?.error,
			);
		}
	}

	/** Discard one entry. Deliberately explicit — this loses a real sale. */
	async function discard(uuid: string) {
		await removeQueueEntry(uuid);
		await refresh();
	}

	let bound = false;

	/** Drain on reconnect, and once on start for whatever last session left behind. */
	function watch() {
		if (bound) return;
		bound = true;
		window.addEventListener("online", () => {
			// navigator.onLine flips before the route is actually usable.
			setTimeout(() => void drain(), RECONNECT_DELAY_MS);
		});
		void refresh().then(() => {
			if (hasOutstanding.value && session.serverReachable) void drain();
		});
	}

	return {
		entries,
		draining,
		lastDrainAt,
		pending,
		failed,
		outstanding,
		hasOutstanding,
		oldest,
		refresh,
		enqueue,
		drain,
		discard,
		isConnectivityFailure,
		watch,
	};
});
