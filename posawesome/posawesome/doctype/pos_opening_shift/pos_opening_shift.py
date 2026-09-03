# Copyright (c) 2020, Youssef Restom and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt

from posawesome.posawesome.api.currency import _rate, build_currency_context
from posawesome.posawesome.api.status_updater import StatusUpdater


class POSOpeningShift(StatusUpdater):
	def validate(self):
		self.validate_pos_profile_and_cashier()
		self.validate_opening_balances()
		self.set_status()

	def validate_pos_profile_and_cashier(self):
		if self.company != frappe.db.get_value("POS Profile", self.pos_profile, "company"):
			frappe.throw(_(f"POS Profile {self.pos_profile} does not belongs to company {self.company}"))

		if not cint(frappe.db.get_value("User", self.user, "enabled")):
			frappe.throw(_(f"User {self.user} has been disabled. Please select valid user/cashier"))

	def validate_opening_balances(self):
		context = build_currency_context(self.pos_profile, posting_date=self.posting_date)
		methods = {
			row.get("mode_of_payment"): row
			for row in context.get("payment_methods") or []
		}
		seen = set()
		for row in self.get("balance_details") or []:
			if row.mode_of_payment in seen or row.mode_of_payment not in methods:
				frappe.throw(
					_("Invalid or duplicate opening Mode of Payment: {0}").format(
						row.mode_of_payment or _("blank")
					)
				)
			seen.add(row.mode_of_payment)
			if flt(row.amount) < 0:
				frappe.throw(
					_("Opening amount for {0} cannot be negative").format(row.mode_of_payment)
				)
			row.currency = methods[row.mode_of_payment].get("currency") or context["invoice_currency"]
			row.company_exchange_rate = _rate(
				row.currency,
				context["company_currency"],
				self.posting_date,
			)
			row.company_amount = flt(row.amount) * row.company_exchange_rate

	def on_submit(self):
		self.set_status(update=True)
