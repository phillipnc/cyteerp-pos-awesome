"""Company-currency POS sales, returns, margin, and volume performance."""

import frappe
from frappe import _
from frappe.utils import flt

from posawesome.posawesome.api.reporting import aggregate_sales_performance


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
			"owner",
			"pos_profile",
			"posa_pos_opening_shift",
			"is_return",
			"base_grand_total",
			"base_net_total",
			"base_discount_amount",
			"base_total_taxes_and_charges",
		],
		order_by="posting_date, posting_time, name",
		limit_page_length=0,
	)
	shift_names = {
		row.posa_pos_opening_shift
		for row in invoices
		if row.posa_pos_opening_shift
	}
	cashiers = {
		row.name: row.user
		for row in (
			frappe.get_all(
				"POS Opening Shift",
				filters={"name": ["in", list(shift_names)]},
				fields=["name", "user"],
				limit_page_length=0,
			)
			if shift_names
			else []
		)
	}
	invoices = [
		{
			**row,
			"cashier": cashiers.get(row.posa_pos_opening_shift) or row.owner,
		}
		for row in invoices
		if not filters.cashier
		or (cashiers.get(row.posa_pos_opening_shift) or row.owner) == filters.cashier
	]
	invoice_names = [row["name"] for row in invoices]
	items = (
		frappe.get_all(
			"Sales Invoice Item",
			filters={
				"parent": ["in", invoice_names],
				"parenttype": "Sales Invoice",
			},
			fields=["parent", "qty", "stock_qty", "incoming_rate"],
			limit_page_length=0,
			ignore_permissions=True,
		)
		if invoice_names
		else []
	)
	data = aggregate_sales_performance(
		invoices,
		items,
		company_currency=company_currency,
		group_by=filters.group_by,
	)
	chart = {
		"data": {
			"labels": [row["group"] for row in data],
			"datasets": [
				{
					"name": _("Sales After Returns"),
					"values": [flt(row["sales_after_returns"]) for row in data],
				},
				{
					"name": _("Gross Profit"),
					"values": [flt(row["gross_profit"]) for row in data],
				},
			],
		},
		"type": "line" if filters.group_by == "Day" else "bar",
		"colors": ["#2490ef", "#21ba45"],
	}
	summary = [
		{
			"value": sum(flt(row["sales_after_returns"]) for row in data),
			"indicator": "Blue",
			"label": _("Sales After Returns"),
			"datatype": "Currency",
			"currency": company_currency,
		},
		{
			"value": sum(flt(row["returns"]) for row in data),
			"indicator": "Red",
			"label": _("Returns"),
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
	]
	message = None
	if any(not row["has_cost_data"] for row in data):
		message = _(
			"Gross profit is blank for groups without incoming-rate cost data. "
			"Sales and return values remain valid company-currency totals."
		)
	return _columns(filters.group_by), data, message, chart, summary


def _validate_filters(filters):
	if not filters.company or not filters.from_date or not filters.to_date:
		frappe.throw(_("Company, From Date and To Date are required"))
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))
	if filters.group_by not in ("Day", "POS Profile", "Cashier"):
		frappe.throw(_("Invalid Group By value"))


def _columns(group_by):
	return [
		{"fieldname": "group", "label": _(group_by), "fieldtype": "Data", "width": 170},
		{"fieldname": "invoice_count", "label": _("Sales"), "fieldtype": "Int", "width": 80},
		{"fieldname": "return_count", "label": _("Returns"), "fieldtype": "Int", "width": 80},
		{"fieldname": "company_currency", "label": _("Currency"), "fieldtype": "Link", "options": "Currency", "width": 90},
		{"fieldname": "gross_sales", "label": _("Gross Sales"), "fieldtype": "Currency", "options": "company_currency", "width": 130},
		{"fieldname": "returns", "label": _("Returns Value"), "fieldtype": "Currency", "options": "company_currency", "width": 125},
		{"fieldname": "sales_after_returns", "label": _("Sales After Returns"), "fieldtype": "Currency", "options": "company_currency", "width": 155},
		{"fieldname": "net_revenue", "label": _("Net Revenue Before Tax"), "fieldtype": "Currency", "options": "company_currency", "width": 170},
		{"fieldname": "discount", "label": _("Discounts"), "fieldtype": "Currency", "options": "company_currency", "width": 115},
		{"fieldname": "tax", "label": _("Tax"), "fieldtype": "Currency", "options": "company_currency", "width": 110},
		{"fieldname": "average_ticket", "label": _("Average Sale"), "fieldtype": "Currency", "options": "company_currency", "width": 125},
		{"fieldname": "stock_qty", "label": _("Stock Qty"), "fieldtype": "Float", "width": 105},
		{"fieldname": "cogs", "label": _("COGS"), "fieldtype": "Currency", "options": "company_currency", "width": 115},
		{"fieldname": "gross_profit", "label": _("Gross Profit"), "fieldtype": "Currency", "options": "company_currency", "width": 125},
	]
