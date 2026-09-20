"""Customer frequency, value, and return analysis for POS invoices."""

import frappe
from frappe import _
from frappe.utils import cint, flt

from posawesome.posawesome.api.reporting import aggregate_customer_performance


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
			"customer",
			"customer_name",
			"is_return",
			"base_grand_total",
		],
		limit_page_length=0,
	)
	data = aggregate_customer_performance(
		invoices,
		company_currency=company_currency,
	)
	if cint(filters.repeat_only):
		data = [row for row in data if row["is_repeat_customer"]]
	chart_rows = data[:20]
	chart = {
		"data": {
			"labels": [row["customer_name"] for row in chart_rows],
			"datasets": [
				{
					"name": _("Net Customer Value"),
					"values": [flt(row["net_value"]) for row in chart_rows],
				}
			],
		},
		"type": "bar",
		"colors": ["#7b61ff"],
	}
	summary = [
		{
			"value": len(data),
			"indicator": "Blue",
			"label": _("Customers"),
			"datatype": "Int",
		},
		{
			"value": sum(1 for row in data if row["is_repeat_customer"]),
			"indicator": "Green",
			"label": _("Repeat Customers"),
			"datatype": "Int",
		},
		{
			"value": sum(flt(row["net_value"]) for row in data),
			"indicator": "Blue",
			"label": _("Net Customer Value"),
			"datatype": "Currency",
			"currency": company_currency,
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
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link", "options": "Customer", "width": 170},
		{"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "is_repeat_customer", "label": _("Repeat"), "fieldtype": "Check", "width": 70},
		{"fieldname": "invoice_count", "label": _("Sales"), "fieldtype": "Int", "width": 80},
		{"fieldname": "return_count", "label": _("Returns"), "fieldtype": "Int", "width": 80},
		{"fieldname": "company_currency", "label": _("Currency"), "fieldtype": "Link", "options": "Currency", "width": 90},
		{"fieldname": "gross_sales", "label": _("Gross Sales"), "fieldtype": "Currency", "options": "company_currency", "width": 130},
		{"fieldname": "returns", "label": _("Returns Value"), "fieldtype": "Currency", "options": "company_currency", "width": 125},
		{"fieldname": "net_value", "label": _("Net Customer Value"), "fieldtype": "Currency", "options": "company_currency", "width": 150},
		{"fieldname": "average_sale", "label": _("Average Sale"), "fieldtype": "Currency", "options": "company_currency", "width": 125},
		{"fieldname": "first_purchase_date", "label": _("First Purchase"), "fieldtype": "Date", "width": 110},
		{"fieldname": "last_purchase_date", "label": _("Last Purchase"), "fieldtype": "Date", "width": 110},
	]
