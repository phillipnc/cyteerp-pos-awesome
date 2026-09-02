<script setup lang="ts">
/** The invoice fields a cashier needs occasionally, kept out of the main flow. */
import { computed, onMounted, ref, watch } from "vue";
import { api } from "@/lib/api";
import { formatCurrency, toNumber } from "@/lib/format";
import { useCartStore } from "@/stores/cart";
import { useCustomerStore } from "@/stores/customers";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";
import { useCatalogStore } from "@/stores/catalog";
import ModalShell from "@/components/common/ModalShell.vue";

const cart = useCartStore();
const customers = useCustomerStore();
const session = useSessionStore();
const ui = useUiStore();
const catalog = useCatalogStore();

interface DeliveryCharge {
	name: string;
	shipping_rule?: string;
	rate?: number;
	charges?: number;
}

const charges = ref<DeliveryCharge[]>([]);
const loadingCharges = ref(false);
const useDelivery = computed(() => !!session.profile?.posa_use_delivery_charges);
const canSelectCurrency = computed(
	() => !!session.currencyContext?.allow_invoice_currency_selection,
);

onMounted(() => {
	void customers.loadSalesPersons();
	if (cart.customer) void customers.loadAddresses(cart.customer);
	void loadCharges();
});

/**
 * Which delivery charges apply to this customer and address.
 *
 * The rule set depends on where the goods are going, so this reloads whenever the
 * shipping address changes — a charge worked out for one address is simply the wrong
 * number for another.
 */
async function loadCharges() {
	if (!useDelivery.value || !cart.customer) {
		charges.value = [];
		return;
	}
	loadingCharges.value = true;
	try {
		charges.value = ((await api.deliveryCharges({
			company: session.companyName,
			pos_profile: session.profile?.name,
			customer: cart.customer,
			shipping_address_name: cart.shippingAddress ?? undefined,
		})) ?? []) as DeliveryCharge[];

		// The profile can ask for the first applicable rule to be picked up without
		// the cashier having to think about it.
		if (session.profile?.posa_auto_set_delivery_charges && !cart.deliveryCharges && charges.value.length) {
			applyCharge(charges.value[0].name);
		}
	} catch {
		// A missing rule set is not an error worth interrupting a sale for.
		charges.value = [];
	} finally {
		loadingCharges.value = false;
	}
}

// Array of getters, compared element-wise — see the note in SellView.
watch([() => cart.customer, () => cart.shippingAddress], () => void loadCharges());

function chargeRate(row: DeliveryCharge): number {
	return toNumber(row.rate ?? row.charges);
}

function applyCharge(name: string | null) {
	cart.deliveryCharges = name || null;
	const row = charges.value.find((entry) => entry.name === name);
	cart.deliveryChargesRate = row ? chargeRate(row) : 0;
}

async function selectCurrency(event: Event) {
	const currency = (event.target as HTMLSelectElement).value;
	if (!currency || currency === session.currency || !cart.isEmpty) return;
	try {
		await session.refreshCurrencyContext(currency);
		await catalog.load({ force: true });
	} catch (error) {
		ui.fail("Could not change currency", error instanceof Error ? error.message : String(error));
	}
}
</script>

