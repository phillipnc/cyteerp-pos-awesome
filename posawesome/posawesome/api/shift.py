"""POS shift lifecycle: opening, closing, and live shift analytics."""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate

from posawesome.posawesome.api.utils import (
	as_dict,
	as_list,
	check_pos_profile_access,
	precision_settings,
	validate_shift_access,
)
from posawesome.posawesome.api.currency import build_currency_context

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

	currency_by_profile = {p.name: p.currency for p in profiles}
	for mode in payments:
		mode["currency"] = currency_by_profile.get(mode["parent"])

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
	opening.set("balance_details", balance_details)
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
	"""Live KPIs for a shift: totals, payment mix, top items and an hourly curve."""
	shift = validate_shift_access(opening_shift)
	currency = frappe.db.get_value("POS Profile", shift.pos_profile, "currency")

	sales = frappe.db.sql(
		"""
		select count(*) as count,
		       sum(grand_total) as grand_total,
		       sum(net_total) as net_total,
		       sum(total_qty) as total_qty,
		       sum(discount_amount) as discount_amount
		from `tabSales Invoice`
		where posa_pos_opening_shift = %s and docstatus = 1 and is_return = 0
		""",
		opening_shift,
		as_dict=True,
	)[0]

	returns = frappe.db.sql(
		"""
		select count(*) as count, sum(grand_total) as grand_total
		from `tabSales Invoice`
		where posa_pos_opening_shift = %s and docstatus = 1 and is_return = 1
		""",
		opening_shift,
		as_dict=True,
	)[0]

	invoice_count = cint(sales.get("count"))
	grand_total = flt(sales.get("grand_total"))

	payment_mix = frappe.db.sql(
		"""
		select sip.mode_of_payment, sum(sip.amount) as amount
		from `tabSales Invoice Payment` sip
		inner join `tabSales Invoice` si on si.name = sip.parent
		where si.posa_pos_opening_shift = %s and si.docstatus = 1
		group by sip.mode_of_payment
		order by amount desc
		""",
		opening_shift,
		as_dict=True,
	)

	top_items = frappe.db.sql(
		"""
		select sii.item_code, sii.item_name,
		       sum(sii.qty) as qty, sum(sii.amount) as amount
		from `tabSales Invoice Item` sii
		inner join `tabSales Invoice` si on si.name = sii.parent
		where si.posa_pos_opening_shift = %s and si.docstatus = 1 and si.is_return = 0
		group by sii.item_code, sii.item_name
		order by amount desc
		limit 8
		""",
		opening_shift,
		as_dict=True,
	)

	hourly = frappe.db.sql(
		"""
		select hour(si.posting_time) as hour,
		       sum(si.grand_total) as amount,
		       count(*) as count
		from `tabSales Invoice` si
		where si.posa_pos_opening_shift = %s and si.docstatus = 1 and si.is_return = 0
		group by hour(si.posting_time)
		order by hour
		""",
		opening_shift,
		as_dict=True,
	)

	return {
		"shift": opening_shift,
		"opened_at": frappe.db.get_value("POS Opening Shift", opening_shift, "period_start_date"),
		"invoice_count": invoice_count,
		"return_count": cint(returns.get("count")),
		"total_returned": abs(flt(returns.get("grand_total"))),
		"grand_total": grand_total,
		"net_total": flt(sales.get("net_total")),
		"total_qty": flt(sales.get("total_qty")),
		"total_discount": flt(sales.get("discount_amount")),
		"average_basket": flt(grand_total / invoice_count) if invoice_count else 0.0,
		"payment_mix": [{"mode_of_payment": r.mode_of_payment, "amount": flt(r.amount)} for r in payment_mix],
		"top_items": [
			{"item_code": r.item_code, "item_name": r.item_name, "qty": flt(r.qty), "amount": flt(r.amount)}
			for r in top_items
		],
		"hourly": [{"hour": cint(r.hour), "amount": flt(r.amount), "count": cint(r.count)} for r in hourly],
		"currency": currency,
	}
