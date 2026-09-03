"""Physical tender movements separated by currency and Mode of Payment."""

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
	shift_filters = {
		"company": filters.company,
		"docstatus": 1,
		"posting_date": ["between", [filters.from_date, filters.to_date]],
	}
	if filters.pos_profile:
		shift_filters["pos_profile"] = filters.pos_profile
	if filters.opening_shift:
		shift_filters["name"] = filters.opening_shift

	shifts = frappe.get_all(
		"POS Opening Shift",
		filters=shift_filters,
		fields=["name", "pos_profile"],
		limit_page_length=0,
	)
	shift_names = [row.name for row in shifts]
	if not shift_names:
		return _columns(), [], None, _chart([], company_currency), []

	invoices = frappe.get_all(
		"Sales Invoice",
		filters={
			"company": filters.company,
			"docstatus": 1,
			"posa_pos_opening_shift": ["in", shift_names],
		},
		fields=[
			"name",
			"posa_pos_opening_shift",
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
	payments = (
		frappe.get_all(
			"Sales Invoice Payment",
			filters={"parent": ["in", invoice_names], "parenttype": "Sales Invoice"},
			fields=[
				"parent",
				"mode_of_payment",
				"amount",
				"base_amount",
				"posa_tender_currency",
				"posa_tender_amount",
				"posa_exchange_rate",
			],
			limit_page_length=0,
			ignore_permissions=True,
		)
		if invoice_names
		else []
	)
	opening_balances = frappe.get_all(
		"POS Opening Shift Detail",
		filters={"parent": ["in", shift_names], "parenttype": "POS Opening Shift"},
		fields=[
			"parent",
			"mode_of_payment",
			"currency",
			"amount",
			"company_exchange_rate",
			"company_amount",
		],
		limit_page_length=0,
		ignore_permissions=True,
	)
	payment_entries = frappe.get_all(
		"Payment Entry",
		filters={
			"company": filters.company,
			"docstatus": 1,
			"payment_type": "Receive",
			"reference_no": ["in", shift_names],
		},
		fields=[
			"name",
			"mode_of_payment",
			"paid_amount",
			"received_amount",
			"base_received_amount",
			"paid_to_account_currency",
		],
		limit_page_length=0,
	)
	cash_modes = {
		row.name: (
			frappe.get_cached_value("POS Profile", row.pos_profile, "posa_cash_mode_of_payment")
			or "Cash"
		)
		for row in shifts
	}
	cash_mode = next(iter(set(cash_modes.values())), "Cash")
	result = aggregate_shift(
		invoices,
		payments,
		[],
		company_currency=company_currency,
		cash_mode=cash_mode,
		cash_mode_by_shift=cash_modes,
		payment_entries=payment_entries,
		opening_balances=opening_balances,
	)
	data = []
	for row in result["payment_mix"]:
		if filters.mode_of_payment and row["mode_of_payment"] != filters.mode_of_payment:
			continue
		if filters.currency and row["currency"] != filters.currency:
			continue
		data.append({**row, "company_currency": company_currency})

	summary = [
		{
			"value": sum(flt(row["company_transaction_amount"]) for row in data),
			"indicator": "Blue",
			"label": _("Tender Movement"),
			"datatype": "Currency",
			"currency": company_currency,
		},
		{
			"value": sum(flt(row["company_expected_amount"]) for row in data),
			"indicator": "Green",
			"label": _("Expected Drawer/Accounts"),
			"datatype": "Currency",
			"currency": company_currency,
		},
	]
	return _columns(), data, None, _chart(data, company_currency), summary


def _validate_filters(filters):
	if not filters.company or not filters.from_date or not filters.to_date:
		frappe.throw(_("Company, From Date and To Date are required"))
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))


def _chart(data, company_currency):
	return {
		"data": {
			"labels": [
				f"{row['mode_of_payment']} · {row['currency']}"
				for row in data
			],
			"datasets": [
				{
					"name": _("Movement ({0})").format(company_currency),
					"values": [
						flt(row["company_transaction_amount"])
						for row in data
					],
				}
			],
		},
		"type": "bar",
		"colors": ["#7b61ff"],
	}


def _columns():
	return [
		{"fieldname": "mode_of_payment", "label": _("Mode of Payment"), "fieldtype": "Link", "options": "Mode of Payment", "width": 160},
		{"fieldname": "currency", "label": _("Tender Currency"), "fieldtype": "Link", "options": "Currency", "width": 120},
		{"fieldname": "opening_amount", "label": _("Opening Float"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "transaction_amount", "label": _("Tender Movement"), "fieldtype": "Currency", "options": "currency", "width": 145},
		{"fieldname": "expected_amount", "label": _("Expected Amount"), "fieldtype": "Currency", "options": "currency", "width": 145},
		{"fieldname": "company_currency", "label": _("Company Currency"), "fieldtype": "Link", "options": "Currency", "width": 125},
		{"fieldname": "company_opening_amount", "label": _("Company Opening"), "fieldtype": "Currency", "options": "company_currency", "width": 145},
		{"fieldname": "company_transaction_amount", "label": _("Company Movement"), "fieldtype": "Currency", "options": "company_currency", "width": 155},
		{"fieldname": "company_expected_amount", "label": _("Company Expected"), "fieldtype": "Currency", "options": "company_currency", "width": 150},
	]
