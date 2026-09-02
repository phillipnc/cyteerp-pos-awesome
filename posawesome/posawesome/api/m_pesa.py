# Copyright (c) 2021, Youssef Restom and contributors
# For license information, please see license.txt

import hmac
import json

import frappe
import requests
from frappe import _
from frappe.utils import flt
from requests.auth import HTTPBasicAuth


def get_token(app_key, app_secret, base_url):
    authenticate_uri = "/oauth/v1/generate?grant_type=client_credentials"
    authenticate_url = "{0}{1}".format(base_url, authenticate_uri)

    r = requests.get(authenticate_url, auth=HTTPBasicAuth(app_key, app_secret))

    return r.json()["access_token"]


@frappe.whitelist(allow_guest=True)
def confirmation(**kwargs):
    try:
        args = frappe._dict(kwargs)
        register = _validate_callback(args)
        if frappe.db.exists("Mpesa Payment Register", {"transid": args.get("TransID")}):
            return {"ResultCode": 0, "ResultDesc": "Accepted"}
        doc = frappe.new_doc("Mpesa Payment Register")
        doc.transactiontype = args.get("TransactionType")
        doc.transid = args.get("TransID")
        doc.transtime = args.get("TransTime")
        doc.transamount = args.get("TransAmount")
        doc.businessshortcode = args.get("BusinessShortCode")
        doc.billrefnumber = args.get("BillRefNumber")
        doc.invoicenumber = args.get("InvoiceNumber")
        doc.orgaccountbalance = args.get("OrgAccountBalance")
        doc.thirdpartytransid = args.get("ThirdPartyTransID")
        doc.msisdn = args.get("MSISDN")
        doc.firstname = args.get("FirstName")
        doc.middlename = args.get("MiddleName")
        doc.lastname = args.get("LastName")
        doc.company = register.company
        doc.mode_of_payment = register.mode_of_payment
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        context = {"ResultCode": 0, "ResultDesc": "Accepted"}
        return dict(context)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), str(e)[:140])
        context = {"ResultCode": 1, "ResultDesc": "Rejected"}
        return dict(context)


@frappe.whitelist(allow_guest=True)
def validation(**kwargs):
    try:
        args = frappe._dict(kwargs)
        _validate_callback(args)
        if not args.get("TransID") or flt(args.get("TransAmount")) <= 0:
            raise ValueError("Invalid transaction")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}
    except Exception:
        return {"ResultCode": 1, "ResultDesc": "Rejected"}


def _validate_callback(args):
    """Authenticate the callback URL and bind it to a registered shortcode."""
    shortcode = args.get("BusinessShortCode")
    token = args.get("token") or frappe.form_dict.get("token")
    if not shortcode or not token:
        frappe.throw(_("Invalid M-Pesa callback"), frappe.AuthenticationError)

    names = frappe.get_all(
        "Mpesa C2B Register URL",
        filters={"business_shortcode": shortcode, "register_status": "Success"},
        pluck="name",
        limit=2,
    )
    for name in names:
        register = frappe.get_doc("Mpesa C2B Register URL", name)
        expected = register.get_password("posa_callback_secret", raise_exception=False) or ""
        if expected and hmac.compare_digest(str(token), str(expected)):
            amount = flt(args.get("TransAmount"))
            if amount <= 0:
                frappe.throw(_("Invalid M-Pesa amount"))
            return register
    frappe.throw(_("Invalid M-Pesa callback"), frappe.AuthenticationError)


@frappe.whitelist()
def get_mpesa_mode_of_payment(company):
    modes = frappe.get_all(
        "Mpesa C2B Register URL",
        filters={"company": company, "register_status": "Success"},
        fields=["mode_of_payment"],
    )
    modes_of_payment = []
    for mode in modes:
        if mode.mode_of_payment not in modes_of_payment:
            modes_of_payment.append(mode.mode_of_payment)
    return modes_of_payment


@frappe.whitelist()
def get_mpesa_draft_payments(
    company,
    mode_of_payment=None,
    mobile_no=None,
    full_name=None,
    payment_methods_list=None,
):
    filters = {"company": company, "docstatus": 0}
    if mode_of_payment:
        filters["mode_of_payment"] = mode_of_payment
    if mobile_no:
        filters["msisdn"] = ["like", f"%{mobile_no}%"]
    if full_name:
        filters["full_name"] = ["like", f"%{full_name}%"]
    if payment_methods_list:
        filters["mode_of_payment"] = ["in", json.loads(payment_methods_list)]

    payments = frappe.get_all(
        "Mpesa Payment Register",
        filters=filters,
        fields=[
            "name",
            "transid",
            "msisdn as mobile_no",
            "full_name",
            "posting_date",
            "transamount as amount",
            "currency",
            "mode_of_payment",
            "company",
        ],
        order_by="posting_date desc",
    )
    return payments


@frappe.whitelist()
def submit_mpesa_payment(mpesa_payment, customer):
    doc = frappe.get_doc("Mpesa Payment Register", mpesa_payment)
    doc.customer = customer
    doc.submit_payment = 1
    doc.submit()
    doc.reload()
    return frappe.get_doc("Payment Entry", doc.payment_entry)
