"""Customer endpoints and Customer document hooks."""

import frappe
from frappe import _
from frappe.utils import cint

from erpnext.accounts.doctype.loyalty_program.loyalty_program import (
	get_loyalty_program_details_with_points,
)

from posawesome.posawesome.api.utils import as_dict
from posawesome.posawesome.doctype.referral_code.referral_code import create_referral_code

# ---------------------------------------------------------------------------
# Document hooks
# ---------------------------------------------------------------------------


def after_insert(doc, method=None):
	create_customer_referral_code(doc)
	create_gift_coupon(doc)


def validate(doc, method=None):
	validate_referral_code(doc)


def create_customer_referral_code(doc):
	if not doc.get("posa_referral_company"):
		return
	company = frappe.get_cached_doc("Company", doc.posa_referral_company)
	if not company.get("posa_auto_referral"):
		return
	create_referral_code(
		doc.posa_referral_company,
		doc.name,
		company.get("posa_customer_offer"),
		company.get("posa_primary_offer"),
		company.get("posa_referral_campaign"),
	)


def create_gift_coupon(doc):
	if not doc.get("posa_referral_code"):
		return
	coupon = frappe.new_doc("POS Coupon")
	coupon.customer = doc.name
	coupon.referral_code = doc.posa_referral_code
	coupon.create_coupon_from_referral()


def validate_referral_code(doc):
	referral_code = doc.get("posa_referral_code")
	if not referral_code:
		return
	exists = frappe.db.exists("Referral Code", referral_code) or frappe.db.exists(
		"Referral Code", {"referral_code": referral_code}
	)
	if not exists:
		frappe.throw(_("Referral Code {0} does not exist").format(referral_code))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _customer_group_filter(pos_profile):
	"""Customer groups a profile is limited to, expanded through the group tree."""
	groups = pos_profile.get("customer_groups") or []
	if not groups:
		return None

	names = []
	for row in groups:
		group = row.get("customer_group")
		if not group:
			continue
		lft, rgt = frappe.db.get_value("Customer Group", group, ["lft", "rgt"])
		names.extend(
			row.name
			for row in frappe.get_all(
				"Customer Group", filters={"lft": [">=", lft], "rgt": ["<=", rgt]}, fields=["name"]
			)
		)
	return list(set(names)) or None


@frappe.whitelist()
def get_customer_names(pos_profile, search=None):
	"""Customer list for the picker, scoped to the profile's customer groups."""
	profile = as_dict(pos_profile)

	filters = {"disabled": 0}
	groups = _customer_group_filter(profile)
	if groups:
		filters["customer_group"] = ["in", groups]

	or_filters = None
	if search:
		pattern = f"%{search}%"
		or_filters = {
			"name": ["like", pattern],
			"customer_name": ["like", pattern],
			"mobile_no": ["like", pattern],
			"tax_id": ["like", pattern],
			"email_id": ["like", pattern],
		}

	return frappe.get_all(
		"Customer",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "customer_name", "mobile_no", "email_id", "tax_id", "primary_address"],
		order_by="customer_name asc",
		limit_page_length=0 if not search else 100,
	)


@frappe.whitelist()
def get_customer_info(customer):
	"""Profile detail plus loyalty standing for one customer."""
	doc = frappe.get_cached_doc("Customer", customer)

	info = {
		"name": doc.name,
		"customer_name": doc.customer_name,
		"email_id": doc.email_id,
		"mobile_no": doc.mobile_no,
		"image": doc.image,
		"loyalty_program": doc.loyalty_program,
		"loyalty_points": None,
		"conversion_factor": None,
		"customer_price_list": doc.default_price_list,
		"customer_group": doc.customer_group,
		"customer_type": doc.customer_type,
		"territory": doc.territory,
		"birthday": doc.get("posa_birthday"),
		"gender": doc.gender,
		"tax_id": doc.tax_id,
		"posa_discount": doc.get("posa_discount"),
		"posa_referral_code": doc.get("posa_referral_code"),
		"customer_group_price_list": frappe.db.get_value(
			"Customer Group", doc.customer_group, "default_price_list"
		),
	}

	if doc.loyalty_program:
		details = get_loyalty_program_details_with_points(
			doc.name, doc.loyalty_program, silent=True, include_expired_entry=False
		)
		info["loyalty_points"] = details.get("loyalty_points")
		info["conversion_factor"] = details.get("conversion_factor")

	return info


@frappe.whitelist()
def save_customer(pos_profile, customer_name, company, customer_id=None, **kwargs):
	"""Create or update a customer from the POS.

	Replaces the v14 `create_customer` endpoint, which took a `method` string; the
	presence of `customer_id` now decides between insert and update.
	"""
	profile = as_dict(pos_profile)
	fields = {
		"tax_id": kwargs.get("tax_id"),
		"posa_referral_code": kwargs.get("referral_code"),
		"posa_birthday": kwargs.get("birthday"),
		"customer_type": kwargs.get("customer_type") or "Individual",
		"gender": kwargs.get("gender"),
		"customer_group": kwargs.get("customer_group") or _default_customer_group(),
		"territory": kwargs.get("territory") or _default_territory(),
	}
	mobile_no = kwargs.get("mobile_no")
	email_id = kwargs.get("email_id")

	if customer_id:
		doc = frappe.get_doc("Customer", customer_id)
		doc.customer_name = customer_name
		doc.posa_referral_company = company
		for key, value in fields.items():
			# Blank is "not supplied", not "clear it". A referral code in particular is
			# the anchor for every coupon already issued against it, so a form that
			# happens not to include the field must never erase it.
			if value is None or value == "":
				continue
			doc.set(key, value)
		doc.save()

		if mobile_no is not None and mobile_no != doc.mobile_no:
			set_customer_info(doc.name, "mobile_no", mobile_no)
		if email_id is not None and email_id != doc.email_id:
			set_customer_info(doc.name, "email_id", email_id)
		return get_customer_info(doc.name)

	if not cint(profile.get("posa_allow_duplicate_customer_names")) and frappe.db.exists(
		"Customer", {"customer_name": customer_name}
	):
		frappe.throw(_("A customer named {0} already exists").format(customer_name))

	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": customer_name,
			"posa_referral_company": company,
			"mobile_no": mobile_no,
			"email_id": email_id,
			**fields,
		}
	)
	doc.insert()
	return get_customer_info(doc.name)


