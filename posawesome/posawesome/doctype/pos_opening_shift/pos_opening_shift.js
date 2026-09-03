// Copyright (c) 2020, Youssef Restom and contributors
// For license information, please see license.txt

frappe.ui.form.on('POS Opening Shift', {
	setup(frm) {
		if (frm.doc.docstatus == 0) {
			frm.trigger('set_posting_date_read_only');
			frm.set_value('period_start_date', frappe.datetime.now_datetime());
			frm.set_value('user', frappe.session.user);
		}
		frm.set_query("user", function(doc) {
			return {
				query: "posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift.get_cashiers",
				filters: { 'parent': doc.pos_profile }
			};
		});
		frm.set_query("pos_profile", function(doc) {
			return {
				filters: { 'company': doc.company}
			};
		});
	},

	refresh(frm) {
		// set default posting date / time
		if(frm.doc.docstatus == 0) {
			if(!frm.doc.posting_date) {
				frm.set_value('posting_date', frappe.datetime.nowdate());
			}
			frm.trigger('set_posting_date_read_only');
		}
	},

	set_posting_date_read_only(frm) {
		if(frm.doc.docstatus == 0 && frm.doc.set_posting_date) {
			frm.set_df_property('posting_date', 'read_only', 0);
		} else {
			frm.set_df_property('posting_date', 'read_only', 1);
		}
	},

	set_posting_date(frm) {
		frm.trigger('set_posting_date_read_only');
	},

	async pos_profile(frm) {
		if (frm.doc.pos_profile) {
			const response = await frappe.call({
				method: "posawesome.posawesome.api.currency.get_currency_context",
				args: {
					pos_profile: frm.doc.pos_profile,
					posting_date: frm.doc.posting_date,
				},
			});
			const context = response.message || {};
			frm.clear_table("balance_details");
			for (const method of context.payment_methods || []) {
				frm.add_child("balance_details", {
					mode_of_payment: method.mode_of_payment,
					currency: method.currency,
					company_exchange_rate:
						(flt(method.exchange_rate) || 1) * (flt(context.conversion_rate) || 1),
					company_amount: 0,
				});
			}
			frm.refresh_field("balance_details");
		}
	},
});

frappe.ui.form.on("POS Opening Shift Detail", {
	amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(
			cdt,
			cdn,
			"company_amount",
			flt(row.amount) * (flt(row.company_exchange_rate) || 1),
		);
	},
});
