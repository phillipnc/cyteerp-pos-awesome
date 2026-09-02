"""Zimbabwe fiscal device configuration."""

import json

import frappe
from frappe import _
from frappe.model.document import Document


class ZimbabweFiscalDevice(Document):
	def validate(self):
		for fieldname in ("tax_mapping_json", "payment_mapping_json", "provider_headers_json"):
			value = self.get(fieldname)
			if not value:
				continue
			try:
				parsed = json.loads(value)
			except (TypeError, ValueError):
				frappe.throw(_("{0} must contain valid JSON").format(self.meta.get_label(fieldname)))
			if not isinstance(parsed, dict):
				frappe.throw(_("{0} must be a JSON object").format(self.meta.get_label(fieldname)))

		if self.provider == "Direct FDMS":
			for fieldname in (
				"device_id",
				"device_model_name",
				"device_model_version",
				"certificate_path",
				"private_key_path",
			):
				if not self.get(fieldname):
					frappe.throw(_("{0} is required for Direct FDMS").format(self.meta.get_label(fieldname)))
		elif self.provider == "External Provider" and not self.external_endpoint:
			frappe.throw(_("External Endpoint is required for an external fiscalisation provider"))
