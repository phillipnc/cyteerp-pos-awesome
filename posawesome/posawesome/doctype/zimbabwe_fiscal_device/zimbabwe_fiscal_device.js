// Copyright (c) 2026, CyteERP contributors
// License: GPL-3.0

frappe.ui.form.on("Zimbabwe Fiscal Device", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Get Device Configuration"), () => {
			frappe.call({
				method:
					"posawesome.posawesome.api.zimbabwe_fiscal.get_device_configuration",
				args: { device_name: frm.doc.name },
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		}, __("ZIMRA"));

		frm.add_custom_button(__("Refresh Fiscal Status"), () => {
			frappe.call({
				method: "posawesome.posawesome.api.zimbabwe_fiscal.refresh_device_status",
				args: { device_name: frm.doc.name },
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		}, __("ZIMRA"));

		if (["FiscalDayOpened", "FiscalDayCloseFailed"].includes(frm.doc.fiscal_day_status)) {
			frm.add_custom_button(__("Close Fiscal Day"), () => {
				frappe.call({
					method: "posawesome.posawesome.api.zimbabwe_fiscal.close_day",
					args: { device_name: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			}, __("ZIMRA"));
		}
	},
});
