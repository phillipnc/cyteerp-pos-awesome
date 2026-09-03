"""Install / migrate hooks.

Custom fields that predate v16 ship as fixtures. Anything introduced for v16 is
created here instead, so an existing site picks it up on `bench migrate` without
needing the fixture file to be re-imported.
"""

from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

V16_CUSTOM_FIELDS = {
	"Sales Invoice": [
		{
			"fieldname": "posa_offline_uuid",
			"label": "POS Offline Sync ID",
			"fieldtype": "Data",
			"insert_after": "posa_pos_opening_shift",
			"read_only": 1,
			"hidden": 1,
			"no_copy": 1,
			"unique": 1,
			"search_index": 1,
			"print_hide": 1,
			"description": (
				"Client-generated id for an invoice captured offline. Enforces "
				"exactly-once sync when a terminal replays its queue."
			),
		},
		{
			"fieldname": "posa_fiscal_section",
			"label": "Zimbabwe Fiscalisation",
			"fieldtype": "Section Break",
			"insert_after": "posa_offline_uuid",
			"collapsible": 1,
			"collapsible_depends_on": "eval:doc.posa_fiscal_status",
		},
		{
			"fieldname": "posa_fiscal_status",
			"label": "Fiscal Status",
			"fieldtype": "Select",
			"options": "\nPending\nAccepted\nFailed\nNot Required",
			"insert_after": "posa_fiscal_section",
			"read_only": 1,
			"allow_on_submit": 1,
		},
		{
			"fieldname": "posa_fiscal_receipt_id",
			"label": "FDMS Receipt ID",
			"fieldtype": "Data",
			"insert_after": "posa_fiscal_status",
			"read_only": 1,
			"allow_on_submit": 1,
		},
		{
			"fieldname": "posa_fiscal_device_id",
			"label": "Fiscal Device ID",
			"fieldtype": "Int",
			"insert_after": "posa_fiscal_receipt_id",
			"read_only": 1,
			"allow_on_submit": 1,
		},
		{
			"fieldname": "posa_fiscal_day_no",
			"label": "Fiscal Day No",
			"fieldtype": "Int",
			"insert_after": "posa_fiscal_device_id",
			"read_only": 1,
			"allow_on_submit": 1,
		},
		{
			"fieldname": "posa_fiscal_receipt_global_no",
			"label": "Fiscal Receipt Global No",
			"fieldtype": "Int",
			"insert_after": "posa_fiscal_day_no",
			"read_only": 1,
			"allow_on_submit": 1,
		},
		{
			"fieldname": "posa_fiscal_column_break",
			"fieldtype": "Column Break",
			"insert_after": "posa_fiscal_receipt_global_no",
		},
		{
			"fieldname": "posa_fiscal_qr_url",
			"label": "Fiscal QR URL",
			"fieldtype": "Small Text",
			"insert_after": "posa_fiscal_column_break",
			"read_only": 1,
			"allow_on_submit": 1,
		},
		{
			"fieldname": "posa_fiscal_verification_code",
			"label": "Fiscal Verification Code",
			"fieldtype": "Data",
			"insert_after": "posa_fiscal_qr_url",
			"read_only": 1,
			"allow_on_submit": 1,
		},
		{
			"fieldname": "posa_fiscal_receipt_hash",
			"label": "Fiscal Receipt Hash",
			"fieldtype": "Small Text",
			"insert_after": "posa_fiscal_verification_code",
			"read_only": 1,
			"allow_on_submit": 1,
			"hidden": 1,
		},
		{
			"fieldname": "posa_fiscal_server_signature",
			"label": "Fiscal Server Signature",
			"fieldtype": "Long Text",
			"insert_after": "posa_fiscal_receipt_hash",
			"read_only": 1,
			"allow_on_submit": 1,
			"hidden": 1,
		},
		{
			"fieldname": "posa_fiscal_error",
			"label": "Fiscalisation Error",
			"fieldtype": "Small Text",
			"insert_after": "posa_fiscal_server_signature",
			"read_only": 1,
			"allow_on_submit": 1,
		},
	],
	"POS Profile": [
		{
			"fieldname": "posa_offline_section",
			"label": "Offline Mode",
			"fieldtype": "Section Break",
			"insert_after": "posa_server_cache_duration",
			"collapsible": 1,
		},
		{
			"fieldname": "posa_allow_offline_mode",
			"label": "Allow Offline Mode",
			"fieldtype": "Check",
			"insert_after": "posa_offline_section",
			"default": "0",
			"description": (
				"Cache the catalog on the terminal and keep taking sales while the "
				"network is down. Queued invoices sync when the connection returns."
			),
		},
		{
			"fieldname": "posa_offline_cache_ttl",
			"label": "Offline Cache Refresh (minutes)",
			"fieldtype": "Int",
			"insert_after": "posa_allow_offline_mode",
			"default": "60",
			"depends_on": "eval:doc.posa_allow_offline_mode",
		},
		{
			"fieldname": "posa_offline_column_break",
			"fieldtype": "Column Break",
			"insert_after": "posa_offline_cache_ttl",
		},
		{
			"fieldname": "posa_offline_max_queue",
			"label": "Max Queued Invoices",
			"fieldtype": "Int",
			"insert_after": "posa_offline_column_break",
			"default": "200",
			"depends_on": "eval:doc.posa_allow_offline_mode",
			"description": "Stop accepting offline sales once this many invoices are waiting to sync.",
		},
		{
			"fieldname": "posa_currency_section",
			"label": "Multi-Currency",
			"fieldtype": "Section Break",
			"insert_after": "posa_offline_max_queue",
			"collapsible": 1,
		},
		{
			"fieldname": "posa_enable_multi_currency",
			"label": "Enable Multi-Currency",
			"fieldtype": "Check",
			"insert_after": "posa_currency_section",
			"default": "0",
		},
		{
			"fieldname": "posa_allow_invoice_currency_selection",
			"label": "Allow Invoice Currency Selection",
			"fieldtype": "Check",
			"insert_after": "posa_enable_multi_currency",
			"default": "0",
			"depends_on": "eval:doc.posa_enable_multi_currency",
		},
		{
			"fieldname": "posa_allow_mixed_currency_tender",
			"label": "Allow Mixed-Currency Tender",
			"fieldtype": "Check",
			"insert_after": "posa_allow_invoice_currency_selection",
			"default": "0",
			"depends_on": "eval:doc.posa_enable_multi_currency",
		},
		{
			"fieldname": "posa_allowed_currencies",
			"label": "Allowed Currencies",
			"fieldtype": "Small Text",
			"insert_after": "posa_allow_mixed_currency_tender",
			"depends_on": "eval:doc.posa_enable_multi_currency",
			"description": "Comma-separated ISO currency codes, for example USD,ZWG,ZAR.",
		},
		{
			"fieldname": "posa_currency_column_break",
			"fieldtype": "Column Break",
			"insert_after": "posa_allowed_currencies",
		},
		{
			"fieldname": "posa_exchange_rate_tolerance",
			"label": "Manual Rate Tolerance (%)",
			"fieldtype": "Percent",
			"insert_after": "posa_currency_column_break",
			"default": "5",
			"depends_on": "eval:doc.posa_enable_multi_currency",
		},
	],
	"Sales Invoice Payment": [
		{
			"fieldname": "posa_tender_currency",
			"label": "Tender Currency",
			"fieldtype": "Link",
			"options": "Currency",
			"insert_after": "amount",
			"read_only": 1,
		},
		{
			"fieldname": "posa_tender_amount",
			"label": "Tender Amount",
			"fieldtype": "Currency",
			"options": "posa_tender_currency",
			"insert_after": "posa_tender_currency",
			"read_only": 1,
		},
		{
			"fieldname": "posa_exchange_rate",
			"label": "Tender Exchange Rate",
			"fieldtype": "Float",
			"precision": "9",
			"insert_after": "posa_tender_amount",
			"read_only": 1,
			"description": "Invoice-currency value of one unit of tender currency.",
		},
	],
	"Mpesa C2B Register URL": [
		{
			"fieldname": "posa_callback_secret",
			"label": "Callback Secret",
			"fieldtype": "Password",
			"insert_after": "register_status",
			"read_only": 1,
			"hidden": 1,
			"no_copy": 1,
			"description": "Random secret included in registered callback URLs to reject forged callbacks.",
		},
	],
	"Item": [
		{
			"fieldname": "posa_hs_code",
			"label": "Zimbabwe HS Code",
			"fieldtype": "Data",
			"insert_after": "gst_hsn_code",
			"length": 8,
			"description": "Four- or eight-digit FDMS-compatible Harmonized System code.",
		},
	],
	"Company": [
		{
			"fieldname": "posa_zimra_tin",
			"label": "ZIMRA TIN",
			"fieldtype": "Data",
			"insert_after": "tax_id",
			"length": 10,
		},
		{
			"fieldname": "posa_zimra_vat_number",
			"label": "ZIMRA VAT Number",
			"fieldtype": "Data",
			"insert_after": "posa_zimra_tin",
			"length": 9,
		},
	],
	"Customer": [
		{
			"fieldname": "posa_zimra_tin",
			"label": "ZIMRA TIN",
			"fieldtype": "Data",
			"insert_after": "tax_id",
			"length": 10,
		},
		{
			"fieldname": "posa_zimra_vat_number",
			"label": "ZIMRA VAT Number",
			"fieldtype": "Data",
			"insert_after": "posa_zimra_tin",
			"length": 9,
		},
	],
}


