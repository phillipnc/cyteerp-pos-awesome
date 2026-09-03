/** Shapes returned by the POS Awesome backend. Kept deliberately loose where the
 *  server hands back whole Frappe documents. */

export interface POSProfile {
	name: string;
	company: string;
	currency: string;
	warehouse: string;
	selling_price_list: string;
	customer?: string;
	cost_center?: string;
	write_off_account?: string;
	write_off_cost_center?: string;
	account_for_change_amount?: string;
	tc_name?: string;
	taxes_and_charges?: string;
	apply_discount_on?: string;
	disable_rounded_total?: 0 | 1;
	update_stock?: 0 | 1;
	ignore_pricing_rule?: 0 | 1;
	payments: PaymentMethod[];

	/* POS Awesome switches */
	posa_allow_delete?: 0 | 1;
	posa_allow_user_to_edit_rate?: 0 | 1;
	posa_allow_user_to_edit_additional_discount?: 0 | 1;
	posa_allow_user_to_edit_item_discount?: 0 | 1;
	posa_display_items_in_stock?: 0 | 1;
	posa_allow_submissions_in_background_job?: 0 | 1;
	posa_allow_partial_payment?: 0 | 1;
	posa_allow_credit_sale?: 0 | 1;
	posa_max_discount_allowed?: number;
	posa_allow_return?: 0 | 1;
	posa_scale_barcode_start?: string;
	posa_local_storage?: 0 | 1;
	posa_cash_mode_of_payment?: string;
	use_customer_credit?: 0 | 1;
	use_cashback?: 0 | 1;
	posa_hide_closing_shift?: 0 | 1;
	posa_apply_customer_discount?: 0 | 1;
	posa_auto_set_batch?: 0 | 1;
	posa_search_serial_no?: 0 | 1;
	posa_search_batch_no?: 0 | 1;
	posa_allow_sales_order?: 0 | 1;
	custom_allow_select_sales_order?: 0 | 1;
	posa_show_template_items?: 0 | 1;
	posa_hide_variants_items?: 0 | 1;
	posa_fetch_coupon?: 0 | 1;
	posa_tax_inclusive?: 0 | 1;
	posa_use_percentage_discount?: 0 | 1;
	posa_allow_customer_purchase_order?: 0 | 1;
	posa_allow_print_last_invoice?: 0 | 1;
	posa_display_additional_notes?: 0 | 1;
	posa_allow_write_off_change?: 0 | 1;
	posa_new_line?: 0 | 1;
	posa_input_qty?: 0 | 1;
	posa_display_item_code?: 0 | 1;
	posa_allow_zero_rated_items?: 0 | 1;
	posa_allow_print_draft_invoices?: 0 | 1;
	posa_auto_set_delivery_charges?: 0 | 1;
	posa_use_delivery_charges?: 0 | 1;
	hide_expected_amount?: 0 | 1;
	posa_allow_change_posting_date?: 0 | 1;
	posa_default_card_view?: 0 | 1;
	posa_default_sales_order?: 0 | 1;
	posa_use_server_cache?: 0 | 1;
	posa_server_cache_duration?: number;
	posa_allow_duplicate_customer_names?: 0 | 1;
	pose_use_limit_search?: 0 | 1;
	posa_search_limit?: number;
	posa_use_pos_awesome_payments?: 0 | 1;
	posa_allow_make_new_payments?: 0 | 1;
	posa_allow_reconcile_payments?: 0 | 1;
	posa_allow_mpesa_reconcile_payments?: 0 | 1;
	posa_allow_offline_mode?: 0 | 1;
	posa_offline_cache_ttl?: number;
	posa_offline_max_queue?: number;
	posa_enable_multi_currency?: 0 | 1;
	posa_allow_invoice_currency_selection?: 0 | 1;
	posa_allow_mixed_currency_tender?: 0 | 1;
	posa_allowed_currencies?: string;
	posa_exchange_rate_tolerance?: number;
	[key: string]: unknown;
}

export interface PaymentMethod {
	name?: string;
	mode_of_payment: string;
	default?: 0 | 1;
	allow_in_returns?: 0 | 1;
	account?: string;
	type?: string;
	currency?: string;
	exchange_rate?: number;
	amount?: number;
	base_amount?: number;
	idx?: number;
}

