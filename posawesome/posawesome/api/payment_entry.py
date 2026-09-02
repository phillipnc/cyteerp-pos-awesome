# Copyright (c) 2021, Youssef Restom and contributors
# For license information, please see license.txt

"""Standalone payment capture and reconciliation (the "POS Awesome Payments" screen).

This is the collections workflow: take money against outstanding invoices, or park
it as an advance, without ringing up a sale.
"""

import erpnext
import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from erpnext.accounts.doctype.bank_account.bank_account import get_party_bank_account
from erpnext.accounts.doctype.journal_entry.journal_entry import get_default_bank_cash_account
from erpnext.accounts.doctype.payment_request.payment_request import (
	make_payment_request as _make_payment_request,
)
from erpnext.accounts.party import get_party_account
from erpnext.accounts.utils import get_account_currency
from erpnext.accounts.utils import get_outstanding_invoices as _get_outstanding_invoices
from posawesome.posawesome.api.currency import _rate
from posawesome.posawesome.api.m_pesa import submit_mpesa_payment
from posawesome.posawesome.api.utils import as_dict, validate_shift_access


def create_payment_entry(
    company,
    customer,
    amount,
    currency,
    mode_of_payment,
    reference_date=None,
    reference_no=None,
    posting_date=None,
    cost_center=None,
    submit=0,
    tender_currency=None,
    tender_amount=None,
    tender_exchange_rate=None,
):
    date = nowdate() if not posting_date else posting_date
    party_type = "Customer"
    party_account = get_party_account(party_type, customer, company)
    party_account_currency = get_account_currency(party_account)
    payment_type = "Receive"
    bank = get_bank_cash_account(company, mode_of_payment)
    if not bank:
        frappe.throw(
            _("No bank or cash account is configured for {0}").format(mode_of_payment)
        )

    tender_currency = tender_currency or bank.account_currency
    if tender_currency != bank.account_currency:
        frappe.throw(
            _("{0} must be received in account currency {1}").format(
                mode_of_payment, bank.account_currency
            )
        )
    company_currency = frappe.get_value("Company", company, "default_currency")
    invoice_rate = _rate(currency, company_currency, date)
    party_rate = _rate(party_account_currency, company_currency, date)
    tender_rate = _rate(tender_currency, company_currency, date)
    expected_tender_exchange_rate = tender_rate / invoice_rate
    if tender_exchange_rate and abs(
        flt(tender_exchange_rate) - expected_tender_exchange_rate
    ) / expected_tender_exchange_rate > 0.05:
        frappe.throw(_("Tender exchange rate is outside the allowed tolerance"))

    company_value = abs(flt(amount)) * invoice_rate
    paid_amount = company_value / party_rate
    received_amount = (
        abs(flt(tender_amount))
        if tender_amount
        else company_value / tender_rate
    )

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = payment_type
    pe.company = company
    pe.cost_center = cost_center or erpnext.get_default_cost_center(company)
    pe.posting_date = date
    pe.mode_of_payment = mode_of_payment
    pe.party_type = party_type
    pe.party = customer

    pe.paid_from = party_account if payment_type == "Receive" else bank.account
    pe.paid_to = party_account if payment_type == "Pay" else bank.account
    pe.paid_from_account_currency = (
        party_account_currency if payment_type == "Receive" else bank.account_currency
    )
    pe.paid_to_account_currency = (
        party_account_currency if payment_type == "Pay" else bank.account_currency
    )
    pe.paid_amount = paid_amount
    pe.received_amount = received_amount
    pe.source_exchange_rate = party_rate
    pe.target_exchange_rate = tender_rate
    pe.letter_head = frappe.get_value("Company", company, "default_letter_head")
    pe.reference_date = reference_date
    pe.reference_no = reference_no
    if pe.party_type in ["Customer", "Supplier"]:
        bank_account = get_party_bank_account(pe.party_type, pe.party)
        pe.set("bank_account", bank_account)
        pe.set_bank_account_data()

    pe.setup_party_account_field()
    pe.set_missing_values()

    if party_account and bank:
        pe.set_amounts()
    if submit:
        pe.docstatus = 1
    pe.insert(ignore_permissions=True)
    return pe


def get_bank_cash_account(company, mode_of_payment, bank_account=None):
    bank = get_default_bank_cash_account(
        company, "Bank", mode_of_payment=mode_of_payment, account=bank_account
    )

    if not bank:
        bank = get_default_bank_cash_account(
            company, "Cash", mode_of_payment=mode_of_payment, account=bank_account
        )

    return bank


