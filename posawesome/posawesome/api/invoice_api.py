"""Sales Invoice endpoints for the POS.

The cart is persisted as a draft Sales Invoice while the cashier works, then
submitted on payment. Two things changed materially for v16:

  * ``set_batch_nos`` no longer exists. Batch and serial selection now goes through
    ``utils.apply_serial_batch_fields``, which flags rows so ERPNext builds the
    Serial and Batch Bundle itself at submit time.
  * ``get_existing_payment_request_amount`` changed signature, so the phone-payment
    path calls ERPNext's own ``make_payment_request`` instead of a forked copy.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate
from frappe.utils.background_jobs import enqueue

from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account
from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

from posawesome.posawesome.api.utils import (
	apply_serial_batch_fields,
	as_dict,
	validate_shift_access,
)
from posawesome.posawesome.api.currency import validate_tender_rows
from posawesome.posawesome.doctype.delivery_charges.delivery_charges import (
	get_applicable_delivery_charges as _get_applicable_delivery_charges,
)


# ---------------------------------------------------------------------------
# Draft lifecycle
# ---------------------------------------------------------------------------


@frappe.whitelist()
def update_invoice(data):
	"""Create or update the draft invoice backing the cart."""
	data = as_dict(data)
	validate_shift_access(data.get("posa_pos_opening_shift"))

	if data.get("name"):
		doc = frappe.get_doc("Sales Invoice", data.get("name"))
		if doc.docstatus != 0:
			frappe.throw(_("Invoice {0} is already submitted").format(doc.name))
		doc.update(data)
	else:
		doc = frappe.get_doc(data)

	doc.set_missing_values()
	doc.flags.ignore_permissions = True
	frappe.flags.ignore_account_permission = True

	if doc.is_return and doc.return_against:
		_prepare_return(doc)

	_validate_rates(doc)
	_apply_tax_templates(doc)

	if frappe.get_cached_value("POS Profile", doc.pos_profile, "posa_tax_inclusive"):
		for tax in doc.get("taxes") or []:
			tax.included_in_print_rate = 1

	if doc.get("posting_date") and getdate(doc.posting_date) != getdate():
		doc.set_posting_time = 1

	doc.save()
	return doc


def _prepare_return(doc):
	"""Mirror the original invoice's stock and payment shape onto a return."""
	reference = frappe.get_cached_doc(doc.doctype, doc.return_against)
	if not reference.update_stock:
		doc.update_stock = 0
	if not doc.payments:
		doc.payments = reference.payments

	doc.paid_amount = doc.rounded_total or doc.grand_total or doc.total
	for payment in doc.payments:
		if payment.default:
			payment.amount = doc.paid_amount


def _validate_rates(doc):
	"""Zero-rated lines are either free items or an error, per profile setting."""
	allow_zero_rated = frappe.get_cached_value("POS Profile", doc.pos_profile, "posa_allow_zero_rated_items")
	for item in doc.items:
		if flt(item.rate):
			item.is_free_item = 0
			continue
		if not allow_zero_rated:
			frappe.throw(_("Rate cannot be zero for item {0}").format(frappe.bold(item.item_code)))
		item.price_list_rate = 0.0
		item.is_free_item = 1


def _apply_tax_templates(doc):
	"""Add tax rows implied by each line's Item Tax Template, once each.

	The v14 version wrote each row with ``db_insert`` mid-validation, which left the
	in-memory document and the database disagreeing. Appending to the child table and
	letting ``save`` persist it keeps the two in step.
	"""
	if not frappe.get_cached_value("Accounts Settings", None, "add_taxes_from_item_tax_template"):
		return

	existing = {tax.account_head for tax in doc.get("taxes") or []}
	templates = {item.item_tax_template for item in doc.items if item.get("item_tax_template")}
	if not templates:
		return

	for tax_type in frappe.get_all(
		"Item Tax Template Detail",
		filters={"parent": ["in", list(templates)]},
		pluck="tax_type",
	):
		if tax_type in existing:
			continue
		existing.add(tax_type)
		doc.append(
			"taxes",
			{
				"charge_type": "On Net Total",
				"description": str(tax_type).split(" - ")[0],
				"account_head": tax_type,
			},
		)


