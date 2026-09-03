// Copyright (c) 2020, Youssef Restom and contributors
// Copyright (c) 2026, CyteERP contributors
// License: GPL-3.0

const CLOSING_FIELDS = [
	"period_start_date",
	"period_end_date",
	"posting_date",
	"company",
	"pos_profile",
	"user",
	"pos_transactions",
	"pos_payments",
	"payment_reconciliation",
	"grand_total",
	"net_total",
	"total_quantity",
	"taxes",
];

frappe.ui.form.on("POS Closing Shift", {
	onload(frm) {
		frm.set_query("pos_profile", (doc) => ({ filters: { user: doc.user } }));
		frm.set_query("user", (doc) => ({
			query: "posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift.get_cashiers",
			filters: { parent: doc.pos_profile },
		}));
		frm.set_query("pos_opening_shift", () => ({
			filters: { status: "Open", docstatus: 1 },
		}));

		if (frm.doc.docstatus === 0) {
			frm.set_value("period_end_date", frappe.datetime.now_datetime());
		}
		if (frm.doc.docstatus === 1) set_html_data(frm);
	},

	async pos_opening_shift(frm) {
		if (!frm.doc.pos_opening_shift || frm.doc.docstatus !== 0) return;

		const response = await frappe.call({
			method:
				"posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift.make_closing_shift_from_opening",
			args: { opening_shift: frm.doc.pos_opening_shift },
			freeze: true,
			freeze_message: __("Calculating currency-safe shift totals…"),
		});
		const data = response.message || {};
		for (const fieldname of CLOSING_FIELDS) {
			if (Object.prototype.hasOwnProperty.call(data, fieldname)) {
				await frm.set_value(fieldname, data[fieldname]);
			}
		}
		frm.refresh_fields();
	},
});

frappe.ui.form.on("POS Closing Shift Detail", {
	closing_amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const rate = flt(row.company_exchange_rate) || 1;
		const closing = flt(row.closing_amount);
		frappe.model.set_value(cdt, cdn, "difference", closing - flt(row.expected_amount));
		frappe.model.set_value(cdt, cdn, "company_closing_amount", closing * rate);
		frappe.model.set_value(
			cdt,
			cdn,
			"company_difference",
			(closing - flt(row.expected_amount)) * rate,
		);
	},
});

function set_html_data(frm) {
	frappe.call({
		method: "get_payment_reconciliation_details",
		doc: frm.doc,
		callback: (response) => {
			frm.get_field("payment_reconciliation_details").$wrapper.html(response.message);
		},
	});
}
