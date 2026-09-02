/**
 * Session store — the shift, the profile, and the connection.
 *
 * Everything downstream reads its configuration from here, so this is the first
 * thing to resolve on boot and the only place that knows whether a shift is open.
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api, FrappeError, OfflineError } from "@/lib/api";
import { configureFormatting, type RoundingMethod } from "@/lib/format";
import { readMeta, writeMeta } from "@/lib/db";
import type {
	CurrencyContext,
	CustomerInfo,
	OpeningShift,
	PaymentMethod,
	POSProfile,
} from "@/types";

interface Bootstrap {
	pos_opening_shift: OpeningShift;
	pos_profile: POSProfile;
	company: Record<string, unknown>;
	stock_settings: { allow_negative_stock: 0 | 1; pick_serial_and_batch_based_on?: string };
	currency_symbol: string;
	currency_precision: number;
	float_precision: number;
	number_format: string;
	date_format: string;
	rounding_method?: string;
	pos_settings?: Record<string, unknown>;
	currency_context?: CurrencyContext;
}

export const useSessionStore = defineStore("session", () => {
	const profile = ref<POSProfile | null>(null);
	const shift = ref<OpeningShift | null>(null);
	const company = ref<Record<string, unknown> | null>(null);
	const stockSettings = ref<{ allow_negative_stock: 0 | 1 }>({ allow_negative_stock: 0 });
	const posSettings = ref<Record<string, unknown>>({});
	const activePriceList = ref("");
	const pricingCustomer = ref<string | null>(null);
	const currencyContext = ref<CurrencyContext | null>(null);
	const user = ref(window.posa_boot?.user ?? "");
	const fullName = ref(window.posa_boot?.full_name ?? "");

	const ready = ref(false);
	const booting = ref(true);
	const bootError = ref<string | null>(null);
	const needsOpeningShift = ref(false);

	const online = ref(navigator.onLine);
	/** True once we have confirmed the server is actually reachable, not just that
	 *  the OS thinks there is a network. */
	const serverReachable = ref(navigator.onLine);

	const currency = computed(
		() => currencyContext.value?.invoice_currency ?? profile.value?.currency ?? "USD",
	);
	const companyCurrency = computed(
		() =>
			currencyContext.value?.company_currency ??
			(company.value?.default_currency as string | undefined) ??
			currency.value,
	);
	const priceListCurrency = computed(
		() => currencyContext.value?.price_list_currency ?? currency.value,
	);
	const conversionRate = computed(() => currencyContext.value?.conversion_rate ?? 1);
	const plcConversionRate = computed(() => currencyContext.value?.plc_conversion_rate ?? 1);
	const currencyOptions = computed(() => currencyContext.value?.allowed_currencies ?? [currency.value]);
	const warehouse = computed(() => profile.value?.warehouse ?? "");
	const priceList = computed(() => activePriceList.value || profile.value?.selling_price_list || "");
	const companyName = computed(() => profile.value?.company ?? "");
	const shiftName = computed(() => shift.value?.name ?? "");
	const offlineEnabled = computed(() => !!profile.value?.posa_allow_offline_mode);
	const canWorkOffline = computed(() => offlineEnabled.value && ready.value);

	const paymentMethods = computed<PaymentMethod[]>(
		() => currencyContext.value?.payment_methods ?? profile.value?.payments ?? [],
	);
	const defaultPaymentMethod = computed(
		() => paymentMethods.value.find((method) => method.default) ?? paymentMethods.value[0] ?? null,
	);

	function applyBootstrap(payload: Bootstrap) {
		profile.value = payload.pos_profile;
		shift.value = payload.pos_opening_shift;
		company.value = payload.company;
		stockSettings.value = payload.stock_settings ?? { allow_negative_stock: 0 };
		posSettings.value = payload.pos_settings ?? {};
		activePriceList.value = payload.pos_profile.selling_price_list;
		pricingCustomer.value = null;
		currencyContext.value = payload.currency_context ?? null;

		configureFormatting({
			numberFormat: payload.number_format,
			currency: currency.value,
			currencySymbol:
				currencyContext.value?.currency_symbols[currency.value] ?? payload.currency_symbol,
			currencyPrecision: payload.currency_precision,
			floatPrecision: payload.float_precision,
			dateFormat: payload.date_format,
			roundingMethod: (payload.rounding_method as RoundingMethod) || "Banker's Rounding",
		});

		needsOpeningShift.value = false;
		ready.value = true;
		// Keep the last good bootstrap so an offline reload can still open the till.
		void writeMeta("bootstrap", payload);
	}

	async function boot() {
		booting.value = true;
		bootError.value = null;
		try {
			const payload = (await api.checkOpeningShift(user.value)) as Bootstrap | "";
			if (!payload) {
				needsOpeningShift.value = true;
				ready.value = false;
			} else {
				applyBootstrap(payload);
			}
			serverReachable.value = true;
		} catch (error) {
			if (error instanceof OfflineError || error instanceof TypeError) {
				serverReachable.value = false;
				// Fall back to the cached shift so an offline terminal still opens.
				const cached = await readMeta<Bootstrap>("bootstrap");
				if (cached) {
					applyBootstrap(cached);
					bootError.value = null;
				} else {
					bootError.value = "No connection, and this terminal has no cached shift yet.";
				}
			} else if (error instanceof FrappeError && error.isAuthError) {
				window.location.href = `/login?redirect-to=${encodeURIComponent("/posawesome")}`;
				return;
			} else {
				bootError.value = error instanceof Error ? error.message : String(error);
			}
		} finally {
			booting.value = false;
		}
	}

	async function openShift(payload: { pos_profile: string; company: string; balance_details: unknown }) {
		const result = (await api.createOpeningVoucher(payload)) as Bootstrap;
		applyBootstrap(result);
		return result;
	}

	function endShift() {
		shift.value = null;
		profile.value = null;
		ready.value = false;
		needsOpeningShift.value = true;
		activePriceList.value = "";
		pricingCustomer.value = null;
		currencyContext.value = null;
	}

	/** Apply the customer's own price list, then the customer-group list, before
	 * falling back to the POS Profile list. Returns true when the catalog must reload. */
	function applyCustomerPricing(info: CustomerInfo | null): boolean {
		const next =
			info?.customer_price_list ||
			info?.customer_group_price_list ||
			profile.value?.selling_price_list ||
			"";
		const customer = info?.name ?? null;
		const changed = activePriceList.value !== next || pricingCustomer.value !== customer;
		activePriceList.value = next;
		pricingCustomer.value = customer;
		return changed;
	}

	function applyCurrencyContext(context: CurrencyContext) {
		currencyContext.value = context;
		configureFormatting({
			currency: context.invoice_currency,
			currencySymbol:
				context.currency_symbols[context.invoice_currency] ?? context.invoice_currency,
		});
	}

	async function refreshCurrencyContext(invoiceCurrency = currency.value) {
		if (!profile.value) return null;
		const context = (await api.currencyContext({
			pos_profile: profile.value.name,
			invoice_currency: invoiceCurrency,
			price_list: priceList.value,
		})) as CurrencyContext;
		applyCurrencyContext(context);
		return context;
	}

	function watchConnectivity() {
		const update = (value: boolean) => {
			online.value = value;
			if (value) void probe();
			else serverReachable.value = false;
		};
		window.addEventListener("online", () => update(true));
		window.addEventListener("offline", () => update(false));
	}

	/** Cheap liveness check — `navigator.onLine` lies on captive portals. */
	async function probe(): Promise<boolean> {
		if (!navigator.onLine) {
			serverReachable.value = false;
			return false;
		}
		try {
			const response = await fetch("/api/method/frappe.ping", {
				method: "GET",
				credentials: "same-origin",
				cache: "no-store",
			});
			serverReachable.value = response.ok;
		} catch {
			serverReachable.value = false;
		}
		return serverReachable.value;
	}

	return {
		profile,
		shift,
		company,
		stockSettings,
		posSettings,
		activePriceList,
		pricingCustomer,
		currencyContext,
		user,
		fullName,
		ready,
		booting,
		bootError,
		needsOpeningShift,
		online,
		serverReachable,
		currency,
		companyCurrency,
		priceListCurrency,
		conversionRate,
		plcConversionRate,
		currencyOptions,
		warehouse,
		priceList,
		companyName,
		shiftName,
		offlineEnabled,
		canWorkOffline,
		paymentMethods,
		defaultPaymentMethod,
		boot,
		openShift,
		endShift,
		watchConnectivity,
		probe,
		applyBootstrap,
		applyCustomerPricing,
		applyCurrencyContext,
		refreshCurrencyContext,
	};
});
