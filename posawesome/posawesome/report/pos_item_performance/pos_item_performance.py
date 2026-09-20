"""Item, item-group, and brand POS performance in company currency."""

import frappe
from frappe import _
from frappe.utils import flt

from posawesome.posawesome.api.reporting import aggregate_item_performance


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
		fields=["name", "is_return"],
		limit_page_length=0,
	)
	invoice_names = [row.name for row in invoices]
	items = (
		frappe.get_all(
			"Sales Invoice Item",
			filters={
				"parent": ["in", invoice_names],
				"parenttype": "Sales Invoice",
			},
			fields=[
				"parent",
				"item_code",
				"qty",
				"stock_qty",
				"base_net_amount",
				"base_amount",
				"base_price_list_rate",
				"base_rate",
				"incoming_rate",
			],
			limit_page_length=0,
			ignore_permissions=True,
		)
		if invoice_names
		else []
	)
	item_codes = {row.item_code for row in items if row.item_code}
	item_metadata = {
		row.item_code: row
		for row in (
			frappe.get_all(
				"Item",
				filters={"item_code": ["in", list(item_codes)]},
				fields=["item_code", "item_group", "brand"],
				limit_page_length=0,
			)
			if item_codes
			else []
		)
	}
	data = aggregate_item_performance(
		invoices,
		items,
		company_currency=company_currency,
		item_metadata=item_metadata,
		group_by=filters.group_by,
	)
	chart_rows = data[:20]
	chart = {
		"data": {
			"labels": [row["group"] for row in chart_rows],
			"datasets": [
				{
					"name": _("Net Revenue"),
					"values": [flt(row["net_revenue"]) for row in chart_rows],
				},
				{
					"name": _("Gross Profit"),
					"values": [flt(row["gross_profit"]) for row in chart_rows],
				},
			],
		},
		"type": "bar",
		"colors": ["#2490ef", "#21ba45"],
	}
	summary = [
		{
			"value": sum(flt(row["net_revenue"]) for row in data),
			"indicator": "Blue",
			"label": _("Net Revenue"),
			"datatype": "Currency",
			"currency": company_currency,
		},
		{
			"value": sum(flt(row["gross_profit"]) for row in data),
			"indicator": "Green",
			"label": _("Gross Profit (Costed Lines)"),
			"datatype": "Currency",
			"currency": company_currency,
		},
		{
			"value": sum(flt(row["returned_qty"]) for row in data),
			"indicator": "Red",
			"label": _("Returned Stock Qty"),
			"datatype": "Float",
		},
	]
	message = None
	if any(not row["has_cost_data"] for row in data):
		message = _(
			"Gross profit is blank for groups without complete incoming-rate cost data."
		)
	return _columns(filters.group_by), data, message, chart, summary


def _validate_filters(filters):
	if not filters.company or not filters.from_date or not filters.to_date:
		frappe.throw(_("Company, From Date and To Date are required"))
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))
	if filters.group_by not in ("Item", "Item Group", "Brand"):
		frappe.throw(_("Invalid Group By value"))


def _columns(group_by):
	return [
		{"fieldname": "group", "label": _(group_by), "fieldtype": "Data", "width": 180},
		{"fieldname": "invoice_count", "label": _("Invoices"), "fieldtype": "Int", "width": 85},
		{"fieldname": "sold_qty", "label": _("Sold Qty"), "fieldtype": "Float", "width": 100},
		{"fieldname": "returned_qty", "label": _("Returned Qty"), "fieldtype": "Float", "width": 110},
		{"fieldname": "net_qty", "label": _("Net Qty"), "fieldtype": "Float", "width": 95},
		{"fieldname": "company_currency", "label": _("Currency"), "fieldtype": "Link", "options": "Currency", "width": 90},
		{"fieldname": "net_revenue", "label": _("Net Revenue"), "fieldtype": "Currency", "options": "company_currency", "width": 130},
		{"fieldname": "discount", "label": _("Discounts"), "fieldtype": "Currency", "options": "company_currency", "width": 115},
		{"fieldname": "cogs", "label": _("COGS"), "fieldtype": "Currency", "options": "company_currency", "width": 115},
		{"fieldname": "gross_profit", "label": _("Gross Profit"), "fieldtype": "Currency", "options": "company_currency", "width": 125},
		{"fieldname": "gross_margin_pct", "label": _("Gross Margin %"), "fieldtype": "Percent", "width": 125},
	]
