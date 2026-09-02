/**
 * Thin client over Frappe's /api/method endpoint.
 *
 * The SPA runs on the same origin as the site, so the session cookie authenticates
 * us; we only need to echo the CSRF token that the www controller injects into the
 * page. Everything funnels through `call` so retry, offline detection and error
 * surfacing live in exactly one place.
 */

export class FrappeError extends Error {
	readonly status: number;
	readonly exception: string;
	readonly messages: string[];
	readonly raw: unknown;

	constructor(message: string, opts: { status: number; exception?: string; messages?: string[]; raw?: unknown }) {
		super(message);
		this.name = "FrappeError";
		this.status = opts.status;
		this.exception = opts.exception ?? "";
		this.messages = opts.messages ?? [];
		this.raw = opts.raw;
	}

	/** True when the session expired and the operator has to sign in again. */
	get isAuthError() {
		return this.status === 401 || this.status === 403;
	}
}

/** Raised before the request leaves the browser when we know we are offline. */
export class OfflineError extends Error {
	constructor(readonly method: string) {
		super(`Offline: ${method}`);
		this.name = "OfflineError";
	}
}

declare global {
	interface Window {
		csrf_token?: string;
		posa_boot?: { user: string; full_name?: string; sitename?: string; lang?: string };
	}
}

function csrfToken(): string {
	return window.csrf_token && window.csrf_token !== "None" ? window.csrf_token : "";
}

/** Frappe returns HTML-ish blobs in _server_messages; reduce them to plain text. */
function parseServerMessages(payload: unknown): string[] {
	const raw = (payload as { _server_messages?: string } | null)?._server_messages;
	if (!raw) return [];
	try {
		const list: string[] = JSON.parse(raw);
		return list
			.map((entry) => {
				try {
					const parsed = JSON.parse(entry) as { message?: string };
					return parsed.message ?? entry;
				} catch {
					return entry;
				}
			})
			.map(stripHtml)
			.filter(Boolean);
	} catch {
		return [];
	}
}

export function stripHtml(value: string): string {
	const el = document.createElement("div");
	el.innerHTML = value;
	return (el.textContent ?? "").trim();
}

function firstLine(messages: string[], fallback: string): string {
	return messages.length ? messages[0] : fallback;
}

export interface CallOptions {
	/** GET is cacheable by the browser and safe to retry; defaults to POST. */
	method?: "GET" | "POST";
	signal?: AbortSignal;
	/** Number of retries for transient network/5xx failures. */
	retries?: number;
	/** Skip the navigator.onLine short-circuit (used by the sync worker). */
	ignoreOffline?: boolean;
}

const RETRY_BASE_MS = 300;

export async function call<T = unknown>(
	method: string,
	args: Record<string, unknown> = {},
	options: CallOptions = {},
): Promise<T> {
	const { method: verb = "POST", signal, retries = 1, ignoreOffline = false } = options;

	if (!ignoreOffline && !navigator.onLine) throw new OfflineError(method);

	let attempt = 0;
	// Retries only cover transport-level failures. A 4xx from Frappe is a real
	// answer and is surfaced immediately.
	for (;;) {
		try {
			return await request<T>(method, args, verb, signal);
		} catch (error) {
			const transient =
				error instanceof TypeError || (error instanceof FrappeError && error.status >= 500);
			if (!transient || attempt >= retries) throw error;
			await sleep(RETRY_BASE_MS * 2 ** attempt);
			attempt += 1;
		}
	}
}

