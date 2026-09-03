# Copyright (c) 2020, Youssef Restom and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from posawesome.posawesome.api.currency import _rate, build_currency_context
from posawesome.posawesome.api.reporting import aggregate_shift


class POSClosingShift(Document):
    def validate(self):
        user = frappe.get_all(
            "POS Closing Shift",
            filters={
                "user": self.user,
                "docstatus": 1,
                "pos_opening_shift": self.pos_opening_shift,
                "name": ["!=", self.name],
            },
        )

        if user:
            frappe.throw(
                _(
                    "POS Closing Shift {} against {} between selected period".format(
                        frappe.bold("already exists"), frappe.bold(self.user)
                    )
                ),
                title=_("Invalid Period"),
            )

        if (
            frappe.db.get_value("POS Opening Shift", self.pos_opening_shift, "status")
            != "Open"
        ):
            frappe.throw(
                _("Selected POS Opening Shift should be open."),
                title=_("Invalid Opening Entry"),
            )
        self.update_payment_reconciliation()

    def update_payment_reconciliation(self):
        precision = (
            frappe.get_cached_value("System Settings", None, "currency_precision") or 3
        )
        company_currency = frappe.get_cached_value(
            "Company", self.company, "default_currency"
        )
        for d in self.payment_reconciliation:
            d.currency = d.currency or company_currency
            rate = _rate(d.currency, company_currency, self.posting_date)
            d.company_exchange_rate = rate
            d.company_closing_amount = flt(d.closing_amount, precision) * rate
            d.difference = flt(d.closing_amount, precision) - flt(
                d.expected_amount, precision
            )
            d.company_difference = flt(d.difference, precision) * rate

    def on_submit(self):
        opening_entry = frappe.get_doc("POS Opening Shift", self.pos_opening_shift)
        opening_entry.pos_closing_shift = self.name
        opening_entry.set_status()
        self.delete_draft_invoices()
        opening_entry.save()

    def delete_draft_invoices(self):
        if frappe.get_value("POS Profile", self.pos_profile, "posa_allow_delete"):
            data = frappe.get_all(
                "Sales Invoice",
                filters={
                    "docstatus": 0,
                    "posa_is_printed": 0,
                    "posa_pos_opening_shift": self.pos_opening_shift,
                },
                fields=["name"],
                limit_page_length=0,
            )

            for invoice in data:
                frappe.delete_doc("Sales Invoice", invoice.name, force=1)

    @frappe.whitelist()
    def get_payment_reconciliation_details(self):
        currency = frappe.get_cached_value("Company", self.company, "default_currency")
        return frappe.render_template(
            "posawesome/posawesome/doctype/pos_closing_shift/closing_shift_details.html",
            {"data": self, "currency": currency},
        )


@frappe.whitelist()
def get_cashiers(doctype, txt, searchfield, start, page_len, filters):
    cashiers_list = frappe.get_all("POS Profile User", filters=filters, fields=["user"])
    return [c["user"] for c in cashiers_list]


@frappe.whitelist()
def get_pos_invoices(pos_opening_shift):
    submit_printed_invoices(pos_opening_shift)
    data = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "posa_pos_opening_shift": pos_opening_shift},
        fields=["name"],
        order_by="posting_date, posting_time, name",
        limit_page_length=0,
    )

    data = [frappe.get_doc("Sales Invoice", d.name).as_dict() for d in data]

    return data


@frappe.whitelist()
def get_payments_entries(pos_opening_shift):
    return frappe.get_all(
        "Payment Entry",
        filters={
            "docstatus": 1,
            "reference_no": pos_opening_shift,
            "payment_type": "Receive",
        },
        fields=[
            "name",
            "mode_of_payment",
            "paid_amount",
            "received_amount",
            "base_received_amount",
            "paid_to_account_currency",
            "reference_no",
            "posting_date",
            "party",
        ],
    )


