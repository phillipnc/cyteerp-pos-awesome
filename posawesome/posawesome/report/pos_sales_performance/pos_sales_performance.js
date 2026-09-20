// Copyright (c) 2026, CyteERP contributors
// License: GPL-3.0

frappe.query_reports["POS Sales Performance"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: "Day\nPOS Profile\nCashier",
			default: "Day",
			reqd: 1,
		},
		{
			fieldname: "pos_profile",
			label: __("POS Profile"),
			fieldtype: "Link",
			options: "POS Profile",
			get_query: () => ({
				filters: { company: frappe.query_report.get_filter_value("company") },
			}),
		},
		{
			fieldname: "cashier",
			label: __("Cashier"),
			fieldtype: "Link",
			options: "User",
		},
	],
};