async function request<T>(
	method: string,
	args: Record<string, unknown>,
	verb: "GET" | "POST",
	signal?: AbortSignal,
): Promise<T> {
	const headers: Record<string, string> = {
		Accept: "application/json",
		"X-Frappe-Site-Name": window.location.hostname,
	};

	let url = `/api/method/${method}`;
	let body: string | undefined;

	if (verb === "GET") {
		const params = new URLSearchParams();
		for (const [key, value] of Object.entries(args)) {
			if (value === undefined || value === null) continue;
			params.set(key, typeof value === "string" ? value : JSON.stringify(value));
		}
		const qs = params.toString();
		if (qs) url += `?${qs}`;
	} else {
		headers["Content-Type"] = "application/json";
		const token = csrfToken();
		if (token) headers["X-Frappe-CSRF-Token"] = token;
		body = JSON.stringify(args);
	}

	const response = await fetch(url, {
		method: verb,
		headers,
		body,
		signal,
		credentials: "same-origin",
	});

	const text = await response.text();
	let payload: unknown = null;
	try {
		payload = text ? JSON.parse(text) : null;
	} catch {
		payload = null;
	}

	if (!response.ok) {
		const messages = parseServerMessages(payload);
		const exception = (payload as { exc_type?: string } | null)?.exc_type ?? "";
		const fallback =
			(payload as { message?: string } | null)?.message ??
			(response.status === 403
				? "You are not permitted to do this."
				: `Request failed (${response.status})`);
		throw new FrappeError(firstLine(messages, stripHtml(String(fallback))), {
			status: response.status,
			exception,
			messages,
			raw: payload,
		});
	}

	return (payload as { message?: T } | null)?.message as T;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** What the print dialog offers for one invoice. */
export interface PrintOptions {
	default_print_format: string | null;
	print_formats: string[];
	default_letterhead: string | null;
	letterheads: string[];
}

/* -------------------------------------------------------------------------- */
/* Namespaced helpers for the endpoints this app actually uses                 */
/* -------------------------------------------------------------------------- */

const NS = "posawesome.posawesome.api";

export const api = {
	/* Shift */
	openingDialogData: () => call<unknown>(`${NS}.shift.get_opening_dialog_data`, {}, { method: "GET" }),
	checkOpeningShift: (user: string) => call<unknown>(`${NS}.shift.check_opening_shift`, { user }),
	createOpeningVoucher: (payload: { pos_profile: string; company: string; balance_details: unknown }) =>
		call<unknown>(`${NS}.shift.create_opening_voucher`, payload),
	closingShiftFromOpening: (opening_shift: string) =>
		call<unknown>(`${NS}.shift.make_closing_shift_from_opening`, { opening_shift }),
	submitClosingShift: (closing_shift: unknown) =>
		call<unknown>(`${NS}.shift.submit_closing_shift`, { closing_shift }),
	shiftAnalytics: (opening_shift: string) =>
		call<unknown>(`${NS}.shift.get_shift_analytics`, { opening_shift }, { method: "GET" }),
	currencyContext: (payload: Record<string, unknown>) =>
		call<unknown>(`${NS}.currency.get_currency_context`, payload),

	/* Catalog */
	items: (payload: Record<string, unknown>) => call<unknown>(`${NS}.catalog.get_items`, payload),
	itemGroups: (pos_profile: string) =>
		call<unknown>(`${NS}.catalog.get_items_groups`, { pos_profile }, { method: "GET" }),
	itemDetail: (payload: Record<string, unknown>) => call<unknown>(`${NS}.catalog.get_item_detail`, payload),
	itemsDetails: (payload: Record<string, unknown>) => call<unknown>(`${NS}.catalog.get_items_details`, payload),
	itemAttributes: (item_code: string) => call<unknown>(`${NS}.catalog.get_item_attributes`, { item_code }),
	scan: (payload: Record<string, unknown>) => call<unknown>(`${NS}.catalog.scan_code`, payload),
	availability: (payload: Record<string, unknown>) =>
		call<unknown>(`${NS}.catalog.get_serial_batch_availability`, payload),

	/* Customers */
	customerNames: (pos_profile: string, search?: string) =>
		call<unknown>(`${NS}.customer.get_customer_names`, { pos_profile, search }),
	customerInfo: (customer: string) => call<unknown>(`${NS}.customer.get_customer_info`, { customer }),
	saveCustomer: (payload: Record<string, unknown>) => call<unknown>(`${NS}.customer.save_customer`, payload),
	customerAddresses: (customer: string) => call<unknown>(`${NS}.customer.get_customer_addresses`, { customer }),
	makeAddress: (args: Record<string, unknown>) => call<unknown>(`${NS}.customer.make_address`, { args }),
	availableCredit: (customer: string, company: string, currency?: string) =>
		call<unknown>(`${NS}.customer.get_available_credit`, { customer, company, currency }),
	salesPersons: () => call<unknown>(`${NS}.customer.get_sales_person_names`, {}, { method: "GET" }),

	/* Invoice */
	updateInvoice: (data: unknown) => call<unknown>(`${NS}.invoice_api.update_invoice`, { data }),
	submitInvoice: (invoice: unknown, data: unknown) =>
		call<unknown>(`${NS}.invoice_api.submit_invoice`, { invoice, data }),
	deleteInvoice: (invoice: string) => call<unknown>(`${NS}.invoice_api.delete_invoice`, { invoice }),
	draftInvoices: (pos_opening_shift: string) =>
		call<unknown>(`${NS}.invoice_api.get_draft_invoices`, { pos_opening_shift }),
	searchInvoicesForReturn: (invoice_name: string, company: string) =>
		call<unknown>(`${NS}.invoice_api.search_invoices_for_return`, { invoice_name, company }),
	searchOrders: (payload: Record<string, unknown>) => call<unknown>(`${NS}.invoice_api.search_orders`, payload),
	invoiceFromOrder: (sales_order: string) =>
		call<unknown>(`${NS}.invoice_api.create_sales_invoice_from_order`, { sales_order }),
	deliveryCharges: (payload: Record<string, unknown>) =>
		call<unknown>(`${NS}.invoice_api.get_applicable_delivery_charges`, payload),
	printInvoice: (invoice: string, print_format?: string, letterhead?: string | null, no_letterhead?: boolean) =>
		call<{ html: string; print_format: string }>(`${NS}.invoice_api.get_invoice_print_html`, {
			invoice,
			print_format,
			letterhead,
			no_letterhead: no_letterhead ? 1 : 0,
		}),
	printOptions: (invoice: string) =>
		call<PrintOptions>(`${NS}.invoice_api.get_print_options`, { invoice }),

	/* Offers & coupons */
	offers: (profile: string) => call<unknown>(`${NS}.offers.get_offers`, { profile }),
	coupon: (payload: Record<string, unknown>) => call<unknown>(`${NS}.offers.get_pos_coupon`, payload),
	activeGiftCoupons: (customer: string, company: string) =>
		call<unknown>(`${NS}.offers.get_active_gift_coupons`, { customer, company }),

	/* Payments workspace */
	availablePosProfiles: (company: string, currency: string) =>
		call<unknown>(`${NS}.payment_entry.get_available_pos_profiles`, { company, currency }),
	outstandingInvoices: (payload: Record<string, unknown>) =>
		call<unknown>(`${NS}.payment_entry.get_outstanding_invoices`, payload),
	unallocatedPayments: (payload: Record<string, unknown>) =>
		call<unknown>(`${NS}.payment_entry.get_unallocated_payments`, payload),
	processPosPayment: (payload: Record<string, unknown>) =>
		call<unknown>(`${NS}.payment_entry.process_pos_payment`, payload),
	createPaymentRequest: (doc: unknown) => call<unknown>(`${NS}.payment_entry.create_payment_request`, { doc }),

	/* M-Pesa */
	mpesaModes: (company: string) => call<unknown>(`${NS}.m_pesa.get_mpesa_mode_of_payment`, { company }),
	mpesaDrafts: (payload: Record<string, unknown>) =>
		call<unknown>(`${NS}.m_pesa.get_mpesa_draft_payments`, payload),
	submitMpesaPayment: (payload: Record<string, unknown>) =>
		call<unknown>(`${NS}.m_pesa.submit_mpesa_payment`, payload),

	/* Offline sync */
	syncInvoices: (batch: unknown) => call<unknown>(`${NS}.offline.sync_invoices`, { batch }, { ignoreOffline: true }),
};
