// Copyright (c) 2026, CyteERP contributors
// License: GPL-3.0

frappe.query_reports["Zimbabwe Fiscal Day Summary"] = {
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
			fieldname: "device_id",
			label: __("Device ID"),
			fieldtype: "Int",
		},
		{
			fieldname: "fiscal_day_no",
			label: __("Fiscal Day"),
			fieldtype: "Int",
		},
		{
			fieldname: "currency",
			label: __("Receipt Currency"),
			fieldtype: "Link",
			options: "Currency",
		},
		{
			fieldname: "fiscal_status",
			label: __("Fiscal Status"),
			fieldtype: "Select",
			options: "\nAccepted\nPending\nFailed",
			default: "Accepted",
		},
	],
};