@frappe.whitelist()
def make_closing_shift_from_opening(opening_shift):
    if isinstance(opening_shift, str):
        try:
            opening_shift = json.loads(opening_shift)
        except (TypeError, ValueError):
            opening_shift = {"name": opening_shift}
    opening_name = opening_shift.get("name")
    if not opening_name:
        frappe.throw(_("POS Opening Shift is required"))
    opening_doc = frappe.get_doc("POS Opening Shift", opening_name)
    opening_shift = opening_doc.as_dict()
    submit_printed_invoices(opening_name)

    profile = frappe.get_cached_doc("POS Profile", opening_doc.pos_profile)
    company_currency = frappe.get_cached_value(
        "Company", opening_doc.company, "default_currency"
    )
    currency_context = build_currency_context(profile)
    method_currencies = {
        row.get("mode_of_payment"): row.get("currency")
        for row in currency_context.get("payment_methods") or []
    }
    opening_balances = []
    for detail in opening_doc.get("balance_details") or []:
        row = detail.as_dict()
        row["currency"] = (
            row.get("currency")
            or method_currencies.get(row.get("mode_of_payment"))
            or company_currency
        )
        row["company_exchange_rate"] = (
            flt(row.get("company_exchange_rate"))
            or _rate(row["currency"], company_currency, opening_doc.posting_date)
        )
        row["company_amount"] = (
            flt(row.get("company_amount"))
            or flt(row.get("amount")) * row["company_exchange_rate"]
        )
        opening_balances.append(row)

    closing_shift = frappe.new_doc("POS Closing Shift")
    closing_shift.pos_opening_shift = opening_name
    closing_shift.period_start_date = opening_shift.get("period_start_date")
    closing_shift.period_end_date = frappe.utils.get_datetime()
    closing_shift.posting_date = frappe.utils.getdate()
    closing_shift.pos_profile = opening_shift.get("pos_profile")
    closing_shift.user = opening_shift.get("user")
    closing_shift.company = opening_shift.get("company")
    closing_shift.grand_total = 0
    closing_shift.net_total = 0
    closing_shift.total_quantity = 0

    invoices = get_pos_invoices(opening_name)
    payment_rows = []
    item_rows = []
    for invoice in invoices:
        payment_rows.extend(invoice.get("payments") or [])
        item_rows.extend(invoice.get("items") or [])
    pos_payments = get_payments_entries(opening_name)
    analytics = aggregate_shift(
        invoices,
        payment_rows,
        item_rows,
        company_currency=company_currency,
        cash_mode=profile.get("posa_cash_mode_of_payment") or "Cash",
        payment_entries=pos_payments,
        opening_balances=opening_balances,
    )

    closing_shift.grand_total = analytics["net_sales"]
    closing_shift.net_total = analytics["net_total"]
    closing_shift.total_quantity = sum(
        (-1 if invoice.get("is_return") else 1)
        * sum(abs(flt(item.get("stock_qty") or item.get("qty"))) for item in invoice.get("items") or [])
        for invoice in invoices
    )

    pos_transactions = [
        {
            "sales_invoice": invoice.name,
            "posting_date": invoice.posting_date,
            "customer": invoice.customer,
            "currency": invoice.currency,
            "grand_total": invoice.grand_total,
            "base_grand_total": invoice.base_grand_total,
        }
        for invoice in invoices
    ]

    tax_groups = {}
    for invoice in invoices:
        for tax in invoice.get("taxes") or []:
            key = (tax.account_head, flt(tax.rate))
            if key not in tax_groups:
                tax_groups[key] = {
                    "account_head": tax.account_head,
                    "rate": tax.rate,
                    "amount": 0,
                }
            amount = flt(tax.get("base_tax_amount"))
            if not amount:
                amount = flt(tax.tax_amount) * flt(invoice.conversion_rate or 1)
            tax_groups[key]["amount"] += amount

    payments = []
    for row in analytics["payment_mix"]:
        rate = _rate(row["currency"], company_currency, closing_shift.posting_date)
        payments.append(
            {
                "mode_of_payment": row["mode_of_payment"],
                "currency": row["currency"],
                "company_exchange_rate": rate,
                "opening_amount": row["opening_amount"],
                "company_opening_amount": row["company_opening_amount"],
                "expected_amount": row["expected_amount"],
                "company_expected_amount": row["company_expected_amount"],
                "closing_amount": row["expected_amount"],
                "company_closing_amount": row["expected_amount"] * rate,
                "difference": 0,
                "company_difference": 0,
            }
        )

    pos_payments_table = [
        {
            "payment_entry": row.name,
            "mode_of_payment": row.mode_of_payment,
            "paid_amount": row.received_amount or row.paid_amount,
            "currency": row.paid_to_account_currency or company_currency,
            "base_paid_amount": row.base_received_amount,
            "posting_date": row.posting_date,
            "customer": row.party,
        }
        for row in pos_payments
    ]

    closing_shift.set("pos_transactions", pos_transactions)
    closing_shift.set("payment_reconciliation", payments)
    closing_shift.set("taxes", list(tax_groups.values()))
    closing_shift.set("pos_payments", pos_payments_table)

    return closing_shift


@frappe.whitelist()
def submit_closing_shift(closing_shift):
    payload = json.loads(closing_shift)
    opening_shift = payload.get("pos_opening_shift")
    if not opening_shift:
        frappe.throw(_("POS Opening Shift is required"))
    counted = {
        (row.get("mode_of_payment"), row.get("currency")): row.get("closing_amount")
        for row in payload.get("payment_reconciliation") or []
    }
    closing_shift_doc = make_closing_shift_from_opening(opening_shift)
    for row in closing_shift_doc.get("payment_reconciliation") or []:
        key = (row.mode_of_payment, row.currency)
        if key in counted and counted[key] is not None:
            row.closing_amount = counted[key]
    closing_shift_doc.flags.ignore_permissions = True
    closing_shift_doc.save()
    closing_shift_doc.submit()
    return closing_shift_doc.name


def submit_printed_invoices(pos_opening_shift):
    invoices_list = frappe.get_all(
        "Sales Invoice",
        filters={
            "posa_pos_opening_shift": pos_opening_shift,
            "docstatus": 0,
            "posa_is_printed": 1,
        },
    )
    if invoices_list:
        frappe.throw(
            _(
                "{0} printed invoice(s) are still waiting for background submission. "
                "Wait for the queue to finish before closing the shift."
            ).format(len(invoices_list))
        )
