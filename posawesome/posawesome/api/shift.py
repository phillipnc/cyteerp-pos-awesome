"""POS shift lifecycle: opening, closing, and live shift analytics."""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate

from posawesome.posawesome.api.currency import _rate, build_currency_context
from posawesome.posawesome.api.reporting import aggregate_shift
from posawesome.posawesome.api.utils import (
	as_dict,
	as_list,
	check_pos_profile_access,
	precision_settings,
	validate_shift_access,
)

# Wrapped rather than re-exported: the implementations live on the doctype, where
# the desk form also reaches them, but they were written for the desk form's
# argument shapes (a JSON string of a whole document). The SPA sends a docname and
# a plain object, so normalise here instead of forking the builders.
from posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift import (
	make_closing_shift_from_opening as _build_closing_shift,
)
from posawesome.posawesome.doctype.pos_closing_shift.pos_closing_shift import (
	submit_closing_shift as _submit_closing_shift,
)


def _resolve_opening_shift(value) -> dict:
	"""Accept a docname, a JSON string, or an already-parsed document."""
	if isinstance(value, str) and not value.strip().startswith("{"):
		return frappe.get_doc("POS Opening Shift", value).as_dict()

	payload = as_dict(value)
	# The builder needs balance_details; a partial payload has to be reloaded.
	if not payload.get("balance_details") and payload.get("name"):
		return frappe.get_doc("POS Opening Shift", payload["name"]).as_dict()
	return payload


@frappe.whitelist()
def make_closing_shift_from_opening(opening_shift):
	"""Build — but do not save — the closing shift for an open shift."""
	payload = _resolve_opening_shift(opening_shift)
	if not payload.get("name"):
		frappe.throw(_("An opening shift is required to build a closing shift."))
	validate_shift_access(payload["name"])
	return _build_closing_shift(json.dumps(payload, default=str))


@frappe.whitelist()
def submit_closing_shift(closing_shift):
	"""Save and submit a closing shift built by the call above."""
	payload = as_dict(closing_shift)
	if not payload.get("pos_opening_shift"):
		frappe.throw(_("The closing shift is not linked to an opening shift."))
	validate_shift_access(payload["pos_opening_shift"])
	return _submit_closing_shift(json.dumps(payload, default=str))


@frappe.whitelist()
def get_opening_dialog_data():
	"""Companies, profiles and payment methods the current user may open a shift on."""
	user = frappe.session.user
	is_manager = "System Manager" in frappe.get_roles(user)

	profiles = frappe.get_all(
		"POS Profile",
		filters={"disabled": 0},
		fields=["name", "company", "currency", "warehouse"],
		order_by="name",
		limit_page_length=0,
	)

	if not is_manager:
		# Restrict to profiles the user is listed on, plus profiles with no user list.
		assigned = {
			row.parent
			for row in frappe.get_all(
				"POS Profile User",
				filters={"user": user, "parent": ["in", [p.name for p in profiles]]},
				fields=["parent"],
				ignore_permissions=True,
			)
		}
		restricted = {
			row.parent
			for row in frappe.get_all(
				"POS Profile User",
				filters={"parent": ["in", [p.name for p in profiles]]},
				fields=["parent"],
				ignore_permissions=True,
			)
		}
		profiles = [p for p in profiles if p.name in assigned or p.name not in restricted]

	profile_names = [p.name for p in profiles]
	payments = (
		frappe.get_all(
			"POS Payment Method",
			filters={"parent": ["in", profile_names]},
			fields=["*"],
			order_by="parent, idx",
			limit_page_length=0,
			ignore_permissions=True,
		)
		if profile_names
		else []
	)

	context_by_profile = {
		profile.name: build_currency_context(profile.name)
		for profile in profiles
	}
	for mode in payments:
		context = context_by_profile.get(mode["parent"]) or {}
		configured = next(
			(
				row
				for row in context.get("payment_methods") or []
				if row.get("mode_of_payment") == mode.mode_of_payment
			),
			{},
		)
		mode["currency"] = configured.get("currency") or context.get("invoice_currency")
		mode["company_exchange_rate"] = _rate(
			mode["currency"],
			context.get("company_currency"),
		)

	companies = sorted({p.company for p in profiles})

	return {
		"companies": [{"name": name} for name in companies],
		"pos_profiles_data": profiles,
		"payments_method": payments,
	}


