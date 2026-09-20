"""ZIMRA-oriented fiscal-day totals using the same tax mapping as receipts."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from posawesome.posawesome.api.zimbabwe_fiscal import _tax_id, _tax_percent


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
	if filters.device_id:
		invoice_filters["posa_fiscal_device_id"] = filters.device_id
	if filters.fiscal_day_no:
		invoice_filters["posa_fiscal_day_no"] = filters.fiscal_day_no
	if filters.currency:
		invoice_filters["currency"] = filters.currency
	if filters.fiscal_status:
		invoice_filters["posa_fiscal_status"] = filters.fiscal_status

	invoice_rows = frappe.get_all(
		"Sales Invoice",
		filters=invoice_filters,
		fields=["name", "posa_fiscal_device_id"],
		limit_page_length=0,
	)
	devices = {
		int(row.device_id): frappe.get_doc("Zimbabwe Fiscal Device", row.name)
		for row in frappe.get_all(
			"Zimbabwe Fiscal Device",
			filters={"company": filters.company},
			fields=["name", "device_id"],
			limit_page_length=0,
		)
	}
	groups = defaultdict(
		lambda: {
			"receipt_count": 0,
			"sales_with_tax": 0.0,
			"tax_amount": 0.0,
			"company_sales_with_tax": 0.0,
			"company_tax_amount": 0.0,
		}
	)
	seen_receipts = set()

	for row in invoice_rows:
		doc = frappe.get_doc("Sales Invoice", row.name)
		device = devices.get(int(doc.posa_fiscal_device_id or 0))
		if not device:
			continue
		sign = -1 if doc.is_return else 1
		tax_inclusive = bool(
			frappe.get_cached_value("POS Profile", doc.pos_profile, "posa_tax_inclusive")
		)
		for item in doc.get("items") or []:
			percent = flt(_tax_percent(doc, item))
			tax_id = _tax_id(device, percent)
			line_total = sign * abs(flt(item.amount))
			if tax_inclusive:
				tax_amount = line_total * percent / (100 + percent) if percent else 0
				sales_with_tax = line_total
			else:
				tax_amount = line_total * percent / 100
				sales_with_tax = line_total + tax_amount
			receipt_type = "Credit Note" if doc.is_return else "Fiscal Invoice"
			key = (
				int(doc.posa_fiscal_device_id or 0),
				int(doc.posa_fiscal_day_no or 0),
				doc.currency,
				receipt_type,
				int(tax_id),
				percent,
			)
			group = groups[key]
			group["sales_with_tax"] += sales_with_tax
			group["tax_amount"] += tax_amount
			group["company_sales_with_tax"] += sales_with_tax * flt(doc.conversion_rate or 1)
			group["company_tax_amount"] += tax_amount * flt(doc.conversion_rate or 1)
			receipt_key = (doc.name, key)
			if receipt_key not in seen_receipts:
				group["receipt_count"] += 1
				seen_receipts.add(receipt_key)

	data = [
		{
			"device_id": key[0],
			"fiscal_day_no": key[1],
			"currency": key[2],
			"receipt_type": key[3],
			"tax_id": key[4],
			"tax_percent": key[5],
			"company_currency": company_currency,
			"data_source": _("Accepted receipt reconstruction"),
			**values,
		}
		for key, values in sorted(groups.items())
	]
	chart = {
		"data": {
			"labels": [
				f"{row['device_id']}/{row['fiscal_day_no']} · {row['currency']} · Tax {row['tax_id']}"
				for row in data
			],
			"datasets": [
				{
					"name": _("Sales with Tax ({0})").format(company_currency),
					"values": [row["company_sales_with_tax"] for row in data],
				}
			],
		},
		"type": "bar",
		"colors": ["#21ba45"],
	}
	summary = [
		{
			"value": sum(row["company_sales_with_tax"] for row in data),
			"indicator": "Green",
			"label": _("Reconstructed Fiscal Sales"),
			"datatype": "Currency",
			"currency": company_currency,
		},
		{
			"value": sum(row["company_tax_amount"] for row in data),
			"indicator": "Blue",
			"label": _("Reconstructed Fiscal Tax"),
			"datatype": "Currency",
			"currency": company_currency,
		},
	]
	message = _(
		"This report reconstructs totals from submitted Sales Invoices. "
		"It is not an authoritative ZIMRA fiscal-day close result; reconcile it "
		"with the provider/device day-close response before statutory use."
	)
	return _columns(), data, message, chart, summary


def _validate_filters(filters):
	if not filters.company or not filters.from_date or not filters.to_date:
		frappe.throw(_("Company, From Date and To Date are required"))
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))


def _columns():
	return [
		{"fieldname": "device_id", "label": _("Device ID"), "fieldtype": "Int", "width": 90},
		{"fieldname": "fiscal_day_no", "label": _("Fiscal Day"), "fieldtype": "Int", "width": 90},
		{"fieldname": "currency", "label": _("Receipt Currency"), "fieldtype": "Link", "options": "Currency", "width": 120},
		{"fieldname": "receipt_type", "label": _("Receipt Type"), "fieldtype": "Data", "width": 120},
		{"fieldname": "tax_id", "label": _("Tax ID"), "fieldtype": "Int", "width": 80},
		{"fieldname": "tax_percent", "label": _("Tax %"), "fieldtype": "Percent", "width": 90},
		{"fieldname": "receipt_count", "label": _("Receipts"), "fieldtype": "Int", "width": 90},
		{"fieldname": "sales_with_tax", "label": _("Sales with Tax"), "fieldtype": "Currency", "options": "currency", "width": 140},
		{"fieldname": "tax_amount", "label": _("Tax Amount"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "company_currency", "label": _("Company Currency"), "fieldtype": "Link", "options": "Currency", "width": 120},
		{"fieldname": "company_sales_with_tax", "label": _("Company Sales with Tax"), "fieldtype": "Currency", "options": "company_currency", "width": 170},
		{"fieldname": "company_tax_amount", "label": _("Company Tax"), "fieldtype": "Currency", "options": "company_currency", "width": 135},
		{"fieldname": "data_source", "label": _("Data Source"), "fieldtype": "Data", "width": 210},
	]
