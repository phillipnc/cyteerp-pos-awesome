<script setup lang="ts">
/** Opening a shift: pick the profile, declare the float, start selling. */
import { computed, onMounted, ref, watch } from "vue";
import { Loader2, PlayCircle, Store, Wallet } from "lucide-vue-next";
import { api } from "@/lib/api";
import { formatCurrency, toNumber } from "@/lib/format";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";
import type { PaymentMethod } from "@/types";

interface DialogData {
	companies: { name: string }[];
	pos_profiles_data: { name: string; company: string; currency: string; warehouse: string }[];
	payments_method: (PaymentMethod & { parent: string })[];
}

const session = useSessionStore();
const ui = useUiStore();

const data = ref<DialogData | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const company = ref("");
const profile = ref("");
const balances = ref<Record<string, number>>({});
const starting = ref(false);

const profiles = computed(() =>
	(data.value?.pos_profiles_data ?? []).filter((entry) => !company.value || entry.company === company.value),
);
const methods = computed(() =>
	(data.value?.payments_method ?? []).filter((entry) => entry.parent === profile.value),
);
const canStart = computed(() => !!company.value && !!profile.value && !starting.value);
const methodKey = (method: PaymentMethod) => `${method.mode_of_payment}::${method.currency}`;

onMounted(async () => {
	try {
		data.value = (await api.openingDialogData()) as DialogData;
		company.value = data.value.companies[0]?.name ?? "";
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	} finally {
		loading.value = false;
	}
});

// Picking a company narrows the profiles; default to the only sensible one.
watch([company, profiles], () => {
	if (!profiles.value.some((entry) => entry.name === profile.value)) {
		profile.value = profiles.value[0]?.name ?? "";
	}
});

watch(methods, (list) => {
	const next: Record<string, number> = {};
	for (const method of list) next[methodKey(method)] = balances.value[methodKey(method)] ?? 0;
	balances.value = next;
});

async function start() {
	if (!canStart.value) return;
	starting.value = true;
	try {
		await session.openShift({
			pos_profile: profile.value,
			company: company.value,
			balance_details: methods.value.map((method) => ({
				mode_of_payment: method.mode_of_payment,
				currency: method.currency,
				amount: toNumber(balances.value[methodKey(method)]),
			})),
		});
		ui.success("Shift open", `${profile.value} is ready.`);
	} catch (err) {
		ui.fail("Could not open the shift", err instanceof Error ? err.message : String(err));
	} finally {
		starting.value = false;
	}
}
</script>

<template>
	<div class="grid h-full place-items-center overflow-y-auto p-4">
		<div class="panel w-full max-w-md animate-fade-up p-6">
			<div class="mb-5 flex items-center gap-3">
				<span class="grid size-11 place-items-center rounded-card bg-accent-soft text-accent">
					<Store class="size-5" />
				</span>
				<div>
					<h1 class="text-base font-semibold">Open a shift</h1>
					<p class="text-xs text-muted">Declare what is in the drawer to begin.</p>
				</div>
			</div>

			<div v-if="loading" class="space-y-3">
				<div class="skeleton h-11 rounded-card" />
				<div class="skeleton h-11 rounded-card" />
				<div class="skeleton h-24 rounded-card" />
			</div>

			<p v-else-if="error" class="rounded-card bg-danger-soft p-3 text-sm text-danger">{{ error }}</p>

			<p
				v-else-if="!profiles.length"
				class="rounded-card bg-warning-soft p-3 text-sm text-warning"
			>
				You are not assigned to any POS Profile. Ask an administrator to add you to one.
			</p>

			<form v-else class="space-y-4" @submit.prevent="start">
				<label class="block">
					<span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-subtle">Company</span>
					<select
						v-model="company"
						class="h-11 w-full rounded-card border-line bg-surface text-sm focus:border-accent focus:ring-0"
					>
						<option v-for="entry in data?.companies ?? []" :key="entry.name" :value="entry.name">
							{{ entry.name }}
						</option>
					</select>
				</label>

				<label class="block">
					<span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-subtle">POS Profile</span>
					<select
						v-model="profile"
						class="h-11 w-full rounded-card border-line bg-surface text-sm focus:border-accent focus:ring-0"
					>
						<option v-for="entry in profiles" :key="entry.name" :value="entry.name">
							{{ entry.name }} — {{ entry.warehouse }}
						</option>
					</select>
				</label>

				<div v-if="methods.length">
					<span class="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-subtle">
						<Wallet class="size-3.5" /> Opening balance
					</span>
					<div class="space-y-2">
						<div
							v-for="method in methods"
							:key="methodKey(method)"
							class="flex items-center gap-2 rounded-card border border-line bg-surface-2 p-2"
						>
							<label class="min-w-0 flex-1 truncate text-sm" :for="`open-${methodKey(method)}`">
								{{ method.mode_of_payment }}
								<span class="ms-1 text-xs text-subtle">{{ method.currency }}</span>
							</label>
							<input
								:id="`open-${methodKey(method)}`"
								v-model.number="balances[methodKey(method)]"
								type="text"
								inputmode="decimal"
								placeholder="0.00"
								class="h-9 w-28 rounded-card border-line bg-surface text-right text-sm font-semibold tnum focus:border-accent focus:ring-0"
							/>
							<span class="sr-only">
								{{ formatCurrency(balances[methodKey(method)], method.currency) }}
							</span>
						</div>
					</div>
				</div>

				<button
					type="submit"
					class="flex h-12 w-full items-center justify-center gap-2 rounded-card bg-accent font-semibold text-accent-fg shadow-glow transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-subtle disabled:shadow-none"
					:disabled="!canStart"
				>
					<Loader2 v-if="starting" class="size-5 animate-spin" />
					<PlayCircle v-else class="size-5" />
					{{ starting ? "Opening…" : "Start selling" }}
				</button>
			</form>
		</div>
	</div>
</template>
