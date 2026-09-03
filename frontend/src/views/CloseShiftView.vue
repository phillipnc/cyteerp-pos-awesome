<script setup lang="ts">
/** Shift summary and close-out. Numbers first, then the irreversible button. */
import { computed, onMounted, ref } from "vue";
import { ArrowLeft, BarChart3, Loader2, LockKeyhole, Receipt } from "lucide-vue-next";
import { useRouter } from "vue-router";
import { api } from "@/lib/api";
import { formatCurrency, formatDateTime, formatFloat, toNumber } from "@/lib/format";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";
import type { ShiftAnalytics } from "@/types";

const session = useSessionStore();
const ui = useUiStore();
const router = useRouter();

const stats = ref<ShiftAnalytics | null>(null);
const loading = ref(true);
const closing = ref(false);
/** Counted cash per mode, entered by the cashier at close. */
const counted = ref<Record<string, number>>({});

const peakHour = computed(() => {
	const hours = stats.value?.hourly ?? [];
	if (!hours.length) return null;
	return hours.reduce((best, row) => (row.amount > best.amount ? row : best), hours[0]);
});

onMounted(async () => {
	if (!session.shiftName) {
		loading.value = false;
		return;
	}
	try {
		stats.value = (await api.shiftAnalytics(session.shiftName)) as ShiftAnalytics;
		for (const row of stats.value?.payment_mix ?? []) counted.value[row.key] = row.expected_amount;
	} catch (error) {
		ui.fail("Could not load the shift summary", error instanceof Error ? error.message : String(error));
	} finally {
		loading.value = false;
	}
});

function variance(key: string, expected: number) {
	return toNumber(counted.value[key]) - expected;
}

async function close() {
	if (!session.shiftName) return;
	closing.value = true;
	try {
		const draft = (await api.closingShiftFromOpening(session.shiftName)) as Record<string, unknown>;
		const rows = (draft.payment_reconciliation as Record<string, unknown>[] | undefined) ?? [];
		for (const row of rows) {
			const mode = row.mode_of_payment as string;
			const currency = row.currency as string;
			const key = `${mode}::${currency}`;
			if (counted.value[key] !== undefined) row.closing_amount = toNumber(counted.value[key]);
		}
		await api.submitClosingShift(draft);
		ui.success("Shift closed");
		session.endShift();
		void router.replace({ name: "shift" });
	} catch (error) {
		ui.fail("Could not close the shift", error instanceof Error ? error.message : String(error));
	} finally {
		closing.value = false;
	}
}
</script>