def set_paid_amount_and_received_amount(
    party_account_currency,
    bank,
    outstanding_amount,
    payment_type,
    bank_amount,
    conversion_rate,
):
    paid_amount = received_amount = 0
    if party_account_currency == bank.account_currency:
        paid_amount = received_amount = abs(outstanding_amount)
    elif payment_type == "Receive":
        paid_amount = abs(outstanding_amount)
        if bank_amount:
            received_amount = bank_amount
        else:
            received_amount = paid_amount * conversion_rate

    else:
        received_amount = abs(outstanding_amount)
        if bank_amount:
            paid_amount = bank_amount
        else:
            # if party account currency and bank currency is different then populate paid amount as well
            paid_amount = received_amount * conversion_rate

    return paid_amount, received_amount


@frappe.whitelist()
def get_outstanding_invoices(company, currency, customer=None, pos_profile_name=None):
    if customer:
        precision = frappe.get_precision("Sales Invoice", "outstanding_amount") or 2
        outstanding_invoices = _get_outstanding_invoices(
            party_type="Customer",
            party=customer,
            account=get_party_account("Customer", customer, company),
        )
        invoices_list = []
        customer_name = frappe.get_cached_value("Customer", customer, "customer_name")
        for invoice in outstanding_invoices:
            if invoice.get("currency") == currency:
                if pos_profile_name and frappe.get_cached_value(
                    "Sales Invoice", invoice.get("voucher_no"), "pos_profile"
                ) != pos_profile_name:
                    continue
                outstanding_amount = invoice.outstanding_amount
                if outstanding_amount > 0.5 / (10**precision):
                    invoice_dict = {
                        "name": invoice.get("voucher_no"),
                        "customer": customer,
                        "customer_name": customer_name,
                        "outstanding_amount": invoice.get("outstanding_amount"),
                        "grand_total": invoice.get("invoice_amount"),
                        "due_date": invoice.get("due_date"),
                        "posting_date": invoice.get("posting_date"),
                        "currency": invoice.get("currency"),
                        "pos_profile": pos_profile_name,

                    }
                    invoices_list.append(invoice_dict)
        return invoices_list
    else:
        filters = {
            "company": company,
            "outstanding_amount": (">", 0),
            "docstatus": 1,
            "is_return": 0,
            "currency": currency,
        }
        if customer:
            filters.update({"customer": customer})
        if pos_profile_name:
            filters.update({"pos_profile": pos_profile_name})
        invoices = frappe.get_all(
            "Sales Invoice",
            filters=filters,
            fields=[
                "name",
                "customer",
                "customer_name",
                "outstanding_amount",
                "grand_total",
                "due_date",
                "posting_date",
                "currency",
                "pos_profile",
            ],
            order_by="due_date asc",
        )
        return invoices


@frappe.whitelist()
def get_unallocated_payments(customer, company, currency, mode_of_payment=None):
    filters = {
        "party": customer,
        "company": company,
        "docstatus": 1,
        "party_type": "Customer",
        "payment_type": "Receive",
        "unallocated_amount": [">", 0],
        "paid_from_account_currency": currency,
    }
    if mode_of_payment:
        filters.update({"mode_of_payment": mode_of_payment})
    unallocated_payment = frappe.get_all(
        "Payment Entry",
        filters=filters,
        fields=[
            "name",
            "paid_amount",
            "party_name as customer_name",
            "received_amount",
            "posting_date",
            "unallocated_amount",
            "mode_of_payment",
            "paid_from_account_currency as currency",
        ],
        order_by="posting_date asc",
    )
    return unallocated_payment