@frappe.whitelist()
def submit_invoice(invoice, data):
	"""Finalise the sale: resolve batches, submit, then settle credit and change."""
	data = as_dict(data)
	invoice = as_dict(invoice)

	doc = frappe.get_doc("Sales Invoice", invoice.get("name"))
	validate_shift_access(doc.posa_pos_opening_shift)
	if doc.docstatus != 0:
		frappe.throw(_("Invoice {0} is already submitted").format(doc.name))

	doc.update(invoice)

	if invoice.get("posa_delivery_date"):
		# A future delivery is fulfilled by the Sales Order, not by this invoice.
		doc.update_stock = 0

	cash_account = _resolve_cash_account(doc)

	if flt(data.get("credit_change")):
		_create_advance_for_change(doc, data, cash_account)

	is_payment_entry = _attach_advances(doc, data)
	payments = list(doc.payments)
	total_cash = sum(abs(flt(payment.amount)) for payment in payments)

	# v16: flag rows so ERPNext materialises the Serial and Batch Bundle on submit.
	auto_set_batch = cint(frappe.get_cached_value("POS Profile", doc.pos_profile, "posa_auto_set_batch"))
	apply_serial_batch_fields(doc, auto_set_batch=auto_set_batch)

	doc.flags.ignore_permissions = True
	frappe.flags.ignore_account_permission = True
	doc.posa_is_printed = 1
	validate_tender_rows(doc)
	doc.save()
	_validate_payment_policy(doc, data)

	if data.get("due_date"):
		frappe.db.set_value("Sales Invoice", doc.name, "due_date", data.get("due_date"), update_modified=False)

	background = cint(
		frappe.get_cached_value("POS Profile", doc.pos_profile, "posa_allow_submissions_in_background_job")
	)
	if background:
		_enqueue_pending_submissions(doc, data, is_payment_entry, total_cash, cash_account, payments)
	else:
		doc.submit()
		settle_customer_credit(doc, data, is_payment_entry, total_cash, cash_account, payments)

	return {"name": doc.name, "status": doc.docstatus, "grand_total": doc.grand_total}


def _validate_payment_policy(doc, data):
	"""Enforce credit and partial-payment switches on the server as well as the SPA."""
	profile = frappe.get_cached_doc("POS Profile", doc.pos_profile)
	paid = sum(abs(flt(row.amount)) for row in doc.get("payments") or [])
	redeemed = abs(flt(data.get("redeemed_customer_credit"))) + abs(flt(doc.get("loyalty_amount")))
	total = abs(flt(doc.get("rounded_total") or doc.get("grand_total")))
	remaining = max(total - paid - redeemed, 0)
	precision = frappe.get_precision("Sales Invoice", "grand_total") or 2
	settled = remaining <= 0.5 / (10**precision)

	if settled:
		return
	if doc.is_return and paid == 0:
		if not profile.get("use_customer_credit"):
			frappe.throw(_("Customer-credit returns are not enabled for this POS Profile"))
		return
	if paid == 0:
		if not profile.get("posa_allow_credit_sale"):
			frappe.throw(_("Credit sales are not enabled for this POS Profile"))
		return
	if not profile.get("posa_allow_partial_payment"):
		frappe.throw(_("Partial payments are not enabled for this POS Profile"))


def _resolve_cash_account(doc):
	"""The account cash change should be paid out of."""
	cash_modes = [
		payment.mode_of_payment
		for payment in doc.payments
		if payment.type == "Cash" and "cash" in (payment.mode_of_payment or "").lower()
	]
	if cash_modes:
		return get_bank_cash_account(cash_modes[0], doc.company)
	return {"account": frappe.get_cached_value("Company", doc.company, "default_cash_account")}


