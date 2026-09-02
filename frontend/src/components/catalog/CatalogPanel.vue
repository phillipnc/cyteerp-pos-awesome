<script setup lang="ts">
/** Left-hand panel: find an item and put it in the cart. */
import { onMounted, ref } from "vue";
import { LayoutGrid, List, Loader2, PackageOpen, RotateCw, Search, X } from "lucide-vue-next";
import { useCatalogStore } from "@/stores/catalog";
import { useCartStore } from "@/stores/cart";
import { useSessionStore } from "@/stores/session";
import { useUiStore } from "@/stores/ui";
import { registerHotkeys } from "@/lib/hotkeys";
import { relativeTime } from "@/lib/format";
import { decodeScaleBarcode } from "@/lib/scanner";
import type { Item } from "@/types";
import ItemCard from "./ItemCard.vue";
import ItemRow from "./ItemRow.vue";

const catalog = useCatalogStore();
const cart = useCartStore();
const session = useSessionStore();
const ui = useUiStore();

const searchEl = ref<HTMLInputElement | null>(null);

onMounted(() => {
	void catalog.load();
	void catalog.loadGroups();
});

const stop = registerHotkeys([
	{
		combo: "F2",
		label: "Focus item search",
		group: "Catalog",
		handler: () => searchEl.value?.select(),
	},
]);
// Vue calls the setup teardown on unmount; releasing the hotkey keeps the
// registry honest when the panel is swapped out.
import { onUnmounted } from "vue";
onUnmounted(stop);

/** A scanned barcode arrives as a full string plus Enter, not keystroke by keystroke. */
async function onSubmitSearch() {
	const term = catalog.search.trim();
	if (!term) return;

	// Scale tickets carry the weight in the tail; resolve the item from the head.
	const scale = decodeScaleBarcode(term, session.profile?.posa_scale_barcode_start);
	const lookup = scale?.lookup ?? term;

	const resolved = await catalog.resolveScan(lookup);
	if (resolved) {
		await cart.addItem(resolved, {
			qty: scale?.weight,
			uom: resolved.scanned_uom ?? undefined,
			batchNo: resolved.scanned_batch_no ?? undefined,
			serialNo: resolved.scanned_serial_no ?? undefined,
		});
		catalog.setSearch("");
		return;
	}

	// Exactly one match is unambiguous — treat Enter as "add it".
	if (!scale && catalog.filtered.length === 1) {
		await cart.addItem(catalog.filtered[0]);
		catalog.setSearch("");
		return;
	}

	if (!catalog.filtered.length || scale) ui.warn("No item matches", lookup);
}

async function pick(item: Item) {
	if (item.has_variants) {
		ui.notify({ title: "Template item", detail: "Pick a specific variant.", tone: "warning" });
		return;
	}
	await cart.addItem(item);
}
</script>

