<script setup lang="ts">
/** Standalone customer collections and reconciliation workspace. */
import { computed, onMounted, ref, watch } from "vue";
import { ArrowLeft, CheckCircle2, Loader2, RefreshCw } from "lucide-vue-next";
import { api } from "@/lib/api";
import { formatCurrency, formatDate, toNumber } from "@/lib/format";
import { useCartStore } from "@/stores/cart";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";
import CustomerPicker from "@/components/customer/CustomerPicker.vue";

interface InvoiceRow {
	name: string;
	outstanding_amount: number;
	grand_total: number;
	posting_date: string;
	due_date?: string;
	currency: string;
	selected?: boolean;
}

interface AdvanceRow {
	name: string;
	unallocated_amount: number;
	posting_date: string;
	mode_of_payment: string;
	currency: string;
	selected?: boolean;
}

interface NewPayment {
	mode_of_payment: string;
	/** Physical amount entered in the payment account currency. */
	amount: number;
	currency: string;
	exchange_rate: number;
}

const cart = useCartStore();
const session = useSessionStore();
const ui = useUiStore();

const invoices = ref<InvoiceRow[]>([]);
const advances = ref<AdvanceRow[]>([]);
const newPayments = ref<NewPayment[]>([]);
const loading = ref(false);
const processing = ref(false);
const result = ref<Record<string, unknown> | null>(null);

const selectedInvoices = computed(() => invoices.value.filter((row) => row.selected));
const selectedAdvances = computed(() => advances.value.filter((row) => row.selected));
const totalInvoices = computed(() =>
	selectedInvoices.value.reduce((sum, row) => sum + toNumber(row.outstanding_amount), 0),
);
const totalAdvances = computed(() =>
	selectedAdvances.value.reduce((sum, row) => sum + toNumber(row.unallocated_amount), 0),
);
const totalNew = computed(() =>
	newPayments.value.reduce(
		(sum, row) => sum + toNumber(row.amount) * toNumber(row.exchange_rate),
		0,
	),
);
const canProcess = computed(
	() =>
		!!cart.customer &&
		(totalNew.value > 0 || totalAdvances.value > 0) &&
		!processing.value,
);

function buildPaymentRows() {
	newPayments.value = session.paymentMethods.map((row) => ({
		mode_of_payment: row.mode_of_payment,
		amount: 0,
		currency: row.currency || session.currency,
		exchange_rate: toNumber(row.exchange_rate) || 1,
	}));
}

async function load() {
	invoices.value = [];
	advances.value = [];
	result.value = null;
	if (!cart.customer) return;
	loading.value = true;
	try {
		const [invoiceResult, advanceResult] = await Promise.all([
			api.outstandingInvoices({
				company: session.companyName,
				currency: session.currency,
				customer: cart.customer,
				pos_profile_name: session.profile?.name,
			}),
			api.unallocatedPayments({
				company: session.companyName,
				currency: session.currency,
				customer: cart.customer,
			}),
		]);
		invoices.value = (invoiceResult ?? []) as InvoiceRow[];
		advances.value = (advanceResult ?? []) as AdvanceRow[];
	} catch (error) {
		ui.fail("Could not load customer balances", error instanceof Error ? error.message : String(error));
	} finally {
		loading.value = false;
	}
}

async function process() {
	if (!canProcess.value) return;
	processing.value = true;
	try {
		result.value = (await api.processPosPayment({
			company: session.companyName,
			currency: session.currency,
			customer: cart.customer,
			pos_profile: session.profile,
			pos_profile_name: session.profile?.name,
			pos_opening_shift_name: session.shiftName,
			payment_methods: newPayments.value
				.filter((row) => row.amount > 0)
				.map((row) => ({
					mode_of_payment: row.mode_of_payment,
					amount: toNumber(row.amount) * toNumber(row.exchange_rate),
					tendered_amount: row.amount,
					currency: row.currency,
					exchange_rate: row.exchange_rate,
				})),
			total_payment_methods: totalNew.value,
			selected_invoices: selectedInvoices.value,
			total_selected_invoices: totalInvoices.value,
			selected_payments: selectedAdvances.value,
			total_selected_payments: totalAdvances.value,
			selected_mpesa_payments: [],
			total_selected_mpesa_payments: 0,
		})) as Record<string, unknown>;
		const errors = (result.value.errors as string[] | undefined) ?? [];
		if (errors.length) ui.warn("Payments completed with warnings", errors[0]);
		else ui.success("Customer payment completed");
		buildPaymentRows();
		await load();
	} catch (error) {
		ui.fail("Could not process payment", error instanceof Error ? error.message : String(error));
	} finally {
		processing.value = false;
	}
}

watch(
	() => cart.customer,
	() => void load(),
);

onMounted(() => {
	buildPaymentRows();
	void load();
});
</script>

