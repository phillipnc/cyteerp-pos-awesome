"""POS invoice settlement status and split-tender visibility."""

from collections import Counter

import frappe
from frappe import _
from frappe.utils import cint, flt

from posawesome.posawesome.api.reporting import build_payment_status_rows


def execute(filters=None):
	filters = frappe._dict(filters or {})
	_validate_filters(filters)
	company_currency = frappe.get_cached_value(
		"Company", filters.company, "default_currency"
	)
	invoice_filters = {
		"company": filters.company,
		"docstatus": 1,
		"posting_date": ["between", [filters.from_date, filters.to_date]],
		"posa_pos_opening_shift": ["is", "set"],
	}
	if filters.pos_profile:
		invoice_filters["pos_profile"] = filters.pos_profile
	invoices = frappe.get_all(
		"Sales Invoice",
		filters=invoice_filters,
		fields=[
			"name",
			"posting_date",
			"posting_time",
			"customer",
			"pos_profile",
			"posa_pos_opening_shift",
			"is_return",
			"currency",
			"grand_total",
			"base_grand_total",
			"base_paid_amount",
			"base_outstanding_amount",
		],
		order_by="posting_date desc, posting_time desc, name desc",
		limit_page_length=0,
	)
	invoice_names = [row.name for row in invoices]
	payments = (
		frappe.get_all(
			"Sales Invoice Payment",
			filters={
				"parent": ["in", invoice_names],
				"parenttype": "Sales Invoice",
			},
			fields=[
				"parent",
				"mode_of_payment",
				"base_amount",
				"posa_tender_currency",
				"posa_tender_amount",
			],
			limit_page_length=0,
			ignore_permissions=True,
		)
		if invoice_names
		else []
	)
	data = build_payment_status_rows(
		invoices,
		payments,
		company_currency=company_currency,
	)
	if filters.payment_status:
		data = [
			row for row in data
			if row["payment_status"] == filters.payment_status
		]
	if cint(filters.split_only):
		data = [row for row in data if row["is_split_payment"]]

	counts = Counter(row["payment_status"] for row in data)
	chart = {
		"data": {
			"labels": list(counts),
			"datasets": [{"name": _("Invoices"), "values": list(counts.values())}],
		},
		"type": "donut",
		"colors": ["#21ba45", "#f2c037", "#c10015", "#607d8b"],
	}
	summary = [
		{
			"value": sum(
				flt(row["company_paid"]) for row in data if not row["is_return"]
			),
			"indicator": "Green",
			"label": _("Paid"),
			"datatype": "Currency",
			"currency": company_currency,
		},
		{
			"value": sum(
				flt(row["company_outstanding"])
				for row in data
				if not row["is_return"]
			),
			"indicator": "Red",
			"label": _("Outstanding"),
			"datatype": "Currency",
			"currency": company_currency,
		},
		{
			"value": sum(1 for row in data if row["is_split_payment"]),
			"indicator": "Blue",
			"label": _("Split Payments"),
			"datatype": "Int",
		},
	]
	return _columns(), data, None, chart, summary


def _validate_filters(filters):
	if not filters.company or not filters.from_date or not filters.to_date:
		frappe.throw(_("Company, From Date and To Date are required"))
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))


def _columns():
	return [
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "name", "label": _("Sales Invoice"), "fieldtype": "Link", "options": "Sales Invoice", "width": 170},
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link", "options": "Customer", "width": 160},
		{"fieldname": "payment_status", "label": _("Payment Status"), "fieldtype": "Data", "width": 115},
		{"fieldname": "is_split_payment", "label": _("Split"), "fieldtype": "Check", "width": 70},
		{"fieldname": "currency", "label": _("Invoice Currency"), "fieldtype": "Link", "options": "Currency", "width": 110},
		{"fieldname": "grand_total", "label": _("Invoice Total"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "company_currency", "label": _("Company Currency"), "fieldtype": "Link", "options": "Currency", "width": 120},
		{"fieldname": "company_total", "label": _("Company Total"), "fieldtype": "Currency", "options": "company_currency", "width": 130},
		{"fieldname": "company_paid", "label": _("Paid"), "fieldtype": "Currency", "options": "company_currency", "width": 115},
		{"fieldname": "company_outstanding", "label": _("Outstanding"), "fieldtype": "Currency", "options": "company_currency", "width": 125},
		{"fieldname": "payment_methods", "label": _("Payment Methods"), "fieldtype": "Data", "width": 180},
		{"fieldname": "tender_currencies", "label": _("Tender Currencies"), "fieldtype": "Data", "width": 210},
		{"fieldname": "pos_profile", "label": _("POS Profile"), "fieldtype": "Link", "options": "POS Profile", "width": 140},
		{"fieldname": "posa_pos_opening_shift", "label": _("Opening Shift"), "fieldtype": "Link", "options": "POS Opening Shift", "width": 150},
	]