@frappe.whitelist()
def process_pos_payment(payload):
    data = as_dict(payload)
    validate_shift_access(data.get("pos_opening_shift_name"))

    # validate data
    if not data.customer:
        frappe.throw(_("Customer is required"))
    if not data.company:
        frappe.throw(_("Company is required"))
    if not data.currency:
        frappe.throw(_("Currency is required"))
    if not data.pos_profile_name:
        frappe.throw(_("POS Profile is required"))
    if not data.pos_opening_shift_name:
        frappe.throw(_("POS Opening Shift is required"))

    profile = frappe.get_cached_doc("POS Profile", data.pos_profile_name)
    opening = frappe.get_cached_doc("POS Opening Shift", data.pos_opening_shift_name)
    if (
        profile.company != data.company
        or opening.pos_profile != profile.name
        or opening.company != data.company
        or opening.status != "Open"
    ):
        frappe.throw(_("POS Profile, company and opening shift do not match"))
    if not profile.get("posa_use_pos_awesome_payments"):
        frappe.throw(_("POS Awesome Payments is not enabled for this POS Profile"))
    data.pos_profile = profile

    company = data.company
    currency = data.currency
    customer = data.customer
    pos_opening_shift_name = data.pos_opening_shift_name
    allow_make_new_payments = data.pos_profile.get("posa_allow_make_new_payments")
    allow_reconcile_payments = data.pos_profile.get("posa_allow_reconcile_payments")
    allow_mpesa_reconcile_payments = data.pos_profile.get(
        "posa_allow_mpesa_reconcile_payments"
    )
    today = nowdate()
    allowed_modes = {row.mode_of_payment for row in profile.get("payments") or []}
    for payment_method in data.get("payment_methods") or []:
        if payment_method.get("mode_of_payment") not in allowed_modes:
            frappe.throw(
                _("Mode of Payment {0} is not configured for this POS Profile").format(
                    payment_method.get("mode_of_payment")
                )
            )

    validated_invoices = []
    for selected in data.get("selected_invoices") or []:
        invoice = frappe.get_cached_doc("Sales Invoice", selected.get("name"))
        if (
            invoice.docstatus != 1
            or invoice.company != company
            or invoice.customer != customer
            or invoice.currency != currency
            or flt(invoice.outstanding_amount) <= 0
        ):
            frappe.throw(_("Invoice {0} is not available for reconciliation").format(invoice.name))
        validated_invoices.append(
            frappe._dict(
                name=invoice.name,
                posting_date=invoice.posting_date,
                grand_total=invoice.grand_total,
                outstanding_amount=invoice.outstanding_amount,
                currency=invoice.currency,
            )
        )
    data.selected_invoices = validated_invoices

    validated_payments = []
    for selected in data.get("selected_payments") or []:
        payment = frappe.get_cached_doc("Payment Entry", selected.get("name"))
        if (
            payment.docstatus != 1
            or payment.company != company
            or payment.party_type != "Customer"
            or payment.party != customer
            or payment.payment_type != "Receive"
            or flt(payment.unallocated_amount) <= 0
        ):
            frappe.throw(_("Payment {0} is not available for reconciliation").format(payment.name))
        validated_payments.append(payment.as_dict())
    data.selected_payments = validated_payments

    new_payments_entry = []
    all_payments_entry = []
    errors = []
    reconcile_doc = None

    # first process mpesa payments
    if (
        allow_mpesa_reconcile_payments
        and len(data.selected_mpesa_payments) > 0
        and data.total_selected_mpesa_payments > 0
    ):
        for mpesa_payment in data.selected_mpesa_payments:
            try:
                new_mpesa_payment = submit_mpesa_payment(
                    mpesa_payment.get("name"), customer
                )
                new_payments_entry.append(new_mpesa_payment)
                all_payments_entry.append(new_mpesa_payment)
            except Exception as e:
                errors.append(e)

    # then process the new payments
    if (
        allow_make_new_payments
        and len(data.payment_methods) > 0
        and data.total_payment_methods > 0
    ):
        for payment_method in data.payment_methods:
            try:
                if not payment_method.get("amount"):
                    continue
                new_payment_entry = create_payment_entry(
                    company=company,
                    customer=customer,
                    currency=currency,
                    amount=flt(payment_method.get("amount")),
                    mode_of_payment=payment_method.get("mode_of_payment"),
                    posting_date=today,
                    reference_no=pos_opening_shift_name,
                    reference_date=today,
                    cost_center=data.pos_profile.get("cost_center"),
                    submit=1,
                    tender_currency=payment_method.get("currency"),
                    tender_amount=payment_method.get("tendered_amount"),
                    tender_exchange_rate=payment_method.get("exchange_rate"),
                )
                new_payments_entry.append(new_payment_entry)
                all_payments_entry.append(new_payment_entry)
            except Exception as e:
                errors.append(e)

    # then then reconcile the new payments and the unallocated payments with the outstanding invoices
    if len(data.selected_invoices) > 0 and data.total_selected_invoices > 0:
        if (
            allow_reconcile_payments
            and len(data.selected_payments) > 0
            and data.total_selected_payments > 0
        ):
            # add the unallocated payments to the all payments entry
            for selected_payment in data.selected_payments:
                all_payments_entry.append(selected_payment)

        if len(all_payments_entry) > 0:
            # sort the all payments entry by posting date
            all_payments_entry = sorted(
                all_payments_entry,
                key=lambda k: getdate(str(k.get("posting_date"))),
                reverse=True,
            )
            all_invoices_list = sorted(
                data.selected_invoices,
                key=lambda k: getdate(k.get("posting_date")),
                reverse=True,
            )
            reconcile_doc = frappe.new_doc("Payment Reconciliation")
            reconcile_doc.party_type = "Customer"
            reconcile_doc.party = customer
            reconcile_doc.company = company
            reconcile_doc.receivable_payable_account = get_party_account(
                "Customer", customer, company
            )
            reconcile_doc.get_unreconciled_entries()
            args = {
                "invoices": [],
                "payments": [],
            }
            for invoice in all_invoices_list:
                args["invoices"].append(
                    {
                        "invoice_type": "Sales Invoice",
                        "invoice_number": invoice.get("name"),
                        "invoice_date": invoice.get("posting_date"),
                        "amount": invoice.get("grand_total"),
                        "outstanding_amount": invoice.get("outstanding_amount"),
                        "currency": invoice.get("currency"),
                        "exchange_rate": 0,
                    }
                )
            for payment in all_payments_entry:
                args["payments"].append(
                    {
                        "reference_type": "Payment Entry",
                        "reference_name": payment.get("name"),
                        "posting_date": payment.get("posting_date"),
                        "amount": payment.get("unallocated_amount"),
                        "unallocated_amount": payment.get("unallocated_amount"),
                        "difference_amount": 0,
                        "currency": payment.get("currency"),
                        "exchange_rate": 0,
                    }
                )
            reconcile_doc.allocate_entries(args)
            reconcile_doc.reconcile()

    # Hand the client structured results; the SPA renders its own summary rather
    # than parsing an HTML blob out of a msgprint.
    def summarise(entries):
        return [
            {
                "name": entry.get("name"),
                "mode_of_payment": entry.get("mode_of_payment"),
                "amount": flt(entry.get("paid_amount")),
                "unallocated_amount": flt(entry.get("unallocated_amount")),
                "posting_date": str(entry.get("posting_date") or ""),
            }
            for entry in entries
        ]

    return {
        "new_payments_entry": summarise(new_payments_entry),
        "all_payments_entry": summarise(all_payments_entry),
        "reconciled_invoices": [
            {
                "name": invoice.get("name"),
                "outstanding_amount": flt(invoice.get("outstanding_amount")),
            }
            for invoice in (data.selected_invoices or [])
        ],
        "errors": [str(error) for error in errors],
        "reconcile_doc": reconcile_doc.name if reconcile_doc else None,
    }


