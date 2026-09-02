<script setup lang="ts">
/** Customer selector. Filters locally against the cached list so it stays usable
 *  offline, and shows the picked customer's key detail inline. */
import { computed, onMounted, ref, watch } from "vue";
import { ChevronDown, Search, User, X } from "lucide-vue-next";
import { useCustomerStore } from "@/stores/customers";
import { useCartStore } from "@/stores/cart";
import { useSessionStore } from "@/stores/session";
import { useCatalogStore } from "@/stores/catalog";

const customers = useCustomerStore();
const cart = useCartStore();
const session = useSessionStore();
const catalog = useCatalogStore();

const open = ref(false);
const searchEl = ref<HTMLInputElement | null>(null);

onMounted(async () => {
	void customers.load();
	if (!cart.customer && session.profile?.customer) {
		cart.customer = session.profile.customer;
		cart.customerInfo = await customers.info(cart.customer);
		if (session.applyCustomerPricing(cart.customerInfo)) {
			await session.refreshCurrencyContext();
			await catalog.load({ force: true });
		}
	}
});

const current = computed(() => customers.find(cart.customer));
const label = computed(() => current.value?.customer_name || cart.customer || "Select a customer");

watch(open, async (isOpen) => {
	if (!isOpen) return;
	customers.search = "";
	// Wait a tick so the input exists before focusing it.
	await Promise.resolve();
	searchEl.value?.focus();
});

async function choose(name: string) {
	cart.customer = name;
	open.value = false;
	cart.customerInfo = await customers.info(name);
	if (session.applyCustomerPricing(cart.customerInfo)) {
		await session.refreshCurrencyContext();
		await catalog.load({ force: true });
	}
}
</script>

<template>
	<div class="relative">
		<button
			type="button"
			class="flex h-11 w-full items-center gap-2 rounded-card border border-line bg-surface px-3 text-left shadow-xs transition hover:border-line-strong"
			:class="!cart.customer && 'border-warning'"
			@click="open = !open"
		>
			<span class="grid size-7 shrink-0 place-items-center rounded-full bg-accent-soft text-accent">
				<User class="size-3.5" />
			</span>
			<span class="min-w-0 flex-1">
				<span class="block truncate text-sm font-medium">{{ label }}</span>
				<span v-if="current?.mobile_no" class="block truncate text-[11px] text-subtle">
					{{ current.mobile_no }}
				</span>
			</span>
			<ChevronDown class="size-4 shrink-0 text-subtle transition" :class="open && 'rotate-180'" />
		</button>

		<Transition
			enter-active-class="transition duration-150"
			enter-from-class="opacity-0 -translate-y-1"
			leave-active-class="transition duration-100"
			leave-to-class="opacity-0"
		>
			<div
				v-if="open"
				class="panel absolute left-0 right-0 top-full z-30 mt-1.5 overflow-hidden shadow-lg"
			>
				<div class="relative border-b border-line">
					<Search class="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-subtle" />
					<input
						ref="searchEl"
						v-model="customers.search"
						type="search"
						placeholder="Name, mobile or tax ID…"
						class="h-10 w-full border-0 bg-transparent pl-9 pr-9 text-sm focus:ring-0"
					/>
					<button
						type="button"
						class="absolute right-2 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-full text-subtle hover:bg-surface-2"
						aria-label="Close"
						@click="open = false"
					>
						<X class="size-3.5" />
					</button>
				</div>

				<ul class="max-h-72 overflow-y-auto py-1">
					<li v-if="!customers.filtered.length" class="px-3 py-6 text-center text-xs text-muted">
						No customer matches.
					</li>
					<li v-for="entry in customers.filtered" :key="entry.name">
						<button
							type="button"
							class="flex w-full items-center gap-2 px-3 py-2 text-left transition hover:bg-surface-2"
							:class="entry.name === cart.customer && 'bg-accent-soft/50'"
							@click="choose(entry.name)"
						>
							<span class="min-w-0 flex-1">
								<span class="block truncate text-sm">{{ entry.customer_name }}</span>
								<span v-if="entry.mobile_no || entry.tax_id" class="block truncate text-[11px] text-subtle">
									{{ [entry.mobile_no, entry.tax_id].filter(Boolean).join(" · ") }}
								</span>
							</span>
						</button>
					</li>
				</ul>
			</div>
		</Transition>
	</div>
</template>