@frappe.whitelist()
def create_opening_voucher(pos_profile, company, balance_details):
	"""Open a shift for the current user."""
	check_pos_profile_access(pos_profile)
	balance_details = as_list(balance_details)
	profile = frappe.get_cached_doc("POS Profile", pos_profile)
	if profile.company != company:
		frappe.throw(_("POS Profile {0} does not belong to company {1}").format(pos_profile, company))
	context = build_currency_context(profile)
	methods = {
		row.get("mode_of_payment"): row
		for row in context.get("payment_methods") or []
	}
	clean_balances = []
	seen = set()
	for row in balance_details:
		mode = row.get("mode_of_payment")
		if not mode or mode in seen or mode not in methods:
			frappe.throw(_("Invalid or duplicate opening Mode of Payment: {0}").format(mode or _("blank")))
		seen.add(mode)
		currency = methods[mode].get("currency") or context["invoice_currency"]
		amount = flt(row.get("amount"))
		if amount < 0:
			frappe.throw(_("Opening amount for {0} cannot be negative").format(mode))
		company_exchange_rate = _rate(currency, context["company_currency"])
		clean_balances.append(
			{
				"mode_of_payment": mode,
				"currency": currency,
				"amount": amount,
				"company_exchange_rate": company_exchange_rate,
				"company_amount": amount * company_exchange_rate,
			}
		)

	existing = frappe.get_all(
		"POS Opening Shift",
		filters={"user": frappe.session.user, "status": "Open", "docstatus": 1},
		fields=["name"],
		limit=1,
	)
	if existing:
		frappe.throw(
			_("You already have an open POS Shift ({0}). Close it before opening another.").format(
				existing[0].name
			)
		)

	opening = frappe.get_doc(
		{
			"doctype": "POS Opening Shift",
			"period_start_date": get_datetime(),
			"posting_date": getdate(),
			"user": frappe.session.user,
			"pos_profile": pos_profile,
			"company": company,
			"docstatus": 1,
		}
	)
	opening.set("balance_details", clean_balances)
	opening.insert(ignore_permissions=True)

	return _shift_bootstrap(opening)


@frappe.whitelist()
def check_opening_shift(user=None):
	"""Bootstrap payload for the caller's open shift, or an empty string if none."""
	user = user or frappe.session.user
	if user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted to read another user's shift"), frappe.PermissionError)

	open_shifts = frappe.get_all(
		"POS Opening Shift",
		filters={
			"user": user,
			"pos_closing_shift": ["in", ["", None]],
			"docstatus": 1,
			"status": "Open",
		},
		fields=["name"],
		order_by="period_start_date desc",
		limit=1,
	)
	if not open_shifts:
		return ""

	return _shift_bootstrap(frappe.get_doc("POS Opening Shift", open_shifts[0].name))


def _shift_bootstrap(opening_shift):
	"""Everything the client needs in one round trip when a shift starts."""
	profile = frappe.get_cached_doc("POS Profile", opening_shift.pos_profile)
	company = frappe.get_cached_doc("Company", profile.company)

	payload = {
		"pos_opening_shift": opening_shift.as_dict(),
		"pos_profile": profile.as_dict(),
		"company": company.as_dict(),
		"stock_settings": {
			"allow_negative_stock": cint(frappe.get_single_value("Stock Settings", "allow_negative_stock")),
			"pick_serial_and_batch_based_on": frappe.get_single_value(
				"Stock Settings", "pick_serial_and_batch_based_on"
			),
		},
		"currency_symbol": frappe.db.get_value("Currency", profile.currency, "symbol") or profile.currency,
		"pos_settings": _pos_settings(),
		"currency_context": build_currency_context(profile),
	}
	payload.update(precision_settings())
	return payload


def _pos_settings():
	try:
		return frappe.get_cached_doc("POS Settings").as_dict()
	except Exception:
		return {}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_shift_analytics(opening_shift):
	"""Live currency-safe KPIs, tender reconciliation, top items and hourly sales."""
	shift = validate_shift_access(opening_shift)
	profile = frappe.get_cached_doc("POS Profile", shift.pos_profile)
	company_currency = frappe.get_cached_value("Company", shift.company, "default_currency")
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={"posa_pos_opening_shift": opening_shift, "docstatus": 1},
		fields=[
			"name",
			"posting_date",
			"posting_time",
			"customer",
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
		order_by="posting_date, posting_time, name",
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
			order_by="parent, idx",
			limit_page_length=0,
			ignore_permissions=True,
		)
		if invoice_names
		else []
	)
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
			order_by="parent, idx",
			limit_page_length=0,
			ignore_permissions=True,
		)
		if invoice_names
		else []
	)
	payment_entries = frappe.get_all(
		"Payment Entry",
		filters={
			"docstatus": 1,
			"reference_no": opening_shift,
			"payment_type": "Receive",
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
	context = build_currency_context(profile)
	method_currencies = {
		row.get("mode_of_payment"): row.get("currency")
		for row in context.get("payment_methods") or []
	}
	opening_balances = []
	for balance in shift.get("balance_details") or []:
		row = balance.as_dict()
		row["currency"] = (
			row.get("currency")
			or method_currencies.get(row.get("mode_of_payment"))
			or company_currency
		)
		row["company_exchange_rate"] = (
			flt(row.get("company_exchange_rate"))
			or _rate(row["currency"], company_currency, shift.posting_date)
		)
		row["company_amount"] = (
			flt(row.get("company_amount"))
			or flt(row.get("amount")) * row["company_exchange_rate"]
		)
		opening_balances.append(row)
	analytics = aggregate_shift(
		invoices,
		payments,
		items,
		company_currency=company_currency,
		cash_mode=profile.get("posa_cash_mode_of_payment") or "Cash",
		payment_entries=payment_entries,
		opening_balances=opening_balances,
	)
	analytics.update(
		{
			"shift": opening_shift,
			"opened_at": shift.period_start_date,
			# Compatibility for older clients. All KPI values now use this currency.
			"currency": company_currency,
		}
	)
	return analytics