export interface Barcode {
	barcode: string;
	posa_uom?: string | null;
}

export interface BatchInfo {
	batch_no: string;
	batch_qty: number;
	expiry_date: string | null;
	batch_price: number | null;
	manufacturing_date: string | null;
}

export interface SerialInfo {
	serial_no: string;
	warehouse?: string;
	batch_no?: string | null;
}

export interface UOMOption {
	uom: string;
	conversion_factor: number;
	/** Price in the active invoice currency. Falls back to conversion-factor pricing. */
	rate?: number;
}

export interface Item {
	item_code: string;
	item_name: string;
	description?: string;
	stock_uom: string;
	image?: string | null;
	is_stock_item: 0 | 1;
	has_variants: 0 | 1;
	variant_of?: string | null;
	item_group: string;
	brand?: string | null;
	has_batch_no: 0 | 1;
	has_serial_no: 0 | 1;
	max_discount?: number;
	rate: number;
	currency: string;
	actual_qty: number;
	item_barcode: Barcode[];
	item_uoms?: UOMOption[];
	batch_no_data?: BatchInfo[];
	serial_no_data?: SerialInfo[];
	scanned_barcode?: string | null;
	scanned_uom?: string | null;
	scanned_serial_no?: string | null;
	scanned_batch_no?: string | null;
	attributes?: ItemAttribute[] | "";
	item_attributes?: { attribute: string; attribute_value: string }[] | "";
}

export interface ItemAttribute {
	attribute: string;
	optional?: boolean;
	values: { attribute_value: string; abbr: string }[];
}

/** One line in the cart. Mirrors Sales Invoice Item plus POS-only bookkeeping. */
export interface CartItem {
	/** Stable client-side row id; becomes posa_row_id on the server. */
	posa_row_id: string;
	item_code: string;
	item_name: string;
	description?: string;
	image?: string | null;
	item_group: string;
	stock_uom: string;
	uom: string;
	conversion_factor: number;
	qty: number;
	rate: number;
	price_list_rate: number;
	base_price_list_rate?: number;
	amount: number;
	discount_percentage: number;
	discount_amount: number;
	max_discount?: number;
	warehouse: string;
	income_account?: string;
	expense_account?: string;
	cost_center?: string;
	item_tax_template?: string | null;
	is_free_item?: 0 | 1;
	is_stock_item: 0 | 1;
	actual_qty: number;

	has_batch_no: 0 | 1;
	has_serial_no: 0 | 1;
	batch_no?: string | null;
	serial_no?: string | null;
	/** v16: entries are materialised into a Serial and Batch Bundle on submit. */
	use_serial_batch_fields: 0 | 1;
	serial_and_batch_bundle?: string | null;
	batch_no_data?: BatchInfo[];
	serial_no_data?: SerialInfo[];
	item_uoms?: UOMOption[];

	/** JSON array of applied offer row ids, as stored in the Small Text field. */
	posa_offers?: string;
	posa_offer_applied?: 0 | 1;
	posa_is_offer?: 0 | 1;
	posa_is_replace?: string | null;
	posa_notes?: string;
	posa_delivery_date?: string | null;

	sales_order?: string | null;
	so_detail?: string | null;
	/** Present only on return lines — the row being returned against. */
	sales_invoice_item?: string | null;
}

export interface Customer {
	name: string;
	customer_name: string;
	mobile_no?: string | null;
	email_id?: string | null;
	tax_id?: string | null;
	primary_address?: string | null;
}

export interface CustomerInfo {
	name: string;
	customer_name: string;
	email_id?: string;
	mobile_no?: string;
	image?: string;
	loyalty_program?: string;
	loyalty_points?: number;
	conversion_factor?: number;
	customer_price_list?: string;
	customer_group_price_list?: string;
	customer_group?: string;
	customer_type?: string;
	territory?: string;
	birthday?: string;
	gender?: string;
	tax_id?: string;
	posa_discount?: number;
	/** Auto-created on insert when the company enables referrals. */
	posa_referral_code?: string;
}