def _create_advance_for_change(doc, data, cash_account):
	"""Park overpayment on the customer's account instead of handing back cash."""
	amount = flt(data.get("credit_change"))
	entry = frappe.get_doc(
		{
			"doctype": "Payment Entry",
			"mode_of_payment": "Cash",
			"paid_to": cash_account.get("account"),
			"payment_type": "Receive",
			"party_type": "Customer",
			"party": doc.customer,
			"paid_amount": amount,
			"received_amount": amount,
			"company": doc.company,
			"reference_no": doc.posa_pos_opening_shift,
			"reference_date": nowdate(),
		}
	)
	entry.flags.ignore_permissions = True
	frappe.flags.ignore_account_permission = True
	entry.insert()
	entry.submit()
	return entry


def _attach_advances(doc, data):
	"""Allocate existing advance payments against this invoice.

	Returns 1 when advances were used, which flips the invoice out of `is_pos` — the
	cash leg is then booked separately as Payment Entries.
	"""
	if not data.get("redeemed_customer_credit"):
		return 0

	used = 0
	for row in data.get("customer_credit_dict") or []:
		if row.get("type") != "Advance" or not flt(row.get("credit_to_redeem")):
			continue
		advance = frappe.get_doc("Payment Entry", row.get("credit_origin"))
		if (
			advance.docstatus != 1
			or advance.company != doc.company
			or advance.party_type != "Customer"
			or advance.party != doc.customer
			or advance.payment_type != "Receive"
			or advance.paid_from_account_currency != doc.currency
		):
			frappe.throw(
				_("Advance {0} is not valid for this customer and currency").format(
					advance.name
				)
			)
		amount = flt(row.get("credit_to_redeem"))
		if amount > flt(advance.unallocated_amount):
			frappe.throw(
				_("Advance allocation exceeds the unallocated amount on {0}").format(
					advance.name
				)
			)
		doc.append(
			"advances",
			{
				"reference_type": "Payment Entry",
				"reference_name": advance.name,
				"remarks": advance.remarks,
				"advance_amount": advance.unallocated_amount,
				"allocated_amount": amount,
			},
		)
		doc.is_pos = 0
		used = 1
	return used


def _enqueue_pending_submissions(doc, data, is_payment_entry, total_cash, cash_account, payments):
	"""Submit only this invoice with its own immutable settlement context."""
	enqueue(
		method=submit_in_background_job,
		queue="short",
		timeout=1000,
		is_async=True,
		job_name=f"posawesome-submit-{doc.name}",
		kwargs={
			"invoice": doc.name,
			"data": data,
			"is_payment_entry": is_payment_entry,
			"total_cash": total_cash,
			"cash_account": cash_account,
			"payments": [payment.as_dict() for payment in payments],
		},
	)


def submit_in_background_job(kwargs):
	invoice = kwargs.get("invoice")
	doc = frappe.get_doc("Sales Invoice", invoice)
	if doc.docstatus != 0:
		return
	doc.submit()
	settle_customer_credit(
		doc,
		kwargs.get("data"),
		kwargs.get("is_payment_entry"),
		kwargs.get("total_cash"),
		kwargs.get("cash_account"),
		kwargs.get("payments"),
	)


def settle_customer_credit(doc, data, is_payment_entry, total_cash, cash_account, payments):
	"""Book the journal/payment entries behind redeemed credit."""
	data = as_dict(data)
	if data.get("redeemed_customer_credit"):
		_knock_off_credit_invoices(doc, data)

	if is_payment_entry and flt(total_cash) > 0:
		_book_cash_legs(doc, data, payments)


