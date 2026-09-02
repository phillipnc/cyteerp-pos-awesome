<script setup lang="ts">
import { computed } from "vue";
import { CloudOff, HandCoins, Keyboard, LogOut, ShoppingBag, Store } from "lucide-vue-next";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";
import { useCartStore } from "@/stores/cart";
import { useSyncStore } from "@/stores/sync";
import ConnectionPill from "./ConnectionPill.vue";
import ThemeButton from "./ThemeButton.vue";

const session = useSessionStore();
const ui = useUiStore();
const cart = useCartStore();
const sync = useSyncStore();

const initials = computed(() =>
	(session.fullName || session.user || "?")
		.split(/[\s.@_-]+/)
		.filter(Boolean)
		.slice(0, 2)
		.map((part) => part[0]?.toUpperCase() ?? "")
		.join(""),
);
</script>

<template>
	<header
		class="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-3 sm:px-4"
	>
		<div class="flex items-center gap-2.5">
			<span class="grid size-9 place-items-center rounded-card bg-accent text-accent-fg shadow-glow">
				<ShoppingBag class="size-5" />
			</span>
			<div class="hidden leading-tight sm:block">
				<p class="text-sm font-semibold">POS Awesome</p>
				<p class="text-[11px] text-subtle">{{ session.profile?.name || "No profile" }}</p>
			</div>
		</div>

		<div class="mx-1 hidden h-7 w-px bg-line md:block" />

		<div class="hidden min-w-0 items-center gap-1.5 text-xs text-muted md:flex">
			<Store class="size-3.5 shrink-0" />
			<span class="truncate">{{ session.warehouse || "—" }}</span>
		</div>

		<div class="ml-auto flex items-center gap-1.5 sm:gap-2">
			<span
				v-if="cart.isReturn"
				class="rounded-full bg-danger-soft px-2.5 py-1 text-xs font-semibold text-danger"
			>
				Return
			</span>

			<!-- Offline invoices. Present whenever the profile allows offline selling, not
			     only once something is stuck, so a cashier can check the queue is empty. -->
			<button
				v-if="session.offlineEnabled"
				type="button"
				class="relative grid size-9 place-items-center rounded-card transition"
				:class="sync.hasOutstanding ? 'text-warning hover:bg-warning-soft' : 'text-muted hover:bg-surface-2 hover:text-fg'"
				:title="sync.hasOutstanding ? `${sync.outstanding} offline invoice(s) waiting to send` : 'Offline invoices'"
				aria-label="Offline invoices"
				@click="ui.openModal('queue')"
			>
				<CloudOff class="size-4.5" />
				<span
					v-if="sync.hasOutstanding"
					class="absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-warning px-1 text-[10px] font-bold text-inverse"
					:class="sync.draining && 'animate-pulse'"
					>{{ sync.outstanding }}</span
				>
			</button>

			<ConnectionPill />

			<RouterLink
				v-if="session.profile?.posa_use_pos_awesome_payments"
				to="/payments"
				class="grid size-9 place-items-center rounded-card text-muted transition hover:bg-surface-2 hover:text-fg"
				title="Customer payments"
				aria-label="Customer payments"
			>
				<HandCoins class="size-4.5" />
			</RouterLink>

			<button
				type="button"
				class="grid size-9 place-items-center rounded-card text-muted transition hover:bg-surface-2 hover:text-fg"
				title="Keyboard shortcuts"
				aria-label="Keyboard shortcuts"
				@click="ui.shortcutsOpen = true"
			>
				<Keyboard class="size-4.5" />
			</button>

			<ThemeButton />

			<div class="mx-0.5 h-7 w-px bg-line" />

			<div class="flex items-center gap-2">
				<span
					class="grid size-8 place-items-center rounded-full bg-surface-2 text-xs font-semibold text-muted"
					:title="session.fullName || session.user"
					>{{ initials }}</span
				>
				<RouterLink
					to="/close"
					class="grid size-9 place-items-center rounded-card text-muted transition hover:bg-danger-soft hover:text-danger"
					title="Close shift"
					aria-label="Close shift"
				>
					<LogOut class="size-4.5" />
				</RouterLink>
			</div>
		</div>
	</header>
</template>
