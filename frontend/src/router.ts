/**
 * Routes are deliberately few. A POS is one screen with panels, not a site — the
 * only real navigation is between selling, opening a shift and closing it.
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { useSessionStore } from "@/stores/session";

const routes: RouteRecordRaw[] = [
	{ path: "/", redirect: "/sell" },
	{ path: "/sell", name: "sell", component: () => import("@/views/SellView.vue") },
	{ path: "/shift", name: "shift", component: () => import("@/views/OpenShiftView.vue") },
	{ path: "/close", name: "close", component: () => import("@/views/CloseShiftView.vue") },
	{ path: "/payments", name: "payments", component: () => import("@/views/PaymentsView.vue") },
	{ path: "/:pathMatch(.*)*", redirect: "/sell" },
];

export const router = createRouter({
	// Frappe serves the SPA at /posawesome, so every route hangs off that base.
	history: createWebHistory("/posawesome"),
	routes,
});

// Selling and closing only exist while a shift is open; typing the URL or
// pressing Back must land on the opening form instead of a half-alive screen.
router.beforeEach((to) => {
	const session = useSessionStore();
	const shiftOpen = session.ready;

	if ((to.name === "sell" || to.name === "close" || to.name === "payments") && !shiftOpen)
		return { name: "shift" };
	if (to.name === "shift" && shiftOpen) return { name: "sell" };
});
