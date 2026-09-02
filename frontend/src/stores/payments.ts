/**
 * Tender state for the sale being closed.
 *
 * Rows mirror the profile's modes of payment. The cashier fills amounts; this
 * store derives what is still owed and what change is due, and owns the actual
 * submit so no component has to know the invoice payload shape.
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "@/lib/api";
import { money, toNumber } from "@/lib/format";
import type { CreditRow, PaymentMethod } from "@/types";
import { useCartStore } from "./cart";
import { useSessionStore } from "./session";
import { useSyncStore } from "./sync";
import { useUiStore } from "./ui";

export interface TenderRow {
	mode_of_payment: string;
	/** Account/tender currency configured for the mode of payment. */
	currency: string;
	/** Invoice-currency value of one unit of tender currency. */
	exchange_rate: number;
	/** Amount physically received in the tender currency. */
	tendered_amount: number;
	/** Converted amount in the invoice currency. */
	amount: number;
	account?: string;
	type?: string;
	default: boolean;
}

export const usePaymentsStore = defineStore("payments", () => {
	const session = useSessionStore();
	const cart = useCartStore();
	const sync = useSyncStore();
	const ui = useUiStore();

	const rows = ref<TenderRow[]>([]);
	/** Credit notes and advances the customer can spend on this sale. */
	const credit = ref<CreditRow[]>([]);
	const loadingCredit = ref(false);
	const submitting = ref(false);
	/** True once the cashier edits amounts by hand — auto-tender then stands down. */
	const touched = ref(false);
	/** The invoice that was just completed, for the success panel and reprint. */
	const lastInvoice = ref<Record<string, unknown> | null>(null);

	/** +1 on a sale, -1 on a return. Money flows the other way on a credit note,
	 *  so every comparison below has to be taken relative to this. */
	const sign = computed(() => (cart.isReturn ? -1 : 1));

	const paid = computed(() => money(rows.value.reduce((sum, row) => sum + toNumber(row.amount), 0)));
	/** Credit the cashier has chosen to spend on this sale. */
	const creditApplied = computed(() =>
		cart.isReturn
			? 0
			: money(credit.value.reduce((sum, row) => sum + toNumber(row.credit_to_redeem), 0)),
	);
	const creditAvailable = computed(() =>
		money(credit.value.reduce((sum, row) => sum + toNumber(row.total_credit), 0)),
	);
	/** Redemption covers part of the total before any cash is counted. */
	const redeemed = computed(() =>
		cart.isReturn ? 0 : money(toNumber(cart.loyaltyAmount) + creditApplied.value),
	);
	const payable = computed(() => {
		const gross = cart.payableAmount - redeemed.value;
		// Only a sale can never fall below zero. A refund's total is negative by
		// design, and clamping it to zero left nothing to tender — so `canSubmit`,
		// which wants a non-zero paid amount, refused every refund outright.
		return money(cart.isReturn ? gross : Math.max(gross, 0));
	});
	/** Signed shortfall: still owed on a sale, still to refund on a return. */
	const remaining = computed(() => money(payable.value - paid.value));
	/** Magnitude still outstanding, whichever way the money is moving. */
	const outstanding = computed(() => money(Math.max(sign.value * remaining.value, 0)));
	/** Over-tender: change owed to the customer, or an over-refund. */
	const change = computed(() => money(Math.max(sign.value * (paid.value - payable.value), 0)));
	const settled = computed(() => sign.value * remaining.value <= 0);
	const hasTender = computed(() => Math.abs(paid.value) > 0);
	const isCreditSale = computed(
		() =>
			!cart.isReturn &&
			!settled.value &&
			!hasTender.value &&
			!!session.profile?.posa_allow_credit_sale,
	);
	const isPartialPayment = computed(
		() =>
			!settled.value &&
			hasTender.value &&
			!!session.profile?.posa_allow_partial_payment,
	);
	const isCustomerCreditReturn = computed(
		() =>
			cart.isReturn &&
			!hasTender.value &&
			!!session.profile?.use_customer_credit,
	);
	const canSubmit = computed(
		() =>
			!cart.isEmpty &&
			!!cart.customer &&
			(settled.value || isCreditSale.value || isPartialPayment.value || isCustomerCreditReturn.value) &&
			!submitting.value,
	);

	const settlementMode = computed(() => {
		if (isCustomerCreditReturn.value) return "customer_credit_return";
		if (isCreditSale.value) return "credit";
		if (isPartialPayment.value) return "partial";
		return "settled";
	});

	function build() {
		rows.value = session.paymentMethods.map((method: PaymentMethod) => ({
			mode_of_payment: method.mode_of_payment,
			currency: method.currency || session.currency,
			exchange_rate: toNumber(method.exchange_rate) || 1,
			tendered_amount: 0,
			amount: 0,
			account: method.account,
			type: method.type,
			default: !!method.default,
		}));
		touched.value = false;
	}

	function reset() {
		build();
		credit.value = [];
		lastInvoice.value = null;
	}

	/**
	 * Load the credit sitting on this customer's account.
	 *
	 * Unapplied credit notes and advance payments both count. The list is per
	 * customer, so it is reloaded whenever the customer on the ticket changes; a
	 * stale list would offer credit that belongs to somebody else.
	 */
	async function loadCredit() {
		credit.value = [];
		if (!cart.customer || !session.companyName) return;
		if (!session.profile?.use_customer_credit) return;
		loadingCredit.value = true;
		try {
			const rowsFromServer = (await api.availableCredit(
				cart.customer,
				session.companyName,
				session.currency,
			)) as CreditRow[];
			credit.value = (rowsFromServer ?? []).map((row) => ({
				...row,
				total_credit: toNumber(row.total_credit),
				credit_to_redeem: 0,
			}));
		} catch {
			// Credit is an optional convenience; failing to read it must not stop a sale.
		} finally {
			loadingCredit.value = false;
		}
	}

	/** Spend an amount from one credit origin, capped at what it holds. */
	function setCredit(origin: string, value: number) {
		const row = credit.value.find((entry) => entry.credit_origin === origin);
		if (!row) return;
		const cap = toNumber(row.total_credit);
		row.credit_to_redeem = money(Math.min(Math.max(toNumber(value), 0), cap));
		// Credit changes what is left to tender, so any auto-tender has to run again.
		touched.value = false;
		clear();
		tenderExact();
	}

	/** Spend as much credit as the sale can absorb, oldest origin first. */
	function applyMaxCredit() {
		let room = money(Math.max(cart.payableAmount - toNumber(cart.loyaltyAmount), 0));
		for (const row of credit.value) {
			const take = money(Math.min(toNumber(row.total_credit), room));
			row.credit_to_redeem = take;
			room = money(room - take);
		}
		touched.value = false;
		clear();
		tenderExact();
	}

	function clearCredit() {
		for (const row of credit.value) row.credit_to_redeem = 0;
		touched.value = false;
		clear();
		tenderExact();
	}

	/** The cashier always types a positive magnitude; direction comes from the sale. */
	function setAmount(mode: string, value: number) {
		const row = rows.value.find((entry) => entry.mode_of_payment === mode);
		if (!row) return;
		row.tendered_amount = money(Math.max(Math.abs(toNumber(value)), 0));
		row.amount = money(sign.value * row.tendered_amount * row.exchange_rate);
		touched.value = true;
	}

	function addAmount(mode: string, delta: number) {
		const row = rows.value.find((entry) => entry.mode_of_payment === mode);
		if (!row) return;
		row.tendered_amount = money(Math.max(row.tendered_amount + Math.abs(delta), 0));
		row.amount = money(sign.value * row.tendered_amount * row.exchange_rate);
		touched.value = true;
	}

	function setExchangeRate(mode: string, value: number) {
		const row = rows.value.find((entry) => entry.mode_of_payment === mode);
		if (!row || value <= 0) return;
		row.exchange_rate = toNumber(value);
		row.amount = money(sign.value * row.tendered_amount * row.exchange_rate);
		touched.value = true;
	}

	/** Drop the whole balance onto one mode — the common single-tender case. */
	function tenderExact(mode?: string) {
		const target =
			rows.value.find((row) => row.mode_of_payment === mode) ??
			rows.value.find((row) => row.default) ??
			rows.value[0];
		if (!target) return;
		clear();
		// Signed, not clamped: a return has to be able to tender a negative amount
		// or the refund can never be completed.
		target.amount = money(payable.value);
		target.tendered_amount = money(Math.abs(payable.value) / target.exchange_rate);
	}

	function clear() {
		for (const row of rows.value) {
			row.amount = 0;
			row.tendered_amount = 0;
		}
	}

	/** Offline-capable, and the thing that failed was the network rather than a rule. */
	function canQueue(error: unknown): boolean {
		return session.offlineEnabled && sync.isConnectivityFailure(error);
	}

	/** Everything `submit_invoice` would have received, built from local state. */
	function buildPayload(draftName?: string) {
		const invoice = {
			...cart.toInvoicePayload(),
			name: draftName,
			payments: rows.value
				// Magnitude, not sign: refund rows are negative and a `> 0` test
				// silently drops every one of them, leaving the invoice unpaid.
				.filter((row) => Math.abs(row.amount) > 0)
				.map((row) => ({
					mode_of_payment: row.mode_of_payment,
					amount: row.amount,
					account: row.account,
					type: row.type,
					default: row.default ? 1 : 0,
					posa_tender_currency: row.currency,
					posa_tender_amount: sign.value * row.tendered_amount,
					posa_exchange_rate: row.exchange_rate,
				})),
			paid_amount: paid.value,
			change_amount: change.value,
		};

		const data: Record<string, unknown> = {
			due_date: cart.dueDate ?? undefined,
			settlement_mode: settlementMode.value,
			redeemed_customer_credit: creditApplied.value || undefined,
			customer_credit_dict: creditApplied.value
				? credit.value.filter((row) => toNumber(row.credit_to_redeem) > 0)
				: undefined,
			credit_change: change.value || undefined,
		};

		return { invoice, data };
	}

	/**
	 * Park a completed sale on the terminal.
	 *
	 * The money is in the drawer and the goods have gone, so this must not fail
	 * quietly — if even the local write fails there is nothing left holding the sale
	 * and the cashier has to be told.
	 */
	async function queueSale(invoice: Record<string, unknown>, data: Record<string, unknown>) {
		try {
			return await parkSale(invoice, data);
		} catch (error) {
			// Nothing is holding this sale now — not the server, not the terminal. The
			// cashier has to know before the customer walks away.
			ui.notify({
				title: "This sale was NOT saved",
				detail:
					"No connection, and this terminal cannot store it either. Do not hand over the goods — write the sale down and re-enter it once the connection is back.",
				tone: "danger",
				duration: 0,
			});
			throw error;
		}
	}

	async function parkSale(invoice: Record<string, unknown>, data: Record<string, unknown>) {
		const uuid = await sync.enqueue({
			invoice,
			data,
			summary: {
				customer: cart.customer,
				customer_name: cart.customerInfo?.customer_name ?? cart.customer,
				grand_total: payable.value,
				currency: session.currency,
				item_count: cart.itemCount,
			},
		});
		lastInvoice.value = { name: uuid, __queued: true };
		ui.warn(
			"Held on this terminal",
			"No connection. It sends itself as soon as the network is back — take the money and hand over the goods.",
		);
		return lastInvoice.value;
	}

	async function submit(): Promise<Record<string, unknown> | null> {
		if (!canSubmit.value) return null;
		submitting.value = true;
		try {
			// Settle the totals on the server when there is one: saving can move them
			// (first-time taxes, discount resolution), and tendering against a figure the
			// server is about to change is how "Pay" ends up rejecting a good sale.
			//
			// Offline there is nothing to settle against, so the local figures stand —
			// they come from the same arithmetic, and the server re-checks everything when
			// the queue drains.
			let draftName: string | undefined;
			try {
				const draft = await cart.saveDraft();
				draftName = draft?.name as string | undefined;
				if (!draftName) {
					ui.fail("Could not save the invoice");
					return null;
				}
				if (!touched.value) {
					clear();
					tenderExact();
				}
			} catch (error) {
				// This is where an offline sale used to die: the draft save threw before
				// anything had a chance to queue, and the cashier saw a bare "Offline".
				if (!canQueue(error)) throw error;
				const parked = buildPayload();
				return await queueSale(parked.invoice, parked.data);
			}

			const { invoice, data } = buildPayload(draftName);

			let result: Record<string, unknown>;
			try {
				result = (await api.submitInvoice(invoice, data)) as Record<string, unknown>;
			} catch (error) {
				// Anything the server actually answered — negative stock, a permission
				// refusal — is a real decision and has to reach the cashier. Only a
				// transport failure is replayable.
				if (!canQueue(error)) throw error;
				return await queueSale(invoice, data);
			}

			lastInvoice.value = result;
			ui.success(
				cart.isReturn ? "Refund complete" : "Sale complete",
				`${result.name ?? draftName}${change.value ? ` · change ${change.value}` : ""}`,
			);
			return result;
		} catch (error) {
			ui.fail(
				cart.isReturn ? "Could not complete the refund" : "Could not complete the sale",
				error instanceof Error ? error.message : String(error),
			);
			return null;
		} finally {
			submitting.value = false;
		}
	}

	return {
		rows,
		credit,
		loadingCredit,
		submitting,
		touched,
		lastInvoice,
		sign,
		paid,
		redeemed,
		creditApplied,
		creditAvailable,
		payable,
		remaining,
		outstanding,
		change,
		settled,
		hasTender,
		isCreditSale,
		isPartialPayment,
		isCustomerCreditReturn,
		settlementMode,
		canSubmit,
		build,
		reset,
		loadCredit,
		setCredit,
		applyMaxCredit,
		clearCredit,
		setAmount,
		addAmount,
		setExchangeRate,
		tenderExact,
		clear,
		submit,
	};
});
