"""Fiscal receipt acceptance, failures and sequence visibility."""

from collections import Counter

import frappe
from frappe import _
from frappe.utils import flt


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
	if filters.fiscal_status:
		invoice_filters["posa_fiscal_status"] = filters.fiscal_status
	if filters.pos_profile:
		invoice_filters["pos_profile"] = filters.pos_profile
	if filters.currency:
		invoice_filters["currency"] = filters.currency
	if filters.device_id:
		invoice_filters["posa_fiscal_device_id"] = filters.device_id

	rows = frappe.get_all(
		"Sales Invoice",
		filters=invoice_filters,
		fields=[
			"name",
			"posting_date",
			"posting_time",
			"customer",
			"is_return",
			"return_against",
			"currency",
			"grand_total",
			"base_grand_total",
			"pos_profile",
			"posa_pos_opening_shift",
			"posa_fiscal_status",
			"posa_fiscal_device_id",
			"posa_fiscal_day_no",
			"posa_fiscal_receipt_id",
			"posa_fiscal_receipt_global_no",
			"posa_fiscal_verification_code",
			"posa_fiscal_qr_url",
			"posa_fiscal_error",
		],
		order_by="posting_date desc, posting_time desc, name desc",
		limit_page_length=0,
	)
	data = []
	for row in rows:
		data.append(
			{
				**row,
				"receipt_type": "Credit Note" if row.is_return else "Fiscal Invoice",
				"company_currency": company_currency,
				"fiscal_status": row.posa_fiscal_status or "Unprocessed",
			}
		)

	counts = Counter(row["fiscal_status"] for row in data)
	chart = {
		"data": {
			"labels": list(counts),
			"datasets": [{"name": _("Receipts"), "values": list(counts.values())}],
		},
		"type": "donut",
		"colors": ["#21ba45", "#f2c037", "#c10015", "#607d8b"],
	}
	summary = [
		{
			"value": counts.get(status, 0),
			"indicator": indicator,
			"label": _(status),
			"datatype": "Int",
		}
		for status, indicator in (
			("Accepted", "Green"),
			("Pending", "Orange"),
			("Failed", "Red"),
			("Unprocessed", "Gray"),
		)
	]
	summary.append(
		{
			"value": sum(abs(flt(row.base_grand_total)) for row in rows),
			"indicator": "Blue",
			"label": _("Company Value"),
			"datatype": "Currency",
			"currency": company_currency,
		}
	)
	return _columns(), data, None, chart, summary


def _validate_filters(filters):
	if not filters.company or not filters.from_date or not filters.to_date:
		frappe.throw(_("Company, From Date and To Date are required"))
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))


def _columns():
	return [
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "posting_time", "label": _("Time"), "fieldtype": "Time", "width": 90},
		{"fieldname": "name", "label": _("Sales Invoice"), "fieldtype": "Link", "options": "Sales Invoice", "width": 170},
		{"fieldname": "receipt_type", "label": _("Receipt Type"), "fieldtype": "Data", "width": 115},
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link", "options": "Customer", "width": 160},
		{"fieldname": "currency", "label": _("Currency"), "fieldtype": "Link", "options": "Currency", "width": 90},
		{"fieldname": "grand_total", "label": _("Invoice Total"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "company_currency", "label": _("Company Currency"), "fieldtype": "Link", "options": "Currency", "width": 120},
		{"fieldname": "base_grand_total", "label": _("Company Total"), "fieldtype": "Currency", "options": "company_currency", "width": 130},
		{"fieldname": "fiscal_status", "label": _("Fiscal Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "posa_fiscal_device_id", "label": _("Device ID"), "fieldtype": "Int", "width": 90},
		{"fieldname": "posa_fiscal_day_no", "label": _("Fiscal Day"), "fieldtype": "Int", "width": 90},
		{"fieldname": "posa_fiscal_receipt_global_no", "label": _("Global No"), "fieldtype": "Int", "width": 100},
		{"fieldname": "posa_fiscal_receipt_id", "label": _("Receipt ID"), "fieldtype": "Data", "width": 120},
		{"fieldname": "posa_fiscal_verification_code", "label": _("Verification Code"), "fieldtype": "Data", "width": 150},
		{"fieldname": "return_against", "label": _("Return Against"), "fieldtype": "Link", "options": "Sales Invoice", "width": 150},
		{"fieldname": "pos_profile", "label": _("POS Profile"), "fieldtype": "Link", "options": "POS Profile", "width": 140},
		{"fieldname": "posa_pos_opening_shift", "label": _("Opening Shift"), "fieldtype": "Link", "options": "POS Opening Shift", "width": 150},
		{"fieldname": "posa_fiscal_error", "label": _("Fiscal Error"), "fieldtype": "Small Text", "width": 260},
	]