<template>
	<section class="h-full overflow-y-auto bg-bg p-3 sm:p-5">
		<div class="mx-auto max-w-6xl space-y-4">
			<header class="flex flex-wrap items-center gap-3">
				<RouterLink
					to="/sell"
					class="grid size-10 place-items-center rounded-card border border-line bg-surface text-muted"
					aria-label="Back to selling"
				>
					<ArrowLeft class="size-4.5" />
				</RouterLink>
				<div>
					<h1 class="text-lg font-semibold">Customer payments</h1>
					<p class="text-xs text-muted">Capture advances and reconcile outstanding invoices.</p>
				</div>
				<div class="ml-auto w-full sm:w-80"><CustomerPicker /></div>
				<button
					type="button"
					class="grid size-10 place-items-center rounded-card border border-line bg-surface text-muted"
					:disabled="loading || !cart.customer"
					@click="load"
				>
					<RefreshCw class="size-4" :class="loading && 'animate-spin'" />
				</button>
			</header>

			<div v-if="!cart.customer" class="panel p-10 text-center text-sm text-muted">
				Select a customer to view outstanding invoices and advances.
			</div>

			<template v-else>
				<div class="grid gap-4 lg:grid-cols-2">
					<section class="panel overflow-hidden">
						<header class="border-b border-line px-4 py-3">
							<h2 class="text-sm font-semibold">Outstanding invoices</h2>
						</header>
						<div v-if="loading" class="grid place-items-center p-10"><Loader2 class="size-5 animate-spin" /></div>
						<div v-else-if="!invoices.length" class="p-8 text-center text-sm text-muted">No outstanding invoices.</div>
						<label
							v-for="row in invoices"
							v-else
							:key="row.name"
							class="flex cursor-pointer items-center gap-3 border-b border-line px-4 py-3 last:border-0"
						>
							<input v-model="row.selected" type="checkbox" class="rounded border-line text-accent" />
							<span class="min-w-0 flex-1">
								<span class="block font-mono text-xs">{{ row.name }}</span>
								<span class="text-[11px] text-subtle">
									{{ formatDate(row.posting_date) }}
									<template v-if="row.due_date"> · due {{ formatDate(row.due_date) }}</template>
								</span>
							</span>
							<span class="font-semibold tnum">{{ formatCurrency(row.outstanding_amount, row.currency) }}</span>
						</label>
					</section>

					<section class="panel overflow-hidden">
						<header class="border-b border-line px-4 py-3">
							<h2 class="text-sm font-semibold">Unallocated payments</h2>
						</header>
						<div v-if="loading" class="grid place-items-center p-10"><Loader2 class="size-5 animate-spin" /></div>
						<div v-else-if="!advances.length" class="p-8 text-center text-sm text-muted">No unallocated payments.</div>
						<label
							v-for="row in advances"
							v-else
							:key="row.name"
							class="flex cursor-pointer items-center gap-3 border-b border-line px-4 py-3 last:border-0"
						>
							<input v-model="row.selected" type="checkbox" class="rounded border-line text-accent" />
							<span class="min-w-0 flex-1">
								<span class="block font-mono text-xs">{{ row.name }}</span>
								<span class="text-[11px] text-subtle">{{ row.mode_of_payment }} · {{ formatDate(row.posting_date) }}</span>
							</span>
							<span class="font-semibold tnum">{{ formatCurrency(row.unallocated_amount, row.currency) }}</span>
						</label>
					</section>
				</div>

				<section class="panel p-4">
					<h2 class="mb-3 text-sm font-semibold">New payment</h2>
					<div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
						<label v-for="row in newPayments" :key="row.mode_of_payment" class="block">
							<span class="mb-1 block text-xs text-muted">{{ row.mode_of_payment }} · {{ row.currency }}</span>
							<input
								v-model.number="row.amount"
								type="number"
								min="0"
								step="0.01"
								class="h-10 w-full rounded-card border-line bg-surface-2 text-right font-semibold tnum"
							/>
							<span v-if="row.currency !== session.currency" class="mt-1 block text-[10px] text-subtle">
								= {{ formatCurrency(row.amount * row.exchange_rate, session.currency) }}
							</span>
						</label>
					</div>

					<div class="mt-4 flex flex-wrap items-end justify-between gap-3 border-t border-line pt-4">
						<div class="text-xs text-muted">
							<p>Selected invoices: <strong>{{ formatCurrency(totalInvoices) }}</strong></p>
							<p>Available to allocate: <strong>{{ formatCurrency(totalAdvances + totalNew) }}</strong></p>
						</div>
						<button
							type="button"
							class="flex h-11 min-w-48 items-center justify-center gap-2 rounded-card bg-success px-5 font-semibold text-white disabled:bg-surface-3 disabled:text-subtle"
							:disabled="!canProcess"
							@click="process"
						>
							<Loader2 v-if="processing" class="size-4 animate-spin" />
							<CheckCircle2 v-else class="size-4" />
							Process payment
						</button>
					</div>
				</section>
			</template>
		</div>
	</section>
</template>