def _knock_off_credit_invoices(doc, data):
	"""Offset credit sitting on old invoices against this one, via a journal entry."""
	cost_center = frappe.get_cached_value("POS Profile", doc.pos_profile, "cost_center") or frappe.get_cached_value(
		"Company", doc.company, "cost_center"
	)
	if not cost_center:
		frappe.throw(_("Cost Center is not set on POS Profile {0}").format(doc.pos_profile))

	for row in data.get("customer_credit_dict") or []:
		if row.get("type") != "Invoice" or not flt(row.get("credit_to_redeem")):
			continue

		origin = frappe.get_doc("Sales Invoice", row.get("credit_origin"))
		amount = flt(row.get("credit_to_redeem"))
		if (
			origin.docstatus != 1
			or not origin.is_return
			or origin.company != doc.company
			or origin.customer != doc.customer
			or origin.currency != doc.currency
		):
			frappe.throw(
				_("Credit note {0} is not valid for this customer and currency").format(
					origin.name
				)
			)
		if amount > abs(flt(origin.outstanding_amount)):
			frappe.throw(
				_("Credit allocation exceeds the available amount on {0}").format(
					origin.name
				)
			)

		journal = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"posting_date": nowdate(),
				"company": doc.company,
				"accounts": [
					{
						"account": origin.debit_to,
						"party_type": "Customer",
						"party": doc.customer,
						"reference_type": "Sales Invoice",
						"reference_name": origin.name,
						"debit_in_account_currency": amount,
						"cost_center": cost_center,
					},
					{
						"account": doc.debit_to,
						"party_type": "Customer",
						"party": doc.customer,
						"reference_type": "Sales Invoice",
						"reference_name": doc.name,
						"credit_in_account_currency": amount,
						"cost_center": cost_center,
					},
				],
			}
		)
		journal.flags.ignore_permissions = True
		frappe.flags.ignore_account_permission = True
		journal.set_missing_values()
		journal.insert()
		journal.submit()


def _book_cash_legs(doc, data, payments):
	"""When advances took the invoice out of is_pos, book the tendered cash by hand."""
	for payment in payments or []:
		amount = flt(payment.get("amount") if isinstance(payment, dict) else payment.amount)
		if not amount:
			continue
		mode = payment.get("mode_of_payment") if isinstance(payment, dict) else payment.mode_of_payment
		account = payment.get("account") if isinstance(payment, dict) else payment.account
		tender_amount = flt(
			payment.get("posa_tender_amount") if isinstance(payment, dict) else payment.posa_tender_amount
		)
		tender_rate = flt(
			payment.get("posa_exchange_rate") if isinstance(payment, dict) else payment.posa_exchange_rate
		) or 1
		account_currency = frappe.get_cached_value("Account", account, "account_currency")
		tender_currency = (
			payment.get("posa_tender_currency")
			if isinstance(payment, dict)
			else payment.posa_tender_currency
		) or doc.currency
		if account_currency != tender_currency:
			frappe.throw(
				_("Payment account {0} must use tender currency {1}").format(
					account, tender_currency
				)
			)

		entry = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"posting_date": nowdate(),
				"payment_type": "Receive",
				"party_type": "Customer",
				"party": doc.customer,
				"paid_amount": amount,
				"received_amount": abs(tender_amount) or abs(amount) / tender_rate,
				"paid_from": doc.debit_to,
				"paid_to": account,
				"paid_from_account_currency": doc.currency,
				"paid_to_account_currency": tender_currency,
				"source_exchange_rate": flt(doc.conversion_rate) or 1,
				"target_exchange_rate": (flt(doc.conversion_rate) or 1) * tender_rate,
				"company": doc.company,
				"mode_of_payment": mode,
				"reference_no": doc.posa_pos_opening_shift,
				"reference_date": nowdate(),
				"references": [
					{
						"allocated_amount": amount,
						"due_date": data.get("due_date"),
						"reference_doctype": "Sales Invoice",
						"reference_name": doc.name,
					}
				],
			}
		)
		entry.flags.ignore_permissions = True
		frappe.flags.ignore_account_permission = True
		entry.insert()
		entry.submit()


@frappe.whitelist()
def delete_invoice(invoice):
	"""Discard a held draft."""
	name, printed, shift = frappe.db.get_value(
		"Sales Invoice", invoice, ["name", "posa_is_printed", "posa_pos_opening_shift"]
	)
	if not name:
		frappe.throw(_("Invoice {0} not found").format(invoice))
	validate_shift_access(shift)
	if printed:
		frappe.throw(_("Invoice {0} has been printed and cannot be deleted").format(invoice))

	frappe.delete_doc("Sales Invoice", invoice, force=1, ignore_permissions=True)
	return _("Invoice {0} deleted").format(invoice)


