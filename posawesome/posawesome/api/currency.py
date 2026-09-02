"""Multi-currency context and tender validation for POS Awesome."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from erpnext.accounts.doctype.journal_entry.journal_entry import get_default_bank_cash_account
from erpnext.setup.utils import get_exchange_rate

from posawesome.posawesome.api.utils import check_pos_profile_access


def _codes(value):
	if not value:
		return []
	if isinstance(value, str):
		value = value.replace("\n", ",").split(",")
	return list(dict.fromkeys(str(code).strip().upper() for code in value if str(code).strip()))


def _rate(source, target, posting_date=None):
	"""Value in ``target`` of one unit of ``source``."""
	if not source or not target or source == target:
		return 1.0
	rate = flt(get_exchange_rate(source, target, getdate(posting_date or nowdate()), "for_selling"))
	if rate <= 0:
		frappe.throw(_("No exchange rate exists from {0} to {1}").format(source, target))
	return rate


def _payment_account(company, mode_of_payment):
	for account_type in ("Bank", "Cash"):
		account = get_default_bank_cash_account(
			company,
			account_type,
			mode_of_payment=mode_of_payment,
		)
		if account:
			return account
	return None


def build_currency_context(profile, invoice_currency=None, price_list=None, posting_date=None):
	"""Build the rates and payment-account currencies for one POS transaction."""
	if isinstance(profile, str):
		profile = frappe.get_cached_doc("POS Profile", profile)

	company_currency = frappe.get_cached_value("Company", profile.company, "default_currency")
	price_list = price_list or profile.selling_price_list
	price_list_currency = (
		frappe.get_cached_value("Price List", price_list, "currency")
		or profile.currency
		or company_currency
	)

	allowed = _codes(profile.get("posa_allowed_currencies"))
	for code in (profile.currency, company_currency, price_list_currency):
		if code and code not in allowed:
			allowed.append(code)

	payment_methods = []
	for row in profile.get("payments") or []:
		account = _payment_account(profile.company, row.mode_of_payment)
		account_currency = (
			account.get("account_currency") if account else None
		) or profile.currency
		if account_currency and account_currency not in allowed:
			allowed.append(account_currency)
		payment_methods.append(
			{
				**row.as_dict(),
				"account": account.get("account") if account else row.get("account"),
				"currency": account_currency,
			}
		)

	default_currency = (profile.currency or company_currency).upper()
	invoice_currency = (invoice_currency or default_currency).upper()
	if not profile.get("posa_enable_multi_currency"):
		if invoice_currency != default_currency:
			frappe.throw(
				_("Multi-currency is not enabled for POS Profile {0}").format(profile.name)
			)
		invoice_currency = default_currency
	elif (
		invoice_currency != default_currency
		and not profile.get("posa_allow_invoice_currency_selection")
	):
		frappe.throw(
			_("Invoice currency selection is not enabled for POS Profile {0}").format(
				profile.name
			)
		)
	elif invoice_currency not in allowed:
		frappe.throw(
			_("Currency {0} is not allowed on POS Profile {1}").format(
				invoice_currency, profile.name
			)
		)

	conversion_rate = _rate(invoice_currency, company_currency, posting_date)
	plc_conversion_rate = _rate(price_list_currency, company_currency, posting_date)

	for row in payment_methods:
		row["exchange_rate"] = _rate(row["currency"], company_currency, posting_date) / conversion_rate

	symbols = {
		code: frappe.get_cached_value("Currency", code, "symbol") or code
		for code in allowed
	}
	return {
		"invoice_currency": invoice_currency,
		"company_currency": company_currency,
		"price_list": price_list,
		"price_list_currency": price_list_currency,
		"conversion_rate": conversion_rate,
		"plc_conversion_rate": plc_conversion_rate,
		"item_rate_factor": plc_conversion_rate / conversion_rate,
		"allowed_currencies": allowed,
		"currency_symbols": symbols,
		"payment_methods": payment_methods,
		"allow_invoice_currency_selection": bool(
			profile.get("posa_enable_multi_currency")
			and profile.get("posa_allow_invoice_currency_selection")
		),
		"allow_mixed_currency_tender": bool(
			profile.get("posa_enable_multi_currency")
			and profile.get("posa_allow_mixed_currency_tender")
		),
	}


@frappe.whitelist()
def get_currency_context(pos_profile, invoice_currency=None, price_list=None, posting_date=None):
	check_pos_profile_access(pos_profile)
	return build_currency_context(
		pos_profile,
		invoice_currency=invoice_currency,
		price_list=price_list,
		posting_date=posting_date,
	)


def validate_tender_rows(doc):
	"""Validate captured tender amounts and exchange rates before submission."""
	profile = frappe.get_cached_doc("POS Profile", doc.pos_profile)
	context = build_currency_context(
		profile,
		invoice_currency=doc.currency,
		price_list=doc.selling_price_list,
		posting_date=doc.posting_date,
	)
	methods = {row["mode_of_payment"]: row for row in context["payment_methods"]}
	tolerance = max(flt(profile.get("posa_exchange_rate_tolerance")), 0) / 100
	used_currencies = set()

	for label, captured, expected in (
		(_("invoice"), flt(doc.conversion_rate), flt(context["conversion_rate"])),
		(
			_("price list"),
			flt(doc.plc_conversion_rate),
			flt(context["plc_conversion_rate"]),
		),
	):
		if captured <= 0:
			frappe.throw(_("{0} conversion rate must be greater than zero").format(label))
		if expected and abs(captured - expected) / expected > tolerance:
			frappe.throw(
				_("{0} conversion rate is outside the allowed tolerance").format(
					label.capitalize()
				)
			)

	for payment in doc.get("payments") or []:
		method = methods.get(payment.mode_of_payment)
		if not method:
			frappe.throw(
				_("Mode of Payment {0} is not configured for this POS Profile").format(
					payment.mode_of_payment
				)
			)

		tender_currency = payment.get("posa_tender_currency") or doc.currency
		tender_amount = flt(payment.get("posa_tender_amount") or payment.amount)
		captured_rate = flt(payment.get("posa_exchange_rate") or 1)
		expected_rate = flt(method.get("exchange_rate") or 1)

		if tender_currency != method.get("currency"):
			frappe.throw(
				_("{0} must be tendered in {1}, not {2}").format(
					payment.mode_of_payment, method.get("currency"), tender_currency
				)
			)
		if not context["allow_mixed_currency_tender"] and tender_currency != doc.currency:
			frappe.throw(_("Mixed-currency tender is not enabled for this POS Profile"))
		if captured_rate <= 0:
			frappe.throw(_("Exchange rate must be greater than zero"))
		if expected_rate and abs(captured_rate - expected_rate) / expected_rate > tolerance:
			frappe.throw(
				_("Exchange rate for {0} is outside the allowed tolerance").format(
					tender_currency
				)
			)

		expected_amount = tender_amount * captured_rate
		precision = frappe.get_precision("Sales Invoice Payment", "amount") or 2
		if abs(abs(flt(payment.amount)) - abs(expected_amount)) > 0.5 / (10**precision):
			frappe.throw(
				_("Converted amount for {0} does not match its tender amount").format(
					payment.mode_of_payment
				)
			)
		used_currencies.add(tender_currency)

	if len(used_currencies) > 1 and not context["allow_mixed_currency_tender"]:
		frappe.throw(_("Mixed-currency tender is not enabled for this POS Profile"))

	return context
