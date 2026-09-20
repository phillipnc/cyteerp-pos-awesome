"""Currency-separated POS sales with company-currency equivalents."""

import frappe
from frappe import _
from frappe.utils import flt

from posawesome.posawesome.api.reporting import aggregate_shift


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
	if filters.opening_shift:
		invoice_filters["posa_pos_opening_shift"] = filters.opening_shift
	if filters.currency:
		invoice_filters["currency"] = filters.currency

	invoices = frappe.get_all(
		"Sales Invoice",
		filters=invoice_filters,
		fields=[
			"name",
			"posting_time",
			"is_return",
			"currency",
			"conversion_rate",
			"grand_total",
			"base_grand_total",
			"net_total",
			"base_net_total",
			"discount_amount",
			"base_discount_amount",
			"change_amount",
			"base_change_amount",
		],
		limit_page_length=0,
	)
	invoice_names = [row.name for row in invoices]
	items = (
		frappe.get_all(
			"Sales Invoice Item",
			filters={"parent": ["in", invoice_names], "parenttype": "Sales Invoice"},
			fields=[
				"parent",
				"item_code",
				"item_name",
				"qty",
				"stock_qty",
				"uom",
				"stock_uom",
				"price_list_rate",
				"rate",
				"base_price_list_rate",
				"base_rate",
				"base_amount",
				"base_net_amount",
			],
			limit_page_length=0,
			ignore_permissions=True,
		)
		if invoice_names
		else []
	)
	result = aggregate_shift(
		invoices,
		[],
		items,
		company_currency=company_currency,
	)
	data = [
		{
			**row,
			"company_currency": company_currency,
		}
		for row in result["currency_totals"]
	]
	chart = {
		"data": {
			"labels": [row["currency"] for row in data],
			"datasets": [
				{
					"name": _("Sales After Returns ({0})").format(company_currency),
					"values": [flt(row["company_net_sales"]) for row in data],
				}
			],
		},
		"type": "bar",
		"colors": ["#2490ef"],
	}
	summary = [
		{
			"value": result["grand_total"],
			"indicator": "Green",
			"label": _("Gross Sales"),
			"datatype": "Currency",
			"currency": company_currency,
		},
		{
			"value": result["total_returned"],
			"indicator": "Red",
			"label": _("Returns"),
			"datatype": "Currency",
			"currency": company_currency,
		},
		{
			"value": result["net_sales"],
			"indicator": "Blue",
			"label": _("Sales After Returns"),
			"datatype": "Currency",
			"currency": company_currency,
		},
		{
			"value": result["net_total"],
			"indicator": "Purple",
			"label": _("Net Revenue Before Tax"),
			"datatype": "Currency",
			"currency": company_currency,
		},
		{
			"value": result["total_discount"],
			"indicator": "Orange",
			"label": _("Discounts"),
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
		{"fieldname": "currency", "label": _("Invoice Currency"), "fieldtype": "Link", "options": "Currency", "width": 120},
		{"fieldname": "invoice_count", "label": _("Sales"), "fieldtype": "Int", "width": 80},
		{"fieldname": "return_count", "label": _("Returns"), "fieldtype": "Int", "width": 80},
		{"fieldname": "sales", "label": _("Gross Sales"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "returns", "label": _("Returns"), "fieldtype": "Currency", "options": "currency", "width": 120},
		{"fieldname": "net_sales", "label": _("Sales After Returns"), "fieldtype": "Currency", "options": "currency", "width": 145},
		{"fieldname": "net_total", "label": _("Net Revenue Before Tax"), "fieldtype": "Currency", "options": "currency", "width": 165},
		{"fieldname": "discount", "label": _("Discounts"), "fieldtype": "Currency", "options": "currency", "width": 120},
		{"fieldname": "company_currency", "label": _("Company Currency"), "fieldtype": "Link", "options": "Currency", "width": 120},
		{"fieldname": "company_sales", "label": _("Company Gross Sales"), "fieldtype": "Currency", "options": "company_currency", "width": 150},
		{"fieldname": "company_returns", "label": _("Company Returns"), "fieldtype": "Currency", "options": "company_currency", "width": 140},
		{"fieldname": "company_net_sales", "label": _("Company Sales After Returns"), "fieldtype": "Currency", "options": "company_currency", "width": 190},
		{"fieldname": "company_net_total", "label": _("Company Net Revenue"), "fieldtype": "Currency", "options": "company_currency", "width": 165},
		{"fieldname": "company_discount", "label": _("Company Discounts"), "fieldtype": "Currency", "options": "company_currency", "width": 145},
	]
