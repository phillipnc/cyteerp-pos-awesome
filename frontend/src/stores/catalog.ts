/**
 * Item catalog: loading, caching, searching and filtering.
 *
 * Search runs locally against the loaded set so keystrokes are instant. When the
 * profile limits the search server-side (`pose_use_limit_search`, for very large
 * catalogs) we fall back to querying the server, debounced.
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api, OfflineError } from "@/lib/api";
import { cacheItems, cacheStamp, readCachedItems } from "@/lib/db";
import type { Item } from "@/types";
import { useSessionStore } from "./session";
import { useUiStore } from "./ui";

export type ViewMode = "grid" | "list";

const SERVER_SEARCH_DEBOUNCE = 260;

export const useCatalogStore = defineStore("catalog", () => {
	const session = useSessionStore();
	const ui = useUiStore();

	const items = ref<Item[]>([]);
	const groups = ref<string[]>([]);
	const loading = ref(false);
	const loadedFromCache = ref(false);
	const lastLoadedAt = ref<number | null>(null);

	const search = ref("");
	const activeGroup = ref("");
	const viewMode = ref<ViewMode>("grid");
	const serverResults = ref<Item[] | null>(null);

	const useServerSearch = computed(() => !!session.profile?.pose_use_limit_search);

	/** Precomputed lowercase haystacks — rebuilding these per keystroke is the
	 *  difference between a snappy and a sluggish search on a big catalog. */
	const haystacks = ref<Map<string, string>>(new Map());

	function indexItems(list: Item[]) {
		const index = new Map<string, string>();
		for (const item of list) {
			index.set(
				item.item_code,
				[item.item_code, item.item_name, item.item_group, item.brand, ...(item.item_barcode ?? []).map((b) => b.barcode)]
					.filter(Boolean)
					.join(" ")
					.toLowerCase(),
			);
		}
		haystacks.value = index;
	}

	const filtered = computed<Item[]>(() => {
		const source = useServerSearch.value && serverResults.value ? serverResults.value : items.value;
		const term = search.value.trim().toLowerCase();
		const group = activeGroup.value;

		if (!term && !group) return source;

		return source.filter((item) => {
			if (group && item.item_group !== group) return false;
			if (!term) return true;
			// Server-searched results are already matched; skip the local pass.
			if (useServerSearch.value && serverResults.value) return true;
			return (haystacks.value.get(item.item_code) ?? "").includes(term);
		});
	});

	async function load(options: { force?: boolean } = {}) {
		if (!session.profile) return;
		loading.value = true;
		loadedFromCache.value = false;

		try {
			if (!options.force) {
				// Show cached items immediately, then refresh underneath.
				const cached = await readCachedItems(session.profile.name);
				const stamp = await cacheStamp("items", session.profile.name);
				const ttl = Math.max(Number(session.profile.posa_offline_cache_ttl ?? 60), 1) * 60_000;
				if (cached.length && stamp && Date.now() - stamp <= ttl) {
					items.value = cached;
					indexItems(cached);
					loadedFromCache.value = true;
					lastLoadedAt.value = stamp;
				}
			}

			const fresh = (await api.items({
				pos_profile: session.profile,
				price_list: session.priceList,
				customer: session.pricingCustomer ?? undefined,
				invoice_currency: session.currency,
			})) as Item[];

			items.value = fresh ?? [];
			indexItems(items.value);
			loadedFromCache.value = false;
			lastLoadedAt.value = Date.now();

			if (session.offlineEnabled) void cacheItems(session.profile.name, items.value);
		} catch (error) {
			if (error instanceof OfflineError || error instanceof TypeError) {
				if (!items.value.length) {
					const cached = await readCachedItems(session.profile.name);
					items.value = cached;
					indexItems(cached);
					loadedFromCache.value = true;
				}
				if (!items.value.length) ui.fail("Offline", "No cached catalog on this terminal yet.");
			} else {
				ui.fail("Could not load items", error instanceof Error ? error.message : String(error));
			}
		} finally {
			loading.value = false;
		}
	}

	async function loadGroups() {
		if (!session.profile) return;
		try {
			const rows = (await api.itemGroups(session.profile.name)) as { name: string }[];
			groups.value = rows.map((row) => row.name);
		} catch {
			// Groups are a filter convenience; failing to load one is not blocking.
		}
	}

	let searchTimer: number | undefined;

	function setSearch(term: string) {
		search.value = term;
		if (!useServerSearch.value) return;

		if (searchTimer) window.clearTimeout(searchTimer);
		if (!term.trim()) {
			serverResults.value = null;
			return;
		}
		searchTimer = window.setTimeout(() => void runServerSearch(term), SERVER_SEARCH_DEBOUNCE);
	}

	async function runServerSearch(term: string) {
		if (!session.profile) return;
		loading.value = true;
		try {
			serverResults.value = (await api.items({
				pos_profile: session.profile,
				price_list: session.priceList,
				customer: session.pricingCustomer ?? undefined,
				search_value: term,
				item_group: activeGroup.value,
				invoice_currency: session.currency,
			})) as Item[];
		} catch {
			serverResults.value = null;
		} finally {
			loading.value = false;
		}
	}

	function setGroup(group: string) {
		activeGroup.value = activeGroup.value === group ? "" : group;
		if (useServerSearch.value && search.value.trim()) void runServerSearch(search.value);
	}

	function clearFilters() {
		search.value = "";
		activeGroup.value = "";
		serverResults.value = null;
	}

	function findByCode(itemCode: string): Item | undefined {
		return items.value.find((item) => item.item_code === itemCode);
	}

	/** Resolve a scanned code, preferring the local catalog before asking the server. */
	async function resolveScan(lookup: string): Promise<Item | null> {
		const local = items.value.find((item) => item.item_code === lookup);
		if (local) return { ...local };

		const barcodeMatch = items.value
			.map((item) => ({
				item,
				barcode: (item.item_barcode ?? []).find((barcode) => barcode.barcode === lookup),
			}))
			.find((match) => !!match.barcode);
		if (barcodeMatch) {
			return {
				...barcodeMatch.item,
				scanned_barcode: lookup,
				scanned_uom: barcodeMatch.barcode?.posa_uom ?? null,
			};
		}

		if (!session.serverReachable) return null;
		try {
			return ((await api.scan({
				pos_profile: session.profile,
				code: lookup,
				price_list: session.priceList,
				customer: session.pricingCustomer ?? undefined,
				invoice_currency: session.currency,
			})) as Item) ?? null;
		} catch {
			return null;
		}
	}

	return {
		items,
		groups,
		loading,
		loadedFromCache,
		lastLoadedAt,
		search,
		activeGroup,
		viewMode,
		filtered,
		useServerSearch,
		load,
		loadGroups,
		setSearch,
		setGroup,
		clearFilters,
		findByCode,
		resolveScan,
	};
});