@frappe.whitelist()
def get_draft_invoices(pos_opening_shift):
	"""Held invoices for the current shift."""
	validate_shift_access(pos_opening_shift)
	names = frappe.get_all(
		"Sales Invoice",
		filters={"posa_pos_opening_shift": pos_opening_shift, "docstatus": 0, "posa_is_printed": 0},
		pluck="name",
		order_by="modified desc",
		limit_page_length=0,
	)
	return [frappe.get_doc("Sales Invoice", name).as_dict() for name in names]


# ---------------------------------------------------------------------------
# Returns and orders
# ---------------------------------------------------------------------------


@frappe.whitelist()
def search_invoices_for_return(invoice_name, company, customer=None, limit=20):
	"""Submitted invoices eligible to be returned against."""
	filters = {"company": company, "docstatus": 1, "is_return": 0}
	if invoice_name:
		filters["name"] = ["like", f"%{invoice_name}%"]
	if customer:
		filters["customer"] = customer

	names = frappe.get_all(
		"Sales Invoice", filters=filters, pluck="name", order_by="posting_date desc", limit_page_length=cint(limit)
	)
	if not names:
		return []

	returned_names = frappe.get_all(
		"Sales Invoice",
		filters={"return_against": ["in", names], "docstatus": 1},
		pluck="name",
	)
	returned_qty = {}
	returned_serials = {}
	if returned_names:
		for row in frappe.get_all(
			"Sales Invoice Item",
			filters={"parent": ["in", returned_names]},
			fields=[
				"sales_invoice_item",
				"qty",
				"serial_no",
				"batch_no",
				"serial_and_batch_bundle",
			],
		):
			if row.sales_invoice_item:
				returned_qty[row.sales_invoice_item] = returned_qty.get(row.sales_invoice_item, 0) + flt(row.qty)
				_restore_legacy_serial_batch_fields(row)
				if row.get("serial_no"):
					returned_serials.setdefault(row.sales_invoice_item, set()).update(
						value.strip()
						for value in row.serial_no.replace(",", "\n").splitlines()
						if value.strip()
					)

	result = []
	for name in names:
		doc = frappe.get_doc("Sales Invoice", name).as_dict()
		available_rows = []
		for row in doc.get("items") or []:
			remaining = max(flt(row.qty) + flt(returned_qty.get(row.name)), 0)
			if remaining <= 0:
				continue
			row["posa_returnable_qty"] = remaining
			_restore_legacy_serial_batch_fields(row)
			if row.get("serial_no"):
				used = returned_serials.get(row.name, set())
				row["serial_no"] = "\n".join(
					value.strip()
					for value in row.serial_no.replace(",", "\n").splitlines()
					if value.strip() and value.strip() not in used
				)
			available_rows.append(row)
		if available_rows:
			doc["items"] = available_rows
			result.append(doc)
	return result


def _restore_legacy_serial_batch_fields(row):
	"""Expose v16 bundle data to the SPA when legacy fields are empty."""
	if row.get("serial_no") or row.get("batch_no") or not row.get("serial_and_batch_bundle"):
		return
	bundle = frappe.get_doc("Serial and Batch Bundle", row.get("serial_and_batch_bundle"))
	entries = bundle.get("entries") or []
	serials = [entry.serial_no for entry in entries if entry.serial_no]
	batches = list(dict.fromkeys(entry.batch_no for entry in entries if entry.batch_no))
	if serials:
		row["serial_no"] = "\n".join(serials)
	if len(batches) == 1:
		row["batch_no"] = batches[0]


