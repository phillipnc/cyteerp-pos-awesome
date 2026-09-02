<script setup lang="ts">
/** Tender screen. Big targets, tabular numbers, and one obvious primary action. */
import { computed, watch } from "vue";
import {
	ArrowLeft,
	Banknote,
	Check,
	CheckCircle2,
	CloudOff,
	Coins,
	Loader2,
	Printer,
	Plus,
	Smartphone,
	WalletCards,
} from "lucide-vue-next";
import { formatCurrency, formatFloat, toNumber } from "@/lib/format";
import { usePaymentsStore } from "@/stores/payments";
import { useCartStore } from "@/stores/cart";
import { useUiStore } from "@/stores/ui";
import { useOffersStore } from "@/stores/offers";
import { useSessionStore } from "@/stores/session";

const payments = usePaymentsStore();
const cart = useCartStore();
const ui = useUiStore();
const offers = useOffersStore();
const session = useSessionStore();

/** Round-number shortcuts a cashier actually reaches for. */
const QUICK = [5, 10, 20, 50, 100, 200, 500];

const done = computed(() => !!payments.lastInvoice);
/** A sale parked on the terminal: real to the customer, not yet on the server. */
const queued = computed(() => !!payments.lastInvoice?.__queued);
const isReturn = computed(() => cart.isReturn);

/** Credit only shows when the profile allows it and the customer actually has some. */
const canUseCredit = computed(
	() => !isReturn.value && !!session.profile?.use_customer_credit && payments.credit.length > 0,
);
const mpesaEnabled = computed(() => !!session.profile?.posa_allow_mpesa_reconcile_payments);
/** Loyalty redemption shows whenever the customer carries a balance to spend. */
const canRedeem = computed(
	() =>
		!isReturn.value &&
		toNumber(cart.customerInfo?.loyalty_points) > 0 &&
		toNumber(cart.customerInfo?.conversion_factor) > 0,
);

// Totals can settle after entry (taxes arriving with the draft save); while the
// cashier has not touched the amounts, keep tender pinned to what is owed.
watch(
	() => payments.payable,
	() => {
		if (!done.value && !payments.touched) payments.tenderExact();
	},
);

// Credit belongs to a customer, so a stale list would offer somebody else's money.
watch(
	() => cart.customer,
	() => void payments.loadCredit(),
	{ immediate: true },
);

function back() {
	ui.setWorkspace("catalog");
}

async function complete() {
	const result = await payments.submit();
	if (!result) return;
	// Keep the receipt on screen; the cart is cleared when the cashier moves on.
	offers.reset();
}

function nextSale() {
	cart.reset();
	payments.reset();
	offers.reset();
	ui.setWorkspace("catalog");
}

function commitRedemption(event: Event) {
	const raw = (event.target as HTMLInputElement).value.trim();
	cart.setLoyaltyRedemption(toNumber(raw));
	payments.tenderExact();
}

/** Open the in-page print dialog; the browser's print sheet stays over this view. */
function print() {
	const name = payments.lastInvoice?.name as string | undefined;
	if (!name || queued.value) return;
	ui.openModal("print", { invoiceName: name });
}

function openMpesa() {
	ui.openModal("mpesa");
}
</script>

