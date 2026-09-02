/** Customer list, lookup and the currently selected customer's detail. */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api, OfflineError } from "@/lib/api";
import { cacheCustomers, cacheStamp, readCachedCustomers } from "@/lib/db";
import type { Customer, CustomerInfo } from "@/types";
import { useSessionStore } from "./session";
import { useUiStore } from "./ui";

export const useCustomerStore = defineStore("customers", () => {
	const session = useSessionStore();
	const ui = useUiStore();

	const customers = ref<Customer[]>([]);
	const loading = ref(false);
	const search = ref("");
	const addresses = ref<Record<string, unknown>[]>([]);
	const salesPersons = ref<{ name: string; sales_person_name: string }[]>([]);

	const haystacks = ref<Map<string, string>>(new Map());

	function index(list: Customer[]) {
		const map = new Map<string, string>();
		for (const customer of list) {
			map.set(
				customer.name,
				[customer.name, customer.customer_name, customer.mobile_no, customer.tax_id, customer.email_id]
					.filter(Boolean)
					.join(" ")
					.toLowerCase(),
			);
		}
		haystacks.value = map;
	}

	const filtered = computed(() => {
		const term = search.value.trim().toLowerCase();
		if (!term) return customers.value.slice(0, 200);
		return customers.value.filter((customer) => (haystacks.value.get(customer.name) ?? "").includes(term)).slice(0, 200);
	});

	async function load() {
		if (!session.profile) return;
		loading.value = true;
		try {
			const cached = await readCachedCustomers(session.profile.name);
			const stamp = await cacheStamp("customers", session.profile.name);
			const ttl = Math.max(Number(session.profile.posa_offline_cache_ttl ?? 60), 1) * 60_000;
			if (cached.length && stamp && Date.now() - stamp <= ttl) {
				customers.value = cached;
				index(cached);
			}

			const fresh = (await api.customerNames(JSON.stringify(session.profile))) as Customer[];
			customers.value = fresh ?? [];
			index(customers.value);
			if (session.offlineEnabled) void cacheCustomers(session.profile.name, customers.value);
		} catch (error) {
			if (!(error instanceof OfflineError || error instanceof TypeError)) {
				ui.fail("Could not load customers", error instanceof Error ? error.message : String(error));
			}
		} finally {
			loading.value = false;
		}
	}

	async function info(customer: string): Promise<CustomerInfo | null> {
		try {
			return (await api.customerInfo(customer)) as CustomerInfo;
		} catch {
			// Offline: fall back to what the cached list already knows.
			const cached = customers.value.find((entry) => entry.name === customer);
			return cached
				? {
						name: cached.name,
						customer_name: cached.customer_name,
						mobile_no: cached.mobile_no ?? undefined,
						email_id: cached.email_id ?? undefined,
						tax_id: cached.tax_id ?? undefined,
					}
				: null;
		}
	}

	async function save(payload: Record<string, unknown>) {
		const result = (await api.saveCustomer({
			...payload,
			pos_profile: session.profile,
			company: session.companyName,
		})) as CustomerInfo;
		await load();
		return result;
	}

	async function loadAddresses(customer: string) {
		try {
			addresses.value = (await api.customerAddresses(customer)) as Record<string, unknown>[];
		} catch {
			addresses.value = [];
		}
	}

	async function loadSalesPersons() {
		try {
			salesPersons.value = (await api.salesPersons()) as typeof salesPersons.value;
		} catch {
			salesPersons.value = [];
		}
	}

	function find(name: string) {
		return customers.value.find((customer) => customer.name === name);
	}

	return {
		customers,
		loading,
		search,
		addresses,
		salesPersons,
		filtered,
		load,
		info,
		save,
		loadAddresses,
		loadSalesPersons,
		find,
	};
});