def after_install():
	create_custom_fields(V16_CUSTOM_FIELDS, ignore_validate=True)
	_backfill_reporting_fields()
	_add_database_constraints()
	_sync_pos_print_format()
	frappe.db.commit()


def after_migrate():
	create_custom_fields(V16_CUSTOM_FIELDS, ignore_validate=True)
	_backfill_reporting_fields()
	_add_database_constraints()
	_sync_pos_print_format()
	frappe.db.commit()


def _add_database_constraints():
	"""Indexes that enforce idempotency even under concurrent callbacks."""
	# Frappe's v16 MariaDB and Postgres implementations both make add_unique
	# idempotent. If legacy duplicate IDs exist, migration stops instead of silently
	# leaving callback replay protection disabled.
	frappe.db.add_unique("Mpesa Payment Register", ["transid"], "uniq_mpesa_transid")


def _backfill_reporting_fields():
	"""Preserve legacy single-currency shift rows after adding currency metadata."""
	for row in frappe.get_all(
		"POS Opening Shift Detail",
		fields=[
			"name",
			"parent",
			"currency",
			"amount",
			"company_exchange_rate",
			"company_amount",
		],
		limit_page_length=0,
		ignore_permissions=True,
	):
		if row.currency and row.company_exchange_rate and row.company_amount is not None:
			continue
		company = frappe.get_cached_value("POS Opening Shift", row.parent, "company")
		currency = frappe.get_cached_value("Company", company, "default_currency")
		frappe.db.set_value(
			"POS Opening Shift Detail",
			row.name,
			{
				"currency": row.currency or currency,
				"company_exchange_rate": row.company_exchange_rate or 1,
				"company_amount": (
					row.company_amount
					if row.company_amount is not None
					else row.amount or 0
				),
			},
			update_modified=False,
		)

	for row in frappe.get_all(
		"POS Closing Shift Detail",
		fields=[
			"name",
			"parent",
			"currency",
			"opening_amount",
			"closing_amount",
			"expected_amount",
			"difference",
			"company_exchange_rate",
			"company_opening_amount",
			"company_closing_amount",
			"company_expected_amount",
			"company_difference",
		],
		limit_page_length=0,
		ignore_permissions=True,
	):
		if row.currency and row.company_exchange_rate:
			continue
		company = frappe.get_cached_value("POS Closing Shift", row.parent, "company")
		currency = frappe.get_cached_value("Company", company, "default_currency")
		frappe.db.set_value(
			"POS Closing Shift Detail",
			row.name,
			{
				"currency": row.currency or currency,
				"company_exchange_rate": row.company_exchange_rate or 1,
				"company_opening_amount": row.opening_amount or 0,
				"company_closing_amount": row.closing_amount or 0,
				"company_expected_amount": row.expected_amount or 0,
				"company_difference": row.difference or 0,
			},
			update_modified=False,
		)

	for row in frappe.get_all(
		"Sales Invoice Reference",
		fields=["name", "sales_invoice", "currency", "grand_total", "base_grand_total"],
		limit_page_length=0,
		ignore_permissions=True,
	):
		if row.currency and row.base_grand_total is not None:
			continue
		invoice = frappe.get_cached_value(
			"Sales Invoice",
			row.sales_invoice,
			["currency", "grand_total", "base_grand_total"],
			as_dict=True,
		)
		if invoice:
			frappe.db.set_value(
				"Sales Invoice Reference",
				row.name,
				{
					"currency": row.currency or invoice.currency,
					"grand_total": row.grand_total or invoice.grand_total,
					"base_grand_total": (
						row.base_grand_total
						if row.base_grand_total is not None
						else invoice.base_grand_total
					),
				},
				update_modified=False,
			)

	for row in frappe.get_all(
		"POS Payment Entry Reference",
		fields=["name", "payment_entry", "currency", "paid_amount", "base_paid_amount"],
		limit_page_length=0,
		ignore_permissions=True,
	):
		if row.currency and row.base_paid_amount is not None:
			continue
		payment = frappe.get_cached_value(
			"Payment Entry",
			row.payment_entry,
			["paid_to_account_currency", "received_amount", "base_received_amount"],
			as_dict=True,
		)
		if payment:
			frappe.db.set_value(
				"POS Payment Entry Reference",
				row.name,
				{
					"currency": row.currency or payment.paid_to_account_currency,
					"paid_amount": row.paid_amount or payment.received_amount,
					"base_paid_amount": (
						row.base_paid_amount
						if row.base_paid_amount is not None
						else payment.base_received_amount
					),
				},
				update_modified=False,
			)


def _sync_pos_print_format():
	"""Keep the database print format aligned with its readable HTML source."""
	if not frappe.db.exists("Print Format", "POS Print Format"):
		return
	path = Path(
		frappe.get_app_path(
			"posawesome",
			"posawesome",
			"print_format",
			"pos_print_format",
			"pos_print_format.html",
		)
	)
	if path.is_file():
		frappe.db.set_value(
			"Print Format",
			"POS Print Format",
			"html",
			path.read_text(encoding="utf-8"),
			update_modified=False,
		)