<template>
	<section class="flex h-full min-h-0 flex-col gap-3">
		<!-- Search + view controls -->
		<div class="flex items-center gap-2">
			<div class="relative min-w-0 flex-1">
				<Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle" />
				<input
					ref="searchEl"
					:value="catalog.search"
					type="search"
					inputmode="search"
					autocomplete="off"
					placeholder="Scan a barcode or search items…  (F2)"
					class="h-11 w-full rounded-card border-line bg-surface pl-9 pr-9 text-sm shadow-xs transition placeholder:text-subtle focus:border-accent focus:ring-0"
					@input="catalog.setSearch(($event.target as HTMLInputElement).value)"
					@keydown.enter.prevent="onSubmitSearch"
				/>
				<button
					v-if="catalog.search"
					type="button"
					class="absolute right-2 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-full text-subtle transition hover:bg-surface-2 hover:text-fg"
					aria-label="Clear search"
					@click="catalog.clearFilters()"
				>
					<X class="size-3.5" />
				</button>
			</div>

			<div class="flex shrink-0 items-center rounded-card border border-line bg-surface p-0.5 shadow-xs">
				<button
					type="button"
					class="grid size-9 place-items-center rounded-[0.6rem] transition"
					:class="catalog.viewMode === 'grid' ? 'bg-accent-soft text-accent' : 'text-subtle hover:text-fg'"
					aria-label="Grid view"
					@click="catalog.viewMode = 'grid'"
				>
					<LayoutGrid class="size-4" />
				</button>
				<button
					type="button"
					class="grid size-9 place-items-center rounded-[0.6rem] transition"
					:class="catalog.viewMode === 'list' ? 'bg-accent-soft text-accent' : 'text-subtle hover:text-fg'"
					aria-label="List view"
					@click="catalog.viewMode = 'list'"
				>
					<List class="size-4" />
				</button>
			</div>

			<button
				type="button"
				class="grid size-10 shrink-0 place-items-center rounded-card border border-line bg-surface text-subtle shadow-xs transition hover:text-fg"
				title="Reload catalog"
				aria-label="Reload catalog"
				@click="catalog.load({ force: true })"
			>
				<RotateCw class="size-4" :class="catalog.loading && 'animate-spin'" />
			</button>
		</div>

		<!-- Group filter -->
		<div v-if="catalog.groups.length" class="-mx-0.5 flex gap-1.5 overflow-x-auto px-0.5 pb-0.5">
			<button
				v-for="group in catalog.groups"
				:key="group"
				type="button"
				class="shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium transition"
				:class="
					catalog.activeGroup === group
						? 'border-accent bg-accent text-accent-fg'
						: 'border-line bg-surface text-muted hover:border-line-strong hover:text-fg'
				"
				@click="catalog.setGroup(group)"
			>
				{{ group }}
			</button>
		</div>

		<!-- Results -->
		<div class="panel min-h-0 flex-1 overflow-y-auto p-2.5">
			<div
				v-if="catalog.loading && !catalog.filtered.length"
				class="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
			>
				<div v-for="n in 12" :key="n" class="skeleton aspect-[3/4] rounded-card" />
			</div>

			<div
				v-else-if="!catalog.filtered.length"
				class="flex h-full flex-col items-center justify-center gap-2 py-16 text-center"
			>
				<PackageOpen class="size-8 text-subtle" />
				<p class="text-sm font-medium">No items found</p>
				<p class="max-w-xs text-xs text-muted">
					{{ catalog.search || catalog.activeGroup ? "Try a different search or group." : "This profile has no items yet." }}
				</p>
				<button
					v-if="catalog.search || catalog.activeGroup"
					type="button"
					class="mt-1 text-xs font-semibold text-accent hover:underline"
					@click="catalog.clearFilters()"
				>
					Clear filters
				</button>
			</div>

			<div
				v-else-if="catalog.viewMode === 'grid'"
				class="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
			>
				<ItemCard
					v-for="(item, i) in catalog.filtered.slice(0, 200)"
					:key="item.item_code"
					:item="item"
					:index="i"
					@pick="pick"
				/>
			</div>

			<div v-else class="divide-y divide-line">
				<ItemRow
					v-for="(item, i) in catalog.filtered.slice(0, 300)"
					:key="item.item_code"
					:item="item"
					:index="i"
					@pick="pick"
				/>
			</div>
		</div>

		<!-- Footer status -->
		<div class="flex items-center justify-between px-1 text-[11px] text-subtle">
			<span>
				{{ catalog.filtered.length }} of {{ catalog.items.length }} items
				<span v-if="catalog.loadedFromCache" class="text-warning"> · cached</span>
			</span>
			<span v-if="catalog.loading" class="inline-flex items-center gap-1">
				<Loader2 class="size-3 animate-spin" /> updating
			</span>
			<span v-else-if="catalog.lastLoadedAt">{{ relativeTime(new Date(catalog.lastLoadedAt)) }}</span>
		</div>
	</section>
</template>
