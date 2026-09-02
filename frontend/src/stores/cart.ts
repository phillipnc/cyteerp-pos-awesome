/**
 * The cart — a draft Sales Invoice held in memory.
 *
 * Lines are kept in POS terms (qty, rate, discount) and only translated into
 * Sales Invoice Item shape when the draft is saved. Totals are recomputed locally
 * on every edit for instant feedback and reconciled with the server's own
 * calculation whenever the draft round-trips.
 */
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { api } from "@/lib/api";
import { applyLineDiscount, calculateTotals, lineAmount, type TaxRow } from "@/lib/totals";
import { money, qty as roundQty, today, toNumber } from "@/lib/format";
import { uid } from "@/lib/uid";
import type { AppliedOffer, CartItem, Coupon, CustomerInfo, Item } from "@/types";
import { useSessionStore } from "./session";
import { useUiStore } from "./ui";

export interface ReturnContext {
	invoiceName: string;
	/** Original qty per source row, so a return can never exceed what was sold. */
	maxQty: Record<string, number>;
}

export const useCartStore = defineStore("cart", () => {
	const session = useSessionStore();
	const ui = useUiStore();

	/* ---------------------------------------------------------------- state */
	const invoiceName = ref<string | null>(null);
	const items = ref<CartItem[]>([]);
	const taxes = ref<TaxRow[]>([]);
	const customer = ref<string>("");
	const customerInfo = ref<CustomerInfo | null>(null);
	const salesPerson = ref<string>("");
	const postingDate = ref<string>(today());
	const dueDate = ref<string | null>(null);
	const deliveryDate = ref<string | null>(null);
	const poNumber = ref<string>("");
	const notes = ref<string>("");
	const shippingAddress = ref<string | null>(null);
	const deliveryCharges = ref<string | null>(null);
	const deliveryChargesRate = ref(0);

	const additionalDiscount = ref(0);
	const additionalDiscountPercentage = ref(0);
	/**
	 * Who set the invoice-level discount.
	 *
	 * There is one such discount on a Sales Invoice, and both the offer engine and the
	 * cashier want it. Without knowing which of them put the current value there, the
	 * engine overwrote a typed amount on the next cart change and the cashier's
	 * discount silently vanished.
	 */
	const additionalDiscountSource = ref<"manual" | "offer" | null>(null);

	const appliedOffers = ref<AppliedOffer[]>([]);
	const appliedCoupons = ref<Coupon[]>([]);
	const loyaltyPointsRedeemed = ref(0);
	const loyaltyAmount = ref(0);

	const isReturn = ref(false);
	const returnAgainst = ref<string | null>(null);
	const returnContext = ref<ReturnContext | null>(null);

	const selectedRowId = ref<string | null>(null);
	const dirty = ref(false);
	const saving = ref(false);
	const lastSavedAt = ref<number | null>(null);

	/* ------------------------------------------------------------- computed */
	const applyDiscountOn = computed(() => session.profile?.apply_discount_on || "Grand Total");
	const disableRoundedTotal = computed(() => !!session.profile?.disable_rounded_total);

	const totals = computed(() =>
		calculateTotals({
			items: items.value,
			taxes: taxes.value,
			applyDiscountOn: applyDiscountOn.value,
			discountAmount: additionalDiscount.value,
			additionalDiscountPercentage: additionalDiscountPercentage.value,
			disableRoundedTotal: disableRoundedTotal.value,
		}),
	);

	const isEmpty = computed(() => items.value.length === 0);
	const itemCount = computed(() => items.value.length);
	const totalQty = computed(() => totals.value.totalQty);
	const grandTotal = computed(() => totals.value.grandTotal);
	const payableAmount = computed(() =>
		disableRoundedTotal.value ? totals.value.grandTotal : totals.value.roundedTotal,
	);
	const selectedItem = computed(
		() => items.value.find((item) => item.posa_row_id === selectedRowId.value) ?? null,
	);

	/* -------------------------------------------------------------- helpers */

	function markDirty() {
		dirty.value = true;
	}

	/** Lines merge unless the profile asks for one row per scan, or they differ in
	 *  a way that cannot be merged (batch, serial, UOM, offer). */
	function findMergeTarget(item: Item, uom: string, batchNo?: string | null): CartItem | undefined {
		if (session.profile?.posa_new_line) return undefined;
		return items.value.find(
			(line) =>
				line.item_code === item.item_code &&
				line.uom === uom &&
				(line.batch_no ?? null) === (batchNo ?? null) &&
				!line.posa_is_offer &&
				!line.has_serial_no,
		);
	}

	function toCartItem(item: Item, overrides: Partial<CartItem> = {}): CartItem {
		const rate = money(toNumber(overrides.rate ?? item.rate));
		const line: CartItem = {
			posa_row_id: uid("row"),
			item_code: item.item_code,
			item_name: item.item_name,
			description: item.description,
			image: item.image,
			item_group: item.item_group,
			stock_uom: item.stock_uom,
			uom: overrides.uom ?? item.stock_uom,
			conversion_factor: toNumber(overrides.conversion_factor) || 1,
			qty: toNumber(overrides.qty) || 1,
			rate,
			price_list_rate: money(toNumber(overrides.price_list_rate ?? item.rate)),
			amount: 0,
			discount_percentage: 0,
			discount_amount: 0,
			max_discount: item.max_discount,
			warehouse: session.warehouse,
			is_stock_item: item.is_stock_item,
			actual_qty: toNumber(item.actual_qty),
			has_batch_no: item.has_batch_no,
			has_serial_no: item.has_serial_no,
			batch_no: null,
			serial_no: null,
			use_serial_batch_fields: item.has_batch_no || item.has_serial_no ? 1 : 0,
			batch_no_data: item.batch_no_data ?? [],
			serial_no_data: item.serial_no_data ?? [],
			item_uoms: item.item_uoms ?? [{ uom: item.stock_uom, conversion_factor: 1 }],
			posa_notes: "",
			posa_is_offer: 0,
			posa_offer_applied: 0,
			...overrides,
		};
		line.amount = lineAmount(line);
		return line;
	}

	/* ------------------------------------------------------------- mutation */

	async function addItem(
		item: Item,
		options: { qty?: number; uom?: string; batchNo?: string; serialNo?: string } = {},
	) {
		if (isReturn.value) {
			ui.warn("Return in progress", "Finish or cancel the return before adding new items.");
			return;
		}

		const uom = options.uom ?? item.stock_uom;
		const quantity = toNumber(options.qty) || 1;

		const existing = findMergeTarget(item, uom, options.batchNo);
		if (existing) {
			await setQty(existing.posa_row_id, existing.qty + quantity);
			selectedRowId.value = existing.posa_row_id;
			bump(existing.posa_row_id);
			return existing;
		}

		const conversionFactor =
			item.item_uoms?.find((entry) => entry.uom === uom)?.conversion_factor ?? 1;
		const uomRate = item.item_uoms?.find((entry) => entry.uom === uom)?.rate;

		const line = toCartItem(item, {
			qty: quantity,
			uom,
			conversion_factor: conversionFactor,
			batch_no: options.batchNo ?? null,
			serial_no: options.serialNo ?? null,
			rate: uomRate ?? item.rate * conversionFactor,
			price_list_rate: uomRate ?? item.rate * conversionFactor,
		});

		// A batch-priced item overrides the price list.
		if (options.batchNo) {
			const batch = item.batch_no_data?.find((entry) => entry.batch_no === options.batchNo);
			if (batch?.batch_price) {
				line.price_list_rate = money(batch.batch_price);
				line.rate = line.price_list_rate;
				line.amount = lineAmount(line);
			}
		}

		applyCustomerDiscount(line);

		items.value = [line, ...items.value];
		selectedRowId.value = line.posa_row_id;
		markDirty();
		bump(line.posa_row_id);

		void hydrateLine(line);
		return line;
	}

	/** A customer-level discount is applied to every new line when enabled. */
	function applyCustomerDiscount(line: CartItem) {
		if (!session.profile?.posa_apply_customer_discount) return;
		const discount = toNumber(customerInfo.value?.posa_discount);
		if (discount <= 0) return;
		line.discount_percentage = discount;
		applyLineDiscount(line, "percentage");
	}

	/** Fetch server-side detail (taxes, income account, precise rate) for a line. */
	async function hydrateLine(line: CartItem) {
		if (!session.serverReachable) return;
		try {
			const detail = (await api.itemDetail({
				item: {
					item_code: line.item_code,
					customer: customer.value,
					doctype: "Sales Invoice",
					name: invoiceName.value,
					company: session.companyName,
					conversion_rate: session.conversionRate,
					currency: session.currency,
					price_list_currency: session.priceListCurrency,
					plc_conversion_rate: session.plcConversionRate,
					is_stock_item: line.is_stock_item,
					uom: line.uom,
					stock_uom: line.stock_uom,
					qty: line.qty,
					warehouse: line.warehouse,
					pos_profile: session.profile?.name,
					transaction_type: "selling",
				},
				warehouse: line.warehouse,
				price_list: session.priceList,
			})) as Record<string, unknown> | null;

			if (!detail) return;
			const target = items.value.find((entry) => entry.posa_row_id === line.posa_row_id);
			if (!target) return;

			target.income_account = detail.income_account as string;
			target.expense_account = detail.expense_account as string;
			target.cost_center = detail.cost_center as string;
			target.item_tax_template = (detail.item_tax_template as string) ?? null;
			target.max_discount = toNumber(detail.max_discount);
			if (detail.price_list_rate !== undefined || detail.rate !== undefined) {
				target.price_list_rate = money(
					toNumber(detail.price_list_rate ?? detail.rate ?? target.price_list_rate),
				);
				target.rate = money(toNumber(detail.rate ?? detail.price_list_rate ?? target.rate));
				applyLineDiscount(target, "rate");
			}
			target.item_uoms = (detail.item_uoms as CartItem["item_uoms"]) ?? target.item_uoms;
			target.batch_no_data = (detail.batch_no_data as CartItem["batch_no_data"]) ?? target.batch_no_data;
			target.serial_no_data =
				(detail.serial_no_data as CartItem["serial_no_data"]) ?? target.serial_no_data;
			if (detail.actual_qty !== undefined) target.actual_qty = toNumber(detail.actual_qty);
		} catch {
			// A failed detail fetch is not fatal — the server fills the gaps on save.
		}
	}

	async function setQty(rowId: string, value: number) {
		const line = items.value.find((item) => item.posa_row_id === rowId);
		if (!line) return;

		const next = roundQty(value);
		// A return line counts in negatives, so "emptied" is zero from either side.
		// Crossing zero is the same gesture as clearing the line, not a sign flip.
		const wasNegative = line.qty < 0;
		if (next === 0 || (wasNegative ? next > 0 : next < 0)) {
			removeItem(rowId);
			return;
		}

		if (!validateStock(line, next)) return;
		if (!validateReturnQty(line, next)) return;

		line.qty = next;
		line.amount = lineAmount(line);
		markDirty();
	}

	function validateStock(line: CartItem, next: number): boolean {
		if (isReturn.value) return true;
		if (!line.is_stock_item) return true;
		if (session.stockSettings.allow_negative_stock) return true;
		if (next <= line.actual_qty) return true;

		ui.warn(
			`Only ${line.actual_qty} of ${line.item_name} in stock`,
			"Enable negative stock in Stock Settings to sell beyond what is on hand.",
		);
		return false;
	}

	function validateReturnQty(line: CartItem, next: number): boolean {
		if (!isReturn.value || !returnContext.value) return true;
		const limit = returnContext.value.maxQty[line.sales_invoice_item ?? ""] ?? Infinity;
		// Return quantities are negative, so compare magnitudes.
		if (Math.abs(next) <= Math.abs(limit)) return true;
		ui.warn(`Cannot return more than ${Math.abs(limit)} of ${line.item_name}`);
		return false;
	}

	/** Step the quantity by magnitude, so + always means "more of this item"
	 *  whether the line is a sale or a return. */
	function stepQty(rowId: string, delta: number) {
		const line = items.value.find((item) => item.posa_row_id === rowId);
		if (!line) return;
		const lineSign = line.qty < 0 ? -1 : 1;
		void setQty(rowId, line.qty + lineSign * delta);
	}

	function setRate(rowId: string, value: number) {
		const line = items.value.find((item) => item.posa_row_id === rowId);
		if (!line) return;
		if (!session.profile?.posa_allow_user_to_edit_rate) {
			ui.warn("Editing rates is not allowed on this POS profile");
			return;
		}
		line.rate = money(value);
		applyLineDiscount(line, "rate");
		if (!enforceMaxDiscount(line)) return;
		markDirty();
	}

	function setLineDiscount(rowId: string, value: number, mode: "percentage" | "amount") {
		const line = items.value.find((item) => item.posa_row_id === rowId);
		if (!line) return;
		if (!session.profile?.posa_allow_user_to_edit_item_discount) {
			ui.warn("Item discounts are not allowed on this POS profile");
			return;
		}
		if (mode === "percentage") line.discount_percentage = value;
		else line.discount_amount = value;
		applyLineDiscount(line, mode);
		if (!enforceMaxDiscount(line)) return;
		markDirty();
	}

	/** Roll back a discount that breaches the item's or the profile's ceiling. */
	function enforceMaxDiscount(line: CartItem): boolean {
		const itemCeiling = toNumber(line.max_discount);
		const profileCeiling = toNumber(session.profile?.posa_max_discount_allowed);
		const ceiling = Math.min(itemCeiling || Infinity, profileCeiling || Infinity);
		if (!Number.isFinite(ceiling) || line.discount_percentage <= ceiling) return true;

		line.discount_percentage = ceiling;
		applyLineDiscount(line, "percentage");
		ui.warn(`Maximum discount for ${line.item_name} is ${ceiling}%`);
		return false;
	}

	async function setUom(rowId: string, uom: string) {
		const line = items.value.find((item) => item.posa_row_id === rowId);
		if (!line) return;
		const option = line.item_uoms?.find((entry) => entry.uom === uom);
		if (!option) return;

		const previousFactor = line.conversion_factor || 1;
		line.uom = uom;
		line.conversion_factor = option.conversion_factor;
		// Prefer an explicit Item Price for this UOM. Only derive from the conversion
		// factor when the price list has no UOM-specific row.
		const ratio = option.conversion_factor / previousFactor;
		line.price_list_rate = money(option.rate ?? line.price_list_rate * ratio);
		applyLineDiscount(line, "percentage");
		markDirty();
		void hydrateLine(line);
	}

	function setSerialBatch(rowId: string, payload: { batch_no?: string | null; serial_no?: string | null }) {
		const line = items.value.find((item) => item.posa_row_id === rowId);
		if (!line) return;
		if (payload.batch_no !== undefined) {
			line.batch_no = payload.batch_no;
			// A batch-priced item re-prices when its batch is picked, matching the
			// price override applied when the batch arrived from a scan.
			if (payload.batch_no) {
				const batch = line.batch_no_data?.find((entry) => entry.batch_no === payload.batch_no);
				if (batch?.batch_price) {
					line.price_list_rate = money(batch.batch_price);
					line.rate = line.price_list_rate;
					line.discount_percentage = 0;
					line.discount_amount = 0;
					line.amount = lineAmount(line);
				}
			}
		}
		if (payload.serial_no !== undefined) {
			line.serial_no = payload.serial_no;
			// Serialised items are sold one unit per number.
			const count = payload.serial_no ? payload.serial_no.split("\n").filter(Boolean).length : 0;
			if (count) line.qty = isReturn.value ? -count : count;
			line.amount = lineAmount(line);
		}
		// v16: these two fields only reach the ledger when the flag is set.
		line.use_serial_batch_fields = 1;
		markDirty();
	}

	function setNotes(rowId: string, value: string) {
		const line = items.value.find((item) => item.posa_row_id === rowId);
		if (!line) return;
		line.posa_notes = value;
		markDirty();
	}

	function removeItem(rowId: string) {
		const line = items.value.find((item) => item.posa_row_id === rowId);
		if (line?.posa_is_offer) {
			ui.warn("This line came from an offer", "Remove the offer instead.");
			return;
		}
		items.value = items.value.filter((item) => item.posa_row_id !== rowId);
		if (selectedRowId.value === rowId) selectedRowId.value = items.value[0]?.posa_row_id ?? null;
		markDirty();
	}

	function setAdditionalDiscount(
		value: number,
		mode: "amount" | "percentage",
		source: "manual" | "offer" = "manual",
	) {
		// A cashier's explicit discount outranks an offer's. The offer engine re-runs on
		// every cart change, so without this the typed figure lasts until the next scan.
		if (source === "offer" && additionalDiscountSource.value === "manual") {
			if (additionalDiscount.value || additionalDiscountPercentage.value) return;
		}
		if (source === "manual" && !session.profile?.posa_allow_user_to_edit_additional_discount) {
			ui.warn("Additional discounts are not allowed on this POS profile");
			return;
		}
		if (mode === "percentage") {
			additionalDiscountPercentage.value = Math.min(Math.max(value, 0), 100);
			additionalDiscount.value = 0;
		} else {
			additionalDiscount.value = Math.max(money(value), 0);
			additionalDiscountPercentage.value = 0;
		}
		// Back to nothing means nobody owns it, so an offer may claim it again.
		additionalDiscountSource.value =
			additionalDiscount.value || additionalDiscountPercentage.value ? source : null;
		markDirty();
	}

	/** The currency value a redemption is worth at the customer's conversion factor. */
	const maxLoyaltyAmount = computed(() => {
		const factor = toNumber(customerInfo.value?.conversion_factor);
		if (!factor) return 0;
		return money(toNumber(customerInfo.value?.loyalty_points) * factor);
	});

	function setLoyaltyRedemption(amount: number) {
		const value = money(Math.min(Math.max(toNumber(amount), 0), maxLoyaltyAmount.value));
		const factor = toNumber(customerInfo.value?.conversion_factor);
		loyaltyAmount.value = value;
		loyaltyPointsRedeemed.value = factor ? Math.floor(value / factor) : 0;
		if (toNumber(amount) > maxLoyaltyAmount.value)
			ui.warn("Loyalty amount capped", `Cannot redeem more than ${maxLoyaltyAmount.value}.`);
		markDirty();
	}

	/* ---------------------------------------------------------- persistence */

	/** The payload `update_invoice` expects. */
	function toInvoicePayload(): Record<string, unknown> {
		const profile = session.profile;
		return {
			doctype: "Sales Invoice",
			name: invoiceName.value ?? undefined,
			is_pos: 1,
			company: session.companyName,
			pos_profile: profile?.name,
			posa_pos_opening_shift: session.shiftName,
			customer: customer.value,
			currency: session.currency,
			conversion_rate: session.conversionRate,
			price_list_currency: session.priceListCurrency,
			plc_conversion_rate: session.plcConversionRate,
			selling_price_list: session.priceList,
			set_warehouse: session.warehouse,
			posting_date: postingDate.value,
			due_date: dueDate.value ?? undefined,
			is_return: isReturn.value ? 1 : 0,
			return_against: returnAgainst.value ?? undefined,
			update_stock: profile?.update_stock ?? 0,
			ignore_pricing_rule: profile?.ignore_pricing_rule ?? 1,
			apply_discount_on: applyDiscountOn.value,
			additional_discount_percentage: additionalDiscountPercentage.value || 0,
			discount_amount: additionalDiscount.value || 0,
			taxes_and_charges: profile?.taxes_and_charges,
			tc_name: profile?.tc_name,
			po_no: poNumber.value || undefined,
			posa_notes: notes.value || undefined,
			posa_delivery_date: deliveryDate.value ?? undefined,
			shipping_address_name: shippingAddress.value ?? undefined,
			posa_delivery_charges: deliveryCharges.value ?? undefined,
			posa_delivery_charges_rate: deliveryChargesRate.value || undefined,
			loyalty_program: customerInfo.value?.loyalty_program ?? undefined,
			loyalty_points: loyaltyPointsRedeemed.value || 0,
			loyalty_amount: loyaltyAmount.value || 0,
			redeem_loyalty_points: loyaltyPointsRedeemed.value > 0 ? 1 : 0,
			posa_offers: appliedOffers.value,
			posa_coupons: appliedCoupons.value,
			sales_team: salesPerson.value
				? [{ sales_person: salesPerson.value, allocated_percentage: 100 }]
				: [],
			items: items.value.map(toInvoiceItem),
		};
	}

	function toInvoiceItem(line: CartItem) {
		return {
			item_code: line.item_code,
			item_name: line.item_name,
			description: line.description,
			qty: line.qty,
			uom: line.uom,
			stock_uom: line.stock_uom,
			conversion_factor: line.conversion_factor,
			rate: line.rate,
			price_list_rate: line.price_list_rate,
			discount_percentage: line.discount_percentage,
			discount_amount: line.discount_amount,
			warehouse: line.warehouse,
			income_account: line.income_account,
			expense_account: line.expense_account,
			cost_center: line.cost_center,
			item_tax_template: line.item_tax_template,
			is_free_item: line.is_free_item ?? 0,
			batch_no: line.batch_no || undefined,
			serial_no: line.serial_no || undefined,
			// v16: without this flag ERPNext ignores batch_no/serial_no entirely.
			use_serial_batch_fields: line.batch_no || line.serial_no ? 1 : 0,
			posa_row_id: line.posa_row_id,
			posa_notes: line.posa_notes || undefined,
			posa_offers: line.posa_offers,
			posa_offer_applied: line.posa_offer_applied ?? 0,
			posa_is_offer: line.posa_is_offer ?? 0,
			posa_is_replace: line.posa_is_replace,
			posa_delivery_date: line.posa_delivery_date ?? undefined,
			sales_order: line.sales_order ?? undefined,
			so_detail: line.so_detail ?? undefined,
			sales_invoice_item: line.sales_invoice_item ?? undefined,
		};
	}

	/** Persist the draft and adopt the server's authoritative totals. */
	async function saveDraft(): Promise<Record<string, unknown> | null> {
		if (isEmpty.value || !customer.value) return null;
		saving.value = true;
		try {
			const doc = (await api.updateInvoice(toInvoicePayload())) as Record<string, unknown>;
			adoptServerDoc(doc);
			dirty.value = false;
			lastSavedAt.value = Date.now();
			return doc;
		} finally {
			saving.value = false;
		}
	}

	/** Take the server's numbers as truth after a save. */
	function adoptServerDoc(doc: Record<string, unknown>) {
		invoiceName.value = (doc.name as string) ?? invoiceName.value;
		taxes.value = ((doc.taxes as TaxRow[]) ?? []).map((tax, index) => ({ ...tax, idx: index + 1 }));

		const serverItems = (doc.items as Record<string, unknown>[]) ?? [];
		for (const serverItem of serverItems) {
			const line = items.value.find((entry) => entry.posa_row_id === serverItem.posa_row_id);
			if (!line) continue;
			line.rate = toNumber(serverItem.rate);
			line.price_list_rate = toNumber(serverItem.price_list_rate);
			line.amount = toNumber(serverItem.amount);
			line.discount_amount = toNumber(serverItem.discount_amount);
			line.discount_percentage = toNumber(serverItem.discount_percentage);
			line.income_account = serverItem.income_account as string;
			line.cost_center = serverItem.cost_center as string;
		}

		if (doc.discount_amount !== undefined) additionalDiscount.value = toNumber(doc.discount_amount);
		if (doc.additional_discount_percentage !== undefined)
			additionalDiscountPercentage.value = toNumber(doc.additional_discount_percentage);
	}

	/* ------------------------------------------------------------- lifecycle */

	function reset() {
		clearBumps();
		invoiceName.value = null;
		items.value = [];
		taxes.value = [];
		additionalDiscount.value = 0;
		additionalDiscountPercentage.value = 0;
		additionalDiscountSource.value = null;
		appliedOffers.value = [];
		appliedCoupons.value = [];
		loyaltyPointsRedeemed.value = 0;
		loyaltyAmount.value = 0;
		isReturn.value = false;
		returnAgainst.value = null;
		returnContext.value = null;
		selectedRowId.value = null;
		notes.value = "";
		poNumber.value = "";
		dueDate.value = null;
		deliveryDate.value = null;
		shippingAddress.value = null;
		deliveryCharges.value = null;
		deliveryChargesRate.value = 0;
		postingDate.value = today();
		dirty.value = false;
		lastSavedAt.value = null;
		customer.value = session.profile?.customer ?? "";
		customerInfo.value = null;
	}

	/**
	 * Abandon a return in progress and go back to selling.
	 *
	 * Nothing has been submitted at this point, so there is nothing to reverse — the
	 * cart is simply cleared. Separate from `reset()` so the caller reads as the
	 * intent ("changed my mind") rather than as the mechanism.
	 */
	function cancelReturn() {
		if (!isReturn.value) return;
		reset();
	}

	function loadFromDoc(doc: Record<string, unknown>, options: { asReturn?: boolean } = {}) {
		reset();
		invoiceName.value = options.asReturn ? null : ((doc.name as string) ?? null);
		customer.value = (doc.customer as string) ?? "";
		notes.value = (doc.posa_notes as string) ?? "";
		poNumber.value = (doc.po_no as string) ?? "";
		postingDate.value = (doc.posting_date as string) ?? today();
		additionalDiscount.value = toNumber(doc.discount_amount);
		additionalDiscountPercentage.value = toNumber(doc.additional_discount_percentage);
		taxes.value = (doc.taxes as TaxRow[]) ?? [];
		appliedOffers.value = (doc.posa_offers as AppliedOffer[]) ?? [];
		appliedCoupons.value = (doc.posa_coupons as Coupon[]) ?? [];

		const sign = options.asReturn ? -1 : 1;
			const maxQty: Record<string, number> = {};

			items.value = ((doc.items as Record<string, unknown>[]) ?? []).map((row) => {
				const rowId = (row.posa_row_id as string) || uid("row");
				const returnableQty = toNumber(row.posa_returnable_qty ?? row.qty);
				const originalQty = Math.abs(toNumber(row.qty));
				const returnRatio = originalQty ? returnableQty / originalQty : 0;
				if (options.asReturn) maxQty[row.name as string] = -returnableQty;
				const line: CartItem = {
				posa_row_id: rowId,
				item_code: row.item_code as string,
				item_name: row.item_name as string,
				description: row.description as string,
				image: (row.image as string) ?? null,
				item_group: (row.item_group as string) ?? "",
				stock_uom: row.stock_uom as string,
				uom: row.uom as string,
				conversion_factor: toNumber(row.conversion_factor) || 1,
					qty: sign * returnableQty,
					rate: toNumber(row.rate),
					price_list_rate: toNumber(row.price_list_rate),
					amount: sign * money(Math.abs(toNumber(row.amount)) * returnRatio),
					discount_percentage: toNumber(row.discount_percentage),
					discount_amount: money(toNumber(row.discount_amount) * returnRatio),
				warehouse: (row.warehouse as string) ?? session.warehouse,
				income_account: row.income_account as string,
				cost_center: row.cost_center as string,
				item_tax_template: (row.item_tax_template as string) ?? null,
				is_stock_item: 1,
				actual_qty: 0,
				has_batch_no: row.batch_no ? 1 : 0,
				has_serial_no: row.serial_no ? 1 : 0,
				batch_no: (row.batch_no as string) ?? null,
				serial_no: (row.serial_no as string) ?? null,
				use_serial_batch_fields: row.batch_no || row.serial_no ? 1 : 0,
				item_uoms: [{ uom: row.uom as string, conversion_factor: toNumber(row.conversion_factor) || 1 }],
				posa_notes: (row.posa_notes as string) ?? "",
				posa_is_offer: (row.posa_is_offer as 0 | 1) ?? 0,
				posa_offer_applied: (row.posa_offer_applied as 0 | 1) ?? 0,
				sales_invoice_item: options.asReturn ? (row.name as string) : null,
			};
			return line;
		});

		if (options.asReturn) {
			isReturn.value = true;
			returnAgainst.value = doc.name as string;
			returnContext.value = { invoiceName: doc.name as string, maxQty };
		}

		selectedRowId.value = items.value[0]?.posa_row_id ?? null;
		markDirty();
	}

	/* --------------------------------------------------------- micro-effects */

	/** Row ids that should play the "just changed" animation. */
	const bumped = ref<Set<string>>(new Set());
	/** Pending un-bump per row, so repeated presses extend rather than restart. */
	const bumpTimers = new Map<string, number>();

	/**
	 * Flash a line to acknowledge it just changed.
	 *
	 * Each press used to set its own timer, so scanning the same item four times
	 * stripped and re-added the class four times and the animation stuttered through
	 * it. The class is applied once and its removal is pushed back instead: CSS will
	 * not restart an animation whose class never left, so the nudge plays once and
	 * the line simply stays lit while the presses keep coming.
	 */
	function bump(rowId: string) {
		const pending = bumpTimers.get(rowId);
		if (pending !== undefined) window.clearTimeout(pending);
		else bumped.value = new Set(bumped.value).add(rowId);

		bumpTimers.set(
			rowId,
			window.setTimeout(() => {
				bumpTimers.delete(rowId);
				const next = new Set(bumped.value);
				next.delete(rowId);
				bumped.value = next;
			}, 400),
		);
	}

	function clearBumps() {
		for (const timer of bumpTimers.values()) window.clearTimeout(timer);
		bumpTimers.clear();
		bumped.value = new Set();
	}

	// Any structural change invalidates the saved draft.
	watch(items, markDirty, { deep: true });

	return {
		invoiceName,
		items,
		taxes,
		customer,
		customerInfo,
		salesPerson,
		postingDate,
		dueDate,
		deliveryDate,
		poNumber,
		notes,
		shippingAddress,
		deliveryCharges,
		deliveryChargesRate,
		additionalDiscount,
		additionalDiscountPercentage,
		additionalDiscountSource,
		appliedOffers,
		appliedCoupons,
		loyaltyPointsRedeemed,
		loyaltyAmount,
		isReturn,
		returnAgainst,
		returnContext,
		selectedRowId,
		dirty,
		saving,
		lastSavedAt,
		bumped,

		totals,
		isEmpty,
		itemCount,
		totalQty,
		grandTotal,
		payableAmount,
		selectedItem,
		applyDiscountOn,

		addItem,
		setQty,
		stepQty,
		setRate,
		setLineDiscount,
		setUom,
		setSerialBatch,
		setNotes,
		removeItem,
		setAdditionalDiscount,
		maxLoyaltyAmount,
		setLoyaltyRedemption,
		saveDraft,
		toInvoicePayload,
		adoptServerDoc,
		reset,
		cancelReturn,
		loadFromDoc,
		bump,
	};
});