@frappe.whitelist()
def get_available_pos_profiles(company, currency):
    pos_profiles_list = frappe.get_list(
        "POS Profile",
        filters={"disabled": 0, "company": company, "currency": currency},
        page_length=1000,
        pluck="name",
    )
    return pos_profiles_list


@frappe.whitelist()
def create_payment_request(doc):
	"""Kick off a phone/gateway payment for the Phone-type rows on an invoice.

	v14 shipped a forked copy of ERPNext's ``make_payment_request`` because the
	upstream one could not price a POS phone payment. v16's ``get_amount`` handles
	that case natively, so we call upstream directly and the fork is gone.
	"""
	doc = as_dict(doc)
	requests = []

	for payment in doc.get("payments") or []:
		if payment.get("type") != "Phone":
			continue
		if flt(payment.get("amount")) <= 0:
			frappe.throw(_("Payment amount must be greater than zero"))
		if not doc.get("contact_mobile"):
			frappe.throw(_("Enter the customer's phone number first"))

		gateway_account = frappe.db.get_value(
			"Payment Gateway Account", {"payment_account": payment.get("account")}, "name"
		)
		if not gateway_account:
			frappe.throw(
				_("No Payment Gateway Account is configured for account {0}").format(payment.get("account"))
			)

		existing = frappe.db.exists(
			"Payment Request",
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": doc.get("name"),
				"payment_gateway_account": gateway_account,
				"docstatus": ["!=", 2],
			},
		)
		if existing:
			request = frappe.get_doc("Payment Request", existing)
			request.request_phone_payment()
		else:
			request = _make_payment_request(
				dt="Sales Invoice",
				dn=doc.get("name"),
				recipient_id=doc.get("contact_mobile"),
				phone_number=doc.get("contact_mobile"),
				mode_of_payment=payment.get("mode_of_payment"),
				payment_gateway_account=gateway_account,
				payment_request_type="Inward",
				party_type="Customer",
				party=doc.get("customer"),
				submit_doc=True,
				return_doc=True,
			)

		requests.append(request.as_dict() if hasattr(request, "as_dict") else request)

	return requests[0] if len(requests) == 1 else requests