<template>
	<section class="panel flex h-full min-h-0 flex-col overflow-hidden">
		<!-- Success state -->
		<div v-if="done" class="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
			<span
				class="grid size-16 place-items-center rounded-full animate-pop-in"
				:class="queued ? 'bg-warning-soft text-warning' : 'bg-success-soft text-success'"
			>
				<CloudOff v-if="queued" class="size-8" />
				<CheckCircle2 v-else class="size-8" />
			</span>
			<div>
				<h2 class="text-lg font-semibold">
					{{ queued ? "Saved on this terminal" : isReturn ? "Refund complete" : "Sale complete" }}
				</h2>
				<p v-if="queued" class="mx-auto mt-1 max-w-[19rem] text-xs text-muted">
					There is no connection, so this sale is waiting on the till. It sends itself as
					soon as the network is back — take the money and hand over the goods.
				</p>
				<p v-else class="mt-0.5 font-mono text-xs text-subtle">{{ payments.lastInvoice?.name }}</p>
			</div>

			<div v-if="payments.change > 0" class="panel bg-surface-2 px-6 py-4">
				<p class="text-xs font-medium uppercase tracking-wide text-subtle">
					{{ isReturn ? "Over-refunded" : "Change due" }}
				</p>
				<p class="mt-0.5 text-3xl font-bold tnum text-warning">{{ formatCurrency(payments.change) }}</p>
			</div>

			<div class="mt-2 flex w-full max-w-xs flex-col gap-2">
				<button
					type="button"
					class="flex h-11 items-center justify-center gap-2 rounded-card bg-accent font-semibold text-accent-fg transition hover:bg-accent-hover"
					@click="nextSale"
				>
					<Plus class="size-4" />
					New sale
				</button>
				<button
					type="button"
					class="flex h-11 items-center justify-center gap-2 rounded-card border border-line font-medium text-muted transition hover:bg-surface-2 hover:text-fg disabled:cursor-not-allowed disabled:opacity-45"
					:disabled="queued"
					:title="queued ? 'Available once the sale has been sent' : undefined"
					@click="print"
				>
					<Printer class="size-4" />
					Print receipt
				</button>
			</div>
		</div>

		<!-- Tender state -->
		<template v-else>
			<header class="flex shrink-0 items-center gap-2 border-b border-line p-3">
				<button
					type="button"
					class="grid size-9 place-items-center rounded-card text-muted transition hover:bg-surface-2 hover:text-fg"
					aria-label="Back to catalog"
					@click="back"
				>
					<ArrowLeft class="size-4.5" />
				</button>
				<h2 class="text-sm font-semibold">{{ isReturn ? "Refund" : "Payment" }}</h2>
				<span class="ml-auto text-right">
					<span class="block text-[11px] uppercase tracking-wide text-subtle">
						{{ isReturn ? "Refund due" : "Due" }}
					</span>
					<span
						class="block text-lg font-bold tnum leading-tight"
						:class="isReturn && 'text-danger'"
						>{{ formatCurrency(Math.abs(payments.payable)) }}</span
					>
				</span>
			</header>

			<div class="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
				<!-- Modes -->
				<div class="space-y-2">
					<div
						v-for="row in payments.rows"
						:key="row.mode_of_payment"
						class="flex items-center gap-2 rounded-card border border-line bg-surface p-2 shadow-xs transition focus-within:border-accent"
					>
						<span class="grid size-9 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
							<Banknote class="size-4" />
						</span>
						<label class="min-w-0 flex-1 truncate text-sm font-medium" :for="`pay-${row.mode_of_payment}`">
							{{ row.mode_of_payment }}
							<span class="block text-[11px] font-normal text-subtle">
								{{ row.currency }}
								<template v-if="row.currency !== session.currency">
									· 1 {{ row.currency }} = {{ row.exchange_rate.toFixed(6) }} {{ session.currency }}
								</template>
							</span>
						</label>
						<input
							:id="`pay-${row.mode_of_payment}`"
							:value="row.tendered_amount || ''"
							type="text"
							inputmode="decimal"
							placeholder="0.00"
							class="h-10 w-32 rounded-card border-line bg-surface-2 text-right text-base font-semibold tnum focus:border-accent focus:ring-0"
							@focus="($event.target as HTMLInputElement).select()"
							@input="payments.setAmount(row.mode_of_payment, toNumber(($event.target as HTMLInputElement).value))"
						/>
					</div>
					<p
						v-for="row in payments.rows.filter((entry) => entry.tendered_amount && entry.currency !== session.currency)"
						:key="`converted-${row.mode_of_payment}`"
						class="-mt-1 text-right text-[11px] text-subtle"
					>
						{{ row.mode_of_payment }}: {{ formatCurrency(Math.abs(row.amount), session.currency) }}
					</p>
				</div>

				<!-- Loyalty redemption — points settle part of the total before cash -->
				<div
					v-if="canRedeem"
					class="flex items-center gap-2 rounded-card border border-dashed border-violet/40 bg-violet-soft/40 p-2"
				>
					<span class="grid size-9 shrink-0 place-items-center rounded-lg bg-violet-soft text-violet">
						<Coins class="size-4" />
					</span>
					<label class="min-w-0 flex-1 text-sm font-medium" for="loyalty-redeem">
						Redeem loyalty
						<span class="block text-[11px] font-normal text-subtle">
							{{ formatFloat(cart.customerInfo?.loyalty_points ?? 0, 0) }} pts available ·
							{{ formatCurrency(cart.maxLoyaltyAmount) }}
						</span>
					</label>
					<input
						id="loyalty-redeem"
						:value="cart.loyaltyAmount || ''"
						type="text"
						inputmode="decimal"
						placeholder="0.00"
						class="h-10 w-28 rounded-card border-line bg-surface text-right text-sm font-semibold tnum focus:border-accent focus:ring-0"
						@focus="($event.target as HTMLInputElement).select()"
						@change="commitRedemption($event)"
					/>
				</div>

				<!-- Customer credit — unapplied credit notes and advances on the account -->
				<div v-if="canUseCredit" class="space-y-2 rounded-card border border-info/40 bg-info-soft/40 p-2">
					<div class="flex items-center gap-2">
						<span class="grid size-9 shrink-0 place-items-center rounded-lg bg-info-soft text-info">
							<WalletCards class="size-4" />
						</span>
						<div class="min-w-0 flex-1">
							<p class="text-sm font-medium">Customer credit</p>
							<p class="text-[11px] text-subtle">
								{{ formatCurrency(payments.creditAvailable) }} available ·
								{{ formatCurrency(payments.creditApplied) }} applied
							</p>
						</div>
						<button
							type="button"
							class="h-8 rounded-card border border-info px-2.5 text-xs font-semibold text-info transition hover:opacity-85"
							@click="payments.applyMaxCredit()"
						>
							Use max
						</button>
						<button
							v-if="payments.creditApplied > 0"
							type="button"
							class="h-8 rounded-card px-2 text-xs font-medium text-subtle transition hover:text-danger"
							@click="payments.clearCredit()"
						>
							Clear
						</button>
					</div>

					<div
						v-for="row in payments.credit"
						:key="row.credit_origin"
						class="flex items-center gap-2 ps-11"
					>
						<label class="min-w-0 flex-1 truncate text-xs" :for="`credit-${row.credit_origin}`">
							<span class="font-medium">{{ row.type }}</span>
							<span class="ms-1 font-mono text-subtle">{{ row.credit_origin }}</span>
							<span class="ms-1 tnum text-subtle">· {{ formatCurrency(row.total_credit) }}</span>
						</label>
						<input
							:id="`credit-${row.credit_origin}`"
							:value="row.credit_to_redeem || ''"
							type="text"
							inputmode="decimal"
							placeholder="0.00"
							class="h-9 w-24 rounded-card border-line bg-surface text-right text-sm font-semibold tnum focus:border-info focus:ring-0"
							@focus="($event.target as HTMLInputElement).select()"
							@change="payments.setCredit(row.credit_origin, toNumber(($event.target as HTMLInputElement).value))"
						/>
					</div>
				</div>

				<!-- M-Pesa: reconcile a transaction the customer has already sent -->
				<button
					v-if="mpesaEnabled"
					type="button"
					class="flex w-full items-center gap-2 rounded-card border border-dashed border-success/50 bg-success-soft/30 p-2 text-left transition hover:border-success"
					@click="openMpesa"
				>
					<span class="grid size-9 shrink-0 place-items-center rounded-lg bg-success-soft text-success">
						<Smartphone class="size-4" />
					</span>
					<span class="min-w-0 flex-1">
						<span class="block text-sm font-medium">M-Pesa</span>
						<span class="block text-[11px] text-subtle">Match a transaction the customer has paid</span>
					</span>
				</button>

				<!-- Quick cash -->
				<div>
					<p class="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-subtle">Quick add</p>
					<div class="flex flex-wrap gap-1.5">
						<button
							v-for="amount in QUICK"
							:key="amount"
							type="button"
							class="h-9 min-w-14 rounded-card border border-line bg-surface px-3 text-sm font-semibold tnum shadow-xs transition hover:border-accent hover:text-accent"
							@click="payments.addAmount(payments.rows.find((r) => r.default)?.mode_of_payment ?? payments.rows[0]?.mode_of_payment ?? '', amount)"
						>
							+{{ amount }}
						</button>
						<button
							type="button"
							class="h-9 rounded-card border border-accent bg-accent-soft px-3 text-sm font-semibold text-accent transition hover:opacity-85"
							@click="payments.tenderExact()"
						>
							Exact
						</button>
						<button
							type="button"
							class="h-9 rounded-card border border-line px-3 text-sm font-medium text-muted transition hover:bg-surface-2"
							@click="payments.clear()"
						>
							Clear
						</button>
					</div>
				</div>
			</div>

			<!-- Balance + complete -->
			<footer class="shrink-0 space-y-2 border-t border-line p-3">
				<div
					v-if="payments.isCreditSale || payments.isPartialPayment || payments.isCustomerCreditReturn"
					class="rounded-card border border-warning/40 bg-warning-soft px-3 py-2 text-xs text-warning"
				>
					<span v-if="payments.isCreditSale">This sale will be posted as customer credit.</span>
					<span v-else-if="payments.isPartialPayment">
						The unpaid balance will remain outstanding on the customer account.
					</span>
					<span v-else>The refund will remain as customer credit instead of cash.</span>
				</div>
				<div class="flex justify-between text-sm">
					<span class="text-muted">{{ isReturn ? "Refunded" : "Tendered" }}</span>
					<span class="font-semibold tnum">{{ formatCurrency(Math.abs(payments.paid)) }}</span>
				</div>
				<div class="flex justify-between text-sm">
					<span :class="payments.outstanding > 0 ? 'text-danger' : 'text-muted'">
						{{
							payments.outstanding > 0
								? isReturn
									? "Still to refund"
									: "Still owed"
								: isReturn
									? "Over-refunded"
									: "Change"
						}}
					</span>
					<span
						class="font-bold tnum"
						:class="payments.outstanding > 0 ? 'text-danger' : 'text-success'"
					>
						{{ formatCurrency(payments.outstanding > 0 ? payments.outstanding : payments.change) }}
					</span>
				</div>

				<button
					type="button"
					class="flex h-13 w-full items-center justify-center gap-2 rounded-card text-base font-semibold text-white shadow-md transition hover:opacity-90 disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-subtle disabled:shadow-none"
					:class="isReturn ? 'bg-danger' : 'bg-success'"
					:disabled="!payments.canSubmit"
					@click="complete"
				>
					<Loader2 v-if="payments.submitting" class="size-5 animate-spin" />
					<Check v-else class="size-5" />
					{{
						payments.submitting
							? isReturn
								? "Refunding…"
								: "Completing…"
							: isReturn
								? "Complete refund"
								: "Complete sale"
					}}
				</button>
			</footer>
		</template>
	</section>
</template>
