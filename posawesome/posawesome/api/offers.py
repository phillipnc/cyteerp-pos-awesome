"""POS Offers, coupons and referral rewards."""

import frappe
from frappe.utils import nowdate

from posawesome.posawesome.doctype.pos_coupon.pos_coupon import check_coupon_code


@frappe.whitelist()
def get_offers(profile):
	"""Offers currently in force for a POS profile.

	An offer applies when its company matches and its profile / warehouse / validity
	window either matches or is left blank (blank meaning "any").
	"""
	pos_profile = frappe.get_cached_doc("POS Profile", profile)
	offer = frappe.qb.DocType("POS Offer")
	today = nowdate()

	blank_or = lambda field, value: field.isnull() | (field == "") | (field == value)  # noqa: E731

	return (
		frappe.qb.from_(offer)
		.select("*")
		.where(offer.disable == 0)
		.where(offer.company == pos_profile.company)
		.where(blank_or(offer.pos_profile, profile))
		.where(blank_or(offer.warehouse, pos_profile.warehouse))
		.where(offer.valid_from.isnull() | (offer.valid_from <= today))
		.where(offer.valid_upto.isnull() | (offer.valid_upto >= today))
		.run(as_dict=True)
	)


@frappe.whitelist()
def get_pos_coupon(coupon, customer, company):
	"""Validate a coupon code and return the offer it unlocks."""
	return check_coupon_code(coupon, customer, company)


@frappe.whitelist()
def get_active_gift_coupons(customer, company):
	"""Unused gift-card codes held by a customer."""
	return frappe.get_all(
		"POS Coupon",
		filters={"company": company, "coupon_type": "Gift Card", "customer": customer, "used": 0},
		pluck="coupon_code",
	)