<template>
	<ModalShell title="Invoice details" width="max-w-md" @close="ui.closeModal()">
		<div class="grid gap-3 p-4 sm:grid-cols-2">
			<label v-if="canSelectCurrency" class="block sm:col-span-2">
				<span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-subtle">
					Invoice currency
				</span>
				<select
					:value="session.currency"
					class="h-10 w-full rounded-card border-line bg-surface text-sm focus:border-accent focus:ring-0 disabled:opacity-60"
					:disabled="!cart.isEmpty"
					@change="selectCurrency"
				>
					<option v-for="currency in session.currencyOptions" :key="currency" :value="currency">
						{{ currency }}
					</option>
				</select>
				<span v-if="!cart.isEmpty" class="mt-1 block text-[11px] text-subtle">
					Clear the current cart before changing its invoice currency.
				</span>
			</label>

			<label v-if="session.profile?.posa_allow_change_posting_date" class="block">
				<span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-subtle">
					Posting date
				</span>
				<input
					v-model="cart.postingDate"
					type="date"
					class="h-10 w-full rounded-card border-line bg-surface text-sm focus:border-accent focus:ring-0"
				/>
			</label>

			<label class="block">
				<span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-subtle">Due date</span>
				<input
					v-model="cart.dueDate"
					type="date"
					class="h-10 w-full rounded-card border-line bg-surface text-sm focus:border-accent focus:ring-0"
				/>
			</label>

			<label v-if="session.profile?.posa_allow_customer_purchase_order" class="block sm:col-span-2">
				<span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-subtle">
					Customer PO number
				</span>
				<input
					v-model="cart.poNumber"
					type="text"
					class="h-10 w-full rounded-card border-line bg-surface text-sm focus:border-accent focus:ring-0"
				/>
			</label>

			<label v-if="session.profile?.posa_allow_sales_order" class="block sm:col-span-2">
				<span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-subtle">
					Delivery date
				</span>
				<input
					v-model="cart.deliveryDate"
					type="date"
					class="h-10 w-full rounded-card border-line bg-surface text-sm focus:border-accent focus:ring-0"
				/>
				<span class="mt-1 block text-[11px] text-muted">
					A delivery date turns this into a sales order, so stock is not moved now.
				</span>
			</label>

			<label v-if="customers.salesPersons.length" class="block sm:col-span-2">
				<span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-subtle">
					Sales person
				</span>
				<select
					v-model="cart.salesPerson"
					class="h-10 w-full rounded-card border-line bg-surface text-sm focus:border-accent focus:ring-0"
				>
					<option value="">—</option>
					<option v-for="person in customers.salesPersons" :key="person.name" :value="person.name">
						{{ person.sales_person_name || person.name }}
					</option>
				</select>
			</label>

			<label v-if="customers.addresses.length" class="block sm:col-span-2">
				<span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-subtle">
					Shipping address
				</span>
				<select
					v-model="cart.shippingAddress"
					class="h-10 w-full rounded-card border-line bg-surface text-sm focus:border-accent focus:ring-0"
				>
					<option :value="null">—</option>
					<option
						v-for="address in customers.addresses"
						:key="address.name as string"
						:value="address.name as string"
					>
						{{ address.address_title || address.name }}
					</option>
				</select>
			</label>

			<label v-if="useDelivery && charges.length" class="block sm:col-span-2">
				<span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-subtle">
					Delivery charge
				</span>
				<select
					:value="cart.deliveryCharges"
					class="h-10 w-full rounded-card border-line bg-surface text-sm focus:border-accent focus:ring-0"
					@change="applyCharge(($event.target as HTMLSelectElement).value || null)"
				>
					<option value="">None</option>
					<option v-for="row in charges" :key="row.name" :value="row.name">
						{{ row.shipping_rule || row.name }} · {{ formatCurrency(chargeRate(row)) }}
					</option>
				</select>
				<span v-if="cart.deliveryChargesRate" class="mt-1 block text-[11px] tnum text-muted">
					Adds {{ formatCurrency(cart.deliveryChargesRate) }} to this invoice
				</span>
			</label>

			<label class="block sm:col-span-2">
				<span class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-subtle">Notes</span>
				<textarea
					v-model="cart.notes"
					rows="3"
					class="w-full rounded-card border-line bg-surface text-sm focus:border-accent focus:ring-0"
				/>
			</label>
		</div>

		<template #footer>
			<button
				type="button"
				class="h-11 w-full rounded-card bg-accent font-semibold text-accent-fg transition hover:bg-accent-hover"
				@click="ui.closeModal()"
			>
				Done
			</button>
		</template>
	</ModalShell>
</template>