def _default_customer_group():
	return frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"


def _default_territory():
	return frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"


@frappe.whitelist()
def set_customer_info(customer, fieldname, value=""):
	"""Keep the customer's primary contact in step with POS edits."""
	if fieldname == "loyalty_program":
		frappe.db.set_value("Customer", customer, "loyalty_program", value)
		return

	if fieldname not in ("mobile_no", "email_id"):
		frappe.throw(_("Cannot set {0} from the POS").format(fieldname))

	contact_name = frappe.get_cached_value("Customer", customer, "customer_primary_contact")

	if contact_name:
		contact = frappe.get_doc("Contact", contact_name)
		if fieldname == "email_id":
			contact.set("email_ids", [{"email_id": value, "is_primary": 1}])
		else:
			contact.set("phone_nos", [{"phone": value, "is_primary_mobile_no": 1}])
		contact.save()
		frappe.db.set_value("Customer", customer, fieldname, value)
		return

	contact = frappe.new_doc("Contact")
	contact.first_name = frappe.get_cached_value("Customer", customer, "customer_name") or customer
	contact.is_primary_contact = 1
	contact.is_billing_contact = 1
	if fieldname == "mobile_no":
		contact.add_phone(value, is_primary_mobile_no=1, is_primary_phone=1)
	else:
		contact.add_email(value, is_primary=1)
	contact.append("links", {"link_doctype": "Customer", "link_name": customer})
	contact.flags.ignore_mandatory = True
	contact.insert()
	frappe.db.set_value("Customer", customer, "customer_primary_contact", contact.name)


@frappe.whitelist()
def get_customer_addresses(customer):
	"""Addresses linked to a customer."""
	address = frappe.qb.DocType("Address")
	link = frappe.qb.DocType("Dynamic Link")
	return (
		frappe.qb.from_(address)
		.inner_join(link)
		.on(address.name == link.parent)
		.select(
			address.name,
			address.address_title,
			address.address_line1,
			address.address_line2,
			address.city,
			address.state,
			address.pincode,
			address.country,
			address.address_type,
		)
		.where(link.link_doctype == "Customer")
		.where(link.link_name == customer)
		.where(address.disabled == 0)
		.orderby(address.name)
		.run(as_dict=True)
	)


@frappe.whitelist()
def make_address(args):
	"""Create a shipping address linked to a customer."""
	args = as_dict(args)
	if not args.get("customer"):
		frappe.throw(_("Customer is required"))

	address = frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": args.get("address_title") or args.get("name") or args.get("customer"),
			"address_line1": args.get("address_line1"),
			"address_line2": args.get("address_line2"),
			"city": args.get("city"),
			"state": args.get("state"),
			"pincode": args.get("pincode"),
			"country": args.get("country"),
			"address_type": args.get("address_type") or "Shipping",
			"links": [{"link_doctype": "Customer", "link_name": args.get("customer")}],
		}
	)
	address.insert()
	return address


@frappe.whitelist()
def get_available_credit(customer, company, currency=None):
	"""Credit the customer can spend: unapplied returns plus advance payments."""
	credit = []

	for row in frappe.get_all(
		"Sales Invoice",
		filters={
			"outstanding_amount": ["<", 0],
			"docstatus": 1,
			"is_return": 1,
			"customer": customer,
			"company": company,
			**({"currency": currency} if currency else {}),
		},
		fields=["name", "outstanding_amount", "currency"],
	):
		credit.append(
			{
				"type": "Invoice",
				"credit_origin": row.name,
				"total_credit": -row.outstanding_amount,
				"credit_to_redeem": 0,
				"currency": row.currency,
			}
		)

	for row in frappe.get_all(
		"Payment Entry",
		filters={
			"unallocated_amount": [">", 0],
			"party_type": "Customer",
			"party": customer,
			"company": company,
			"docstatus": 1,
			**({"paid_from_account_currency": currency} if currency else {}),
		},
		fields=["name", "unallocated_amount", "paid_from_account_currency"],
	):
		credit.append(
			{
				"type": "Advance",
				"credit_origin": row.name,
				"total_credit": row.unallocated_amount,
				"credit_to_redeem": 0,
				"currency": row.paid_from_account_currency,
			}
		)

	return credit


@frappe.whitelist()
def get_sales_person_names():
	return frappe.get_all(
		"Sales Person",
		filters={"enabled": 1},
		fields=["name", "sales_person_name"],
		order_by="sales_person_name",
		limit_page_length=0,
	)