export interface POSOffer {
	name: string;
	title: string;
	offer: "Item Price" | "Grand Total" | "Give Product" | "Loyalty Point";
	apply_on: "Item Code" | "Item Group" | "Brand" | "Transaction";
	item?: string;
	item_group?: string;
	brand?: string;
	apply_type?: "Item Code" | "Item Group";
	apply_item_code?: string;
	apply_item_group?: string;
	discount_type?: "Rate" | "Discount Percentage" | "Discount Amount";
	rate?: number;
	discount_percentage?: number;
	discount_amount?: number;
	min_qty?: number;
	max_qty?: number;
	min_amt?: number;
	max_amt?: number;
	given_qty?: number;
	given_item?: string;
	replace_item?: 0 | 1;
	replace_cheapest_item?: 0 | 1;
	apply_for?: string;
	coupon_based?: 0 | 1;
	auto?: 0 | 1;
	loyalty_points?: number;
	loyalty_program?: string;
	description?: string;
	less_then?: number;
	/** Client-side only */
	offer_applied?: boolean;
	row_id?: string;
	items?: string[];
	give_item?: string;
}

export interface AppliedOffer {
	row_id: string;
	offer_name: string;
	offer: string;
	apply_on: string;
	items?: string;
	item?: string;
	applied: 0 | 1;
	offer_applied?: 0 | 1;
	coupon?: string;
	give_item?: string;
}

/**
 * One row of Sales Invoice.posa_coupons, which is a POS Coupon Detail table.
 *
 * The keys are the child doctype's fieldnames because this object is sent straight
 * into the invoice. `coupon`, `pos_offer` and `coupon_code` are all mandatory there,
 * and `coupon` is the POS Coupon *document name* — not the code the cashier typed.
 * The server increments the used-count by that name, and the once-per-customer rule
 * counts these rows by `customer`, so an incomplete row breaks both.
 */
export interface Coupon {
	/** POS Coupon docname. Mandatory server-side. */
	coupon?: string;
	coupon_code: string;
	pos_offer?: string;
	/** Mirrors POS Coupon.coupon_type — "Promotional" or "Gift Card". */
	type?: string;
	customer?: string;
	applied?: 0 | 1;
}

export interface OpeningShift {
	name: string;
	pos_profile: string;
	company: string;
	period_start_date: string;
	user: string;
	status: string;
	balance_details: {
		mode_of_payment: string;
		currency: string;
		opening_amount?: number;
		amount?: number;
		company_exchange_rate?: number;
		company_amount?: number;
	}[];
}

export interface ShiftBootstrap {
	pos_opening_shift: OpeningShift;
	pos_profile: POSProfile;
	company: { name: string; default_currency: string; [k: string]: unknown };
	stock_settings: { allow_negative_stock: 0 | 1 };
	payments_method: PaymentMethod[];
	currency_precision: number;
	float_precision: number;
	item_price_precision?: number;
	pos_settings?: Record<string, unknown>;
	currency_context?: CurrencyContext;
}

export interface CurrencyContext {
	invoice_currency: string;
	company_currency: string;
	price_list: string;
	price_list_currency: string;
	conversion_rate: number;
	plc_conversion_rate: number;
	item_rate_factor: number;
	allowed_currencies: string[];
	currency_symbols: Record<string, string>;
	payment_methods: PaymentMethod[];
	allow_invoice_currency_selection: boolean;
	allow_mixed_currency_tender: boolean;
}

export interface CreditRow {
	type: "Invoice" | "Advance";
	credit_origin: string;
	total_credit: number;
	credit_to_redeem: number;
	currency?: string;
}

export interface ShiftAnalytics {
	shift: string;
	opened_at: string;
	invoice_count: number;
	return_count: number;
	net_total: number;
	grand_total: number;
	total_returned: number;
	net_sales: number;
	average_basket: number;
	total_qty: number;
	total_discount: number;
	payment_mix: {
		key: string;
		mode_of_payment: string;
		currency: string;
		opening_amount: number;
		transaction_amount: number;
		expected_amount: number;
		company_opening_amount: number;
		company_transaction_amount: number;
		company_expected_amount: number;
		amount: number;
	}[];
	currency_totals: {
		currency: string;
		invoice_count: number;
		return_count: number;
		sales: number;
		returns: number;
		net_sales: number;
		net_total: number;
		discount: number;
	}[];
	top_items: {
		item_code: string;
		item_name: string;
		stock_uom?: string;
		qty: number;
		amount: number;
	}[];
	hourly: { hour: number; amount: number; count: number }[];
	currency: string;
	company_currency: string;
}
