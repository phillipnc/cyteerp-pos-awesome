"""POS warehouse stock health, velocity, cover, and reorder visibility."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import date_diff, flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	_validate_filters(filters)
	company_currency = frappe.get_cached_value(
		"Company", filters.company, "default_currency"
	)
	profile_filters = {"company": filters.company, "disabled": 0}
	if filters.pos_profile:
		profile_filters["name"] = filters.pos_profile
	profiles = frappe.get_all(
		"POS Profile",
		filters=profile_filters,
		fields=["name", "warehouse"],
		limit_page_length=0,
	)
	profile_names = [row.name for row in profiles]
	warehouses = sorted({row.warehouse for row in profiles if row.warehouse})
	if filters.warehouse:
		warehouses = [
			warehouse for warehouse in warehouses
			if warehouse == filters.warehouse
		]
	if not warehouses:
		message = _(
			"No POS Profile warehouse matches the selected company and filters."
		)
		return _columns(), [], message, _chart([], company_currency), []

	bins = frappe.get_all(
		"Bin",
		filters={"warehouse": ["in", warehouses]},
		fields=[
			"item_code",
			"warehouse",
			"actual_qty",
			"projected_qty",
			"reserved_qty",
			"ordered_qty",
			"valuation_rate",
		],
		limit_page_length=0,
	)
	item_codes = sorted({row.item_code for row in bins if row.item_code})
	item_filters = {"item_code": ["in", item_codes], "disabled": 0}
	if filters.item_group:
		item_filters["item_group"] = filters.item_group
	items = (
		frappe.get_all(
			"Item",
			filters=item_filters,
			fields=[
				"item_code",
				"item_name",
				"item_group",
				"brand",
				"stock_uom",
			],
			limit_page_length=0,
		)
		if item_codes
		else []
	)
	item_map = {row.item_code: row for row in items}
	bins = [row for row in bins if row.item_code in item_map]

	reorder_rows = (
		frappe.get_all(
			"Item Reorder",
			filters={
				"parent": ["in", list(item_map)],
				"warehouse": ["in", warehouses],
			},
			fields=[
				"parent",
				"warehouse",
				"warehouse_reorder_level",
				"warehouse_reorder_qty",
			],
			limit_page_length=0,
			ignore_permissions=True,
		)
		if item_map
		else []
	)
	reorder_map = {
		(row.parent, row.warehouse): row
		for row in reorder_rows
	}
	sold_qty = _sold_quantities(
		filters,
		profile_names,
		list(item_map),
	)
	days = max(date_diff(filters.to_date, filters.from_date) + 1, 1)
	threshold = max(flt(filters.low_stock_threshold), 0)
	data = []
	for row in bins:
		item = item_map[row.item_code]
		reorder = reorder_map.get((row.item_code, row.warehouse))
		reorder_level = flt(
			reorder.warehouse_reorder_level if reorder else 0
		)
		effective_threshold = max(threshold, reorder_level)
		actual_qty = flt(row.actual_qty)
		period_sold_qty = flt(sold_qty.get(row.item_code))
		average_daily_sales = max(period_sold_qty, 0) / days
		if actual_qty < 0:
			status = "Negative Stock"
		elif actual_qty == 0:
			status = "Out of Stock"
		elif actual_qty <= effective_threshold:
			status = "Low Stock"
		else:
			status = "In Stock"
		if filters.stock_status and status != filters.stock_status:
			continue
		data.append(
			{
				"item_code": row.item_code,
				"item_name": item.item_name,
				"item_group": item.item_group,
				"brand": item.brand,
				"stock_uom": item.stock_uom,
				"warehouse": row.warehouse,
				"stock_status": status,
				"actual_qty": actual_qty,
				"projected_qty": flt(row.projected_qty),
				"reserved_qty": flt(row.reserved_qty),
				"ordered_qty": flt(row.ordered_qty),
				"sold_qty": period_sold_qty,
				"average_daily_sales": average_daily_sales,
				"stock_cover_days": (
					actual_qty / average_daily_sales
					if actual_qty > 0 and average_daily_sales > 0
					else None
				),
				"reorder_level": reorder_level,
				"reorder_qty": flt(
					reorder.warehouse_reorder_qty if reorder else 0
				),
				"company_currency": company_currency,
				"valuation_rate": flt(row.valuation_rate),
				"stock_value": actual_qty * flt(row.valuation_rate),
			}
		)
	severity = {
		"Negative Stock": 0,
		"Out of Stock": 1,
		"Low Stock": 2,
		"In Stock": 3,
	}
	data.sort(
		key=lambda row: (
			severity[row["stock_status"]],
			row["actual_qty"],
			row["item_code"],
			row["warehouse"],
		)
	)
	summary = [
		{
			"value": sum(
				1 for row in data
				if row["stock_status"] in ("Negative Stock", "Out of Stock", "Low Stock")
			),
			"indicator": "Orange",
			"label": _("Attention Required"),
			"datatype": "Int",
		},
		{
			"value": sum(1 for row in data if row["stock_status"] == "Out of Stock"),
			"indicator": "Red",
			"label": _("Out of Stock"),
			"datatype": "Int",
		},
		{
			"value": sum(flt(row["stock_value"]) for row in data),
			"indicator": "Blue",
			"label": _("Stock Value"),
			"datatype": "Currency",
			"currency": company_currency,
		},
	]
	return _columns(), data, None, _chart(data, company_currency), summary


def _sold_quantities(filters, profile_names, item_codes):
	if not profile_names or not item_codes:
		return {}
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={
			"company": filters.company,
			"docstatus": 1,
			"posting_date": ["between", [filters.from_date, filters.to_date]],
			"pos_profile": ["in", profile_names],
			"posa_pos_opening_shift": ["is", "set"],
		},
		fields=["name", "is_return"],
		limit_page_length=0,
	)
	invoice_map = {row.name: bool(row.is_return) for row in invoices}
	if not invoice_map:
		return {}
	rows = frappe.get_all(
		"Sales Invoice Item",
		filters={
			"parent": ["in", list(invoice_map)],
			"parenttype": "Sales Invoice",
			"item_code": ["in", item_codes],
		},
		fields=["parent", "item_code", "qty", "stock_qty"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	totals = defaultdict(float)
	for row in rows:
		qty = abs(flt(row.stock_qty or row.qty))
		totals[row.item_code] += -qty if invoice_map[row.parent] else qty
	return totals


def _validate_filters(filters):
	if not filters.company or not filters.from_date or not filters.to_date:
		frappe.throw(_("Company, Sales From and Sales To are required"))
	if filters.from_date > filters.to_date:
		frappe.throw(_("Sales From cannot be after Sales To"))


def _chart(data, company_currency):
	rows = data[:20]
	return {
		"data": {
			"labels": [f"{row['item_code']} · {row['warehouse']}" for row in rows],
			"datasets": [
				{
					"name": _("Stock Value ({0})").format(company_currency),
					"values": [flt(row["stock_value"]) for row in rows],
				}
			],
		},
		"type": "bar",
		"colors": ["#f2c037"],
	}


def _columns():
	return [
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 145},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "item_group", "label": _("Item Group"), "fieldtype": "Link", "options": "Item Group", "width": 135},
		{"fieldname": "brand", "label": _("Brand"), "fieldtype": "Link", "options": "Brand", "width": 110},
		{"fieldname": "warehouse", "label": _("Warehouse"), "fieldtype": "Link", "options": "Warehouse", "width": 155},
		{"fieldname": "stock_status", "label": _("Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "stock_uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 80},
		{"fieldname": "actual_qty", "label": _("Actual Qty"), "fieldtype": "Float", "width": 100},
		{"fieldname": "projected_qty", "label": _("Projected Qty"), "fieldtype": "Float", "width": 110},
		{"fieldname": "reserved_qty", "label": _("Reserved Qty"), "fieldtype": "Float", "width": 105},
		{"fieldname": "ordered_qty", "label": _("Ordered Qty"), "fieldtype": "Float", "width": 105},
		{"fieldname": "sold_qty", "label": _("Period Sold Qty"), "fieldtype": "Float", "width": 120},
		{"fieldname": "average_daily_sales", "label": _("Avg Daily Sales"), "fieldtype": "Float", "width": 115},
		{"fieldname": "stock_cover_days", "label": _("Stock Cover Days"), "fieldtype": "Float", "width": 125},
		{"fieldname": "reorder_level", "label": _("Reorder Level"), "fieldtype": "Float", "width": 110},
		{"fieldname": "reorder_qty", "label": _("Reorder Qty"), "fieldtype": "Float", "width": 100},
		{"fieldname": "company_currency", "label": _("Currency"), "fieldtype": "Link", "options": "Currency", "width": 90},
		{"fieldname": "valuation_rate", "label": _("Valuation Rate"), "fieldtype": "Currency", "options": "company_currency", "width": 120},
		{"fieldname": "stock_value", "label": _("Stock Value"), "fieldtype": "Currency", "options": "company_currency", "width": 125},
	]