<template>
	<div class="h-full overflow-y-auto p-3">
		<div class="mx-auto w-full max-w-3xl space-y-3">
			<div class="flex items-center gap-2">
				<button
					type="button"
					class="grid size-9 place-items-center rounded-card text-muted transition hover:bg-surface-2 hover:text-fg"
					aria-label="Back to selling"
					@click="router.back()"
				>
					<ArrowLeft class="size-4.5" />
				</button>
				<h1 class="text-base font-semibold">Close shift</h1>
				<span v-if="stats" class="ml-auto text-xs text-subtle">
					{{ stats.company_currency }} company totals · Opened {{ formatDateTime(stats.opened_at) }}
				</span>
			</div>

			<div v-if="loading" class="grid gap-3 sm:grid-cols-4">
				<div v-for="n in 4" :key="n" class="skeleton h-24 rounded-panel" />
			</div>

			<p v-else-if="!session.shiftName" class="panel p-6 text-center text-sm text-muted">
				No shift is open on this terminal.
			</p>

			<template v-else-if="stats">
				<!-- KPIs -->
				<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
					<div class="panel p-4">
						<p class="text-[11px] font-semibold uppercase tracking-wide text-subtle">Sales</p>
						<p class="mt-1 text-2xl font-bold tnum">
							{{ formatCurrency(stats.grand_total, stats.company_currency) }}
						</p>
						<p class="text-xs text-muted">{{ stats.invoice_count }} invoices</p>
					</div>
					<div class="panel p-4">
						<p class="text-[11px] font-semibold uppercase tracking-wide text-subtle">Returns</p>
						<p class="mt-1 text-2xl font-bold tnum text-danger">
							{{ formatCurrency(stats.total_returned, stats.company_currency) }}
						</p>
						<p class="text-xs text-muted">{{ stats.return_count }} returns</p>
					</div>
					<div class="panel p-4">
						<p class="text-[11px] font-semibold uppercase tracking-wide text-subtle">Average basket</p>
						<p class="mt-1 text-2xl font-bold tnum">
							{{ formatCurrency(stats.average_basket, stats.company_currency) }}
						</p>
						<p class="text-xs text-muted">{{ formatFloat(stats.total_qty) }} stock units sold</p>
					</div>
					<div class="panel p-4">
						<p class="text-[11px] font-semibold uppercase tracking-wide text-subtle">Discounts</p>
						<p class="mt-1 text-2xl font-bold tnum text-warning">
							{{ formatCurrency(stats.total_discount, stats.company_currency) }}
						</p>
						<p v-if="peakHour" class="text-xs text-muted">Busiest {{ peakHour.hour }}:00</p>
					</div>
				</div>

				<!-- Invoice-currency breakdown -->
				<div class="panel overflow-hidden">
					<header class="border-b border-line px-4 py-3">
						<h2 class="text-sm font-semibold">Sales by invoice currency</h2>
						<p class="mt-0.5 text-xs text-muted">
							Currencies remain separate; the KPI cards above use {{ stats.company_currency }} base values.
						</p>
					</header>
					<div class="divide-y divide-line">
						<div
							v-for="row in stats.currency_totals"
							:key="row.currency"
							class="grid grid-cols-[1fr_auto_auto] items-center gap-4 px-4 py-2.5 text-sm"
						>
							<div>
								<p class="font-semibold">{{ row.currency }}</p>
								<p class="text-xs text-muted">
									{{ row.invoice_count }} sales · {{ row.return_count }} returns
								</p>
							</div>
							<div class="text-right">
								<p class="text-xs text-subtle">Sales</p>
								<p class="font-semibold tnum">{{ formatCurrency(row.sales, row.currency) }}</p>
							</div>
							<div class="text-right">
								<p class="text-xs text-subtle">Net after returns</p>
								<p class="font-semibold tnum">{{ formatCurrency(row.net_sales, row.currency) }}</p>
							</div>
						</div>
					</div>
				</div>

				<!-- Reconciliation -->
				<div class="panel overflow-hidden">
					<header class="flex items-center gap-2 border-b border-line px-4 py-3">
						<Receipt class="size-4 text-subtle" />
						<h2 class="text-sm font-semibold">Count the drawer</h2>
					</header>
					<div class="divide-y divide-line">
						<div
							v-for="row in stats.payment_mix"
							:key="row.key"
							class="flex items-center gap-3 px-4 py-2.5"
						>
							<span class="min-w-0 flex-1 text-sm">
								<span class="block truncate">{{ row.mode_of_payment }} · {{ row.currency }}</span>
								<span class="block text-[11px] text-subtle">
									Open {{ formatCurrency(row.opening_amount, row.currency) }} · movement
									{{ formatCurrency(row.transaction_amount, row.currency) }}
								</span>
							</span>
							<span class="w-28 text-right text-sm tnum text-muted">
								{{ formatCurrency(row.expected_amount, row.currency) }}
							</span>
							<input
								v-model.number="counted[row.key]"
								type="text"
								inputmode="decimal"
								class="h-9 w-28 rounded-card border-line bg-surface-2 text-right text-sm font-semibold tnum focus:border-accent focus:ring-0"
								:aria-label="`Counted ${row.mode_of_payment} in ${row.currency}`"
							/>
							<span
								class="w-24 text-right text-xs font-semibold tnum"
								:class="
									variance(row.key, row.expected_amount) === 0
										? 'text-subtle'
										: variance(row.key, row.expected_amount) > 0
											? 'text-success'
											: 'text-danger'
								"
							>
								{{ variance(row.key, row.expected_amount) > 0 ? "+" : ""
								}}{{ formatCurrency(variance(row.key, row.expected_amount), row.currency) }}
							</span>
						</div>
					</div>
				</div>

				<!-- Top items -->
				<div v-if="stats.top_items?.length" class="panel overflow-hidden">
					<header class="flex items-center gap-2 border-b border-line px-4 py-3">
						<BarChart3 class="size-4 text-subtle" />
						<h2 class="text-sm font-semibold">Top sellers</h2>
					</header>
					<ul class="divide-y divide-line">
						<li
							v-for="item in stats.top_items.slice(0, 8)"
							:key="item.item_code"
							class="flex items-center gap-3 px-4 py-2 text-sm"
						>
							<span class="min-w-0 flex-1 truncate">{{ item.item_name }}</span>
							<span class="shrink-0 text-xs tnum text-subtle">
								{{ formatFloat(item.qty) }} {{ item.stock_uom || "units" }}
							</span>
							<span class="w-24 shrink-0 text-right tnum font-semibold">
								{{ formatCurrency(item.amount, stats.company_currency) }}
							</span>
						</li>
					</ul>
				</div>

				<button
					type="button"
					class="flex h-12 w-full items-center justify-center gap-2 rounded-card bg-danger font-semibold text-white shadow-md transition hover:opacity-90 disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-subtle disabled:shadow-none"
					:disabled="closing"
					@click="close"
				>
					<Loader2 v-if="closing" class="size-5 animate-spin" />
					<LockKeyhole v-else class="size-5" />
					{{ closing ? "Closing…" : "Close shift" }}
				</button>
			</template>
		</div>
	</div>
</template>