@frappe.whitelist()
def search_orders(company, currency, order_name=None, customer=None, limit=20):
	"""Open sales orders that can be billed from the POS."""
	filters = {
		"billing_status": ["in", ["Not Billed", "Partly Billed"]],
		"docstatus": 1,
		"company": company,
		"currency": currency,
	}
	if order_name:
		filters["name"] = ["like", f"%{order_name}%"]
	if customer:
		filters["customer"] = customer

	names = frappe.get_all(
		"Sales Order", filters=filters, pluck="name", order_by="transaction_date desc", limit_page_length=cint(limit)
	)
	return [frappe.get_doc("Sales Order", name).as_dict() for name in names]


@frappe.whitelist()
def create_sales_invoice_from_order(sales_order):
	invoice = make_sales_invoice(sales_order, ignore_permissions=True)
	invoice.flags.ignore_permissions = True
	invoice.insert()
	return invoice


@frappe.whitelist()
def get_applicable_delivery_charges(company, pos_profile, customer, shipping_address_name=None):
	return _get_applicable_delivery_charges(company, pos_profile, customer, shipping_address_name)


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------


def _sales_invoice_print_formats():
	return [
		row.name
		for row in frappe.get_all(
			"Print Format",
			filters={"doc_type": "Sales Invoice", "disabled": 0},
			fields=["name"],
			order_by="name",
			limit_page_length=0,
		)
	]


def _resolve_print_format(doc, requested=None):
	"""Which format a receipt should use, in order of how deliberate the choice is.

	The POS Profile is the shop's own decision and wins. Failing that, the doctype's
	configured default is what the desk would print, and matching it means the receipt
	from the till and the reprint from the desk are the same document. Only then do we
	fall back to whatever exists, which is otherwise an alphabetical accident.
	"""
	if requested:
		return requested

	profile_format = (
		frappe.get_cached_value("POS Profile", doc.pos_profile, "print_format")
		if doc.pos_profile
		else None
	)
	if profile_format:
		return profile_format

	meta_default = frappe.get_meta("Sales Invoice").default_print_format
	if meta_default:
		return meta_default

	formats = _sales_invoice_print_formats()
	return formats[0] if formats else None


@frappe.whitelist()
def get_print_options(invoice):
	"""Print formats and letterheads the print dialog offers for one invoice."""
	doc = frappe.get_doc("Sales Invoice", invoice)
	doc.check_permission("read")

	formats = _sales_invoice_print_formats()
	default_format = _resolve_print_format(doc)
	if default_format and default_format not in formats:
		formats.insert(0, default_format)

	# The doctype is "Letter Head", two words. Querying "Letterhead" raised
	# DoesNotExistError, which took the whole dialog down with it — no formats, no
	# preview, nothing to print.
	letterheads = [
		row.name
		for row in frappe.get_all(
			"Letter Head",
			filters={"disabled": 0},
			fields=["name"],
			order_by="name",
			limit_page_length=0,
		)
	]

	return {
		"default_print_format": default_format,
		"print_formats": formats,
		"default_letterhead": frappe.db.get_value(
			"Letter Head", {"is_default": 1, "disabled": 0}, "name"
		),
		"letterheads": letterheads,
	}


@frappe.whitelist()
def get_invoice_print_html(invoice, print_format=None, letterhead=None, no_letterhead=0):
	"""Rendered invoice HTML so the SPA can print without leaving the page."""
	doc = frappe.get_doc("Sales Invoice", invoice)
	doc.check_permission("read")

	# Same resolution as the dialog's own default, so the preview and the printed
	# sheet cannot be two different documents.
	print_format = _resolve_print_format(doc, print_format)
	suppress_letterhead = cint(no_letterhead) or not letterhead

	html = frappe.get_print(
		"Sales Invoice",
		invoice,
		print_format=print_format,
		letterhead=None if suppress_letterhead else letterhead,
		no_letterhead=1 if suppress_letterhead else 0,
	)
	return {"html": html, "print_format": print_format}


@frappe.whitelist()
def get_sales_invoice_child_table(sales_invoice, sales_invoice_item):
	parent = frappe.get_doc("Sales Invoice", sales_invoice)
	parent.check_permission("read")
	return frappe.get_doc("Sales Invoice Item", {"parent": parent.name, "name": sales_invoice_item})
