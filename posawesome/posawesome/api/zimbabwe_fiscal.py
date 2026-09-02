"""Zimbabwe FDMS fiscalisation with direct and external-provider adapters."""

import base64
import hashlib
import io
import json
from collections import defaultdict
from pathlib import Path

import frappe
import requests
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime

from posawesome.posawesome.api.fiscal_utils import (
	fiscal_day_signature_content,
	receipt_signature_content,
)


TEST_URL = "https://fdmsapitest.zimra.co.zw"
PRODUCTION_URL = "https://fdmsapi.zimra.co.zw"
MONEY_TYPES = {"Cash", "Card", "MobileWallet", "Coupon", "Credit"}


def _json(value, default=None):
	if not value:
		return default if default is not None else {}
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		frappe.throw(_("Fiscal device configuration contains invalid JSON"))


def _device_for_profile(pos_profile, lock=False):
	name = frappe.db.get_value(
		"Zimbabwe Fiscal Device",
		{"pos_profile": pos_profile, "enabled": 1},
		"name",
	)
	if not name:
		return None
	if lock:
		frappe.db.sql(
			"select name from `tabZimbabwe Fiscal Device` where name=%s for update",
			name,
		)
	return frappe.get_doc("Zimbabwe Fiscal Device", name)


def _private_file(value):
	if not value:
		frappe.throw(_("Fiscal certificate/key path is not configured"))
	path = Path(value)
	if path.is_absolute() or ".." in path.parts:
		frappe.throw(_("Fiscal certificate/key path must be relative to the private site directory"))
	resolved = Path(frappe.get_site_path("private", *path.parts)).resolve()
	private_root = Path(frappe.get_site_path("private")).resolve()
	if private_root not in resolved.parents:
		frappe.throw(_("Fiscal certificate/key path escapes the private site directory"))
	if not resolved.is_file():
		frappe.throw(_("Fiscal certificate/key file {0} does not exist").format(value))
	return str(resolved)


def _fdms_headers(device):
	return {
		"DeviceModelName": device.device_model_name,
		"DeviceModelVersionNo": device.device_model_version,
		"Content-Type": "application/json",
	}


def _direct_request(device, method, action, payload=None):
	base = TEST_URL if device.environment == "Test" else PRODUCTION_URL
	url = f"{base}/Device/v1/{int(device.device_id)}/{action}"
	response = requests.request(
		method,
		url,
		headers=_fdms_headers(device),
		json=payload,
		cert=(_private_file(device.certificate_path), _private_file(device.private_key_path)),
		timeout=45,
	)
	if response.status_code >= 400:
		try:
			detail = response.json()
		except ValueError:
			detail = response.text
		frappe.throw(
			_("FDMS {0} failed with HTTP {1}: {2}").format(
				action, response.status_code, detail
			)
		)
	return response.json()


def _external_request(device, action, payload):
	headers = {"Content-Type": "application/json"}
	headers.update(_json(device.provider_headers_json))
	token = device.get_password("external_token", raise_exception=False)
	if token:
		headers.setdefault("Authorization", f"Bearer {token}")
	response = requests.post(
		device.external_endpoint,
		headers=headers,
		json={
			"action": action,
			"device": device.name,
			"device_id": device.device_id,
			"payload": payload,
		},
		timeout=45,
	)
	if response.status_code >= 400:
		frappe.throw(
			_("Fiscal provider failed with HTTP {0}: {1}").format(
				response.status_code, response.text
			)
		)
	return response.json()


def _call(device, method, action, payload):
	if device.provider == "External Provider":
		return _external_request(device, action, payload)
	return _direct_request(device, method, action, payload)


def _result(response):
	"""Unwrap common external-provider response envelopes."""
	if not isinstance(response, dict):
		frappe.throw(_("Fiscal provider returned an invalid response"))
	for key in ("data", "result"):
		value = response.get(key)
		if isinstance(value, dict):
			return value
	return response


def _format_datetime(value):
	return get_datetime(value).strftime("%Y-%m-%dT%H:%M:%S")


def _sign(device, content):
	from cryptography.hazmat.primitives import hashes, serialization
	from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
	from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

	message = content.encode("utf-8")
	digest = hashlib.sha256(message).digest()
	with open(_private_file(device.private_key_path), "rb") as handle:
		key = serialization.load_pem_private_key(handle.read(), password=None)
	if isinstance(key, rsa.RSAPrivateKey):
		signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
	elif isinstance(key, ec.EllipticCurvePrivateKey):
		signature = key.sign(digest, ec.ECDSA(Prehashed(hashes.SHA256())))
	else:
		frappe.throw(_("Unsupported fiscal private-key type"))
	return {
		"hash": base64.b64encode(digest).decode(),
		"signature": base64.b64encode(signature).decode(),
		"_signature_bytes": signature,
	}


def _tax_percent(doc, row):
	try:
		item_rates = json.loads(row.get("item_tax_rate") or "{}")
	except (TypeError, ValueError):
		item_rates = {}
	if item_rates:
		return flt(next(iter(item_rates.values())))
	for tax in doc.get("taxes") or []:
		if tax.charge_type == "On Net Total":
			return flt(tax.rate)
	return 0.0


def _tax_id(device, percent):
	mapping = _json(device.tax_mapping_json)
	for key in (str(percent), f"{percent:g}", f"{percent:.1f}", f"{percent:.2f}"):
		if key in mapping:
			return int(mapping[key])
	frappe.throw(
		_("No FDMS tax ID is mapped for tax rate {0}% on {1}").format(percent, device.name)
	)


def _money_type(device, payment):
	mapping = _json(device.payment_mapping_json)
	candidates = (
		payment.get("mode_of_payment"),
		payment.get("type"),
		str(payment.get("mode_of_payment") or "").lower(),
	)
	for candidate in candidates:
		if candidate in mapping:
			value = mapping[candidate]
			if value in MONEY_TYPES:
				return value
	mode = str(payment.get("mode_of_payment") or "").lower()
	if "cash" in mode:
		return "Cash"
	if "card" in mode or payment.get("type") == "Bank":
		return "Card"
	if "mobile" in mode or "ecocash" in mode or "mpesa" in mode:
		return "MobileWallet"
	return "Credit"


def _receipt_date(doc):
	return _format_datetime(f"{doc.posting_date} {doc.posting_time or '00:00:00'}")


def _build_receipt(device, doc, global_no, counter):
	company = frappe.get_cached_doc("Company", doc.company)
	customer = frappe.get_cached_doc("Customer", doc.customer)
	is_credit = bool(doc.is_return)
	receipt_type = "CreditNote" if is_credit else "FiscalInvoice"
	sign = -1 if is_credit else 1
	tax_inclusive = bool(frappe.get_cached_value("POS Profile", doc.pos_profile, "posa_tax_inclusive"))

	lines = []
	tax_groups = defaultdict(lambda: {"taxAmount": 0.0, "salesAmountWithTax": 0.0})
	for index, row in enumerate(doc.get("items") or [], start=1):
		percent = _tax_percent(doc, row)
		tax_id = _tax_id(device, percent)
		hs_code = frappe.get_cached_value(
			"Item", row.item_code, "posa_hs_code"
		) or frappe.get_cached_value("Item", row.item_code, "gst_hsn_code")
		if company.get("posa_zimra_vat_number") and not hs_code:
			frappe.throw(_("Zimbabwe HS Code is required for item {0}").format(row.item_code))

		qty = abs(flt(row.qty))
		unit_price = sign * abs(flt(row.rate))
		line_total = sign * abs(flt(row.amount))
		line = {
			"receiptLineType": "Sale",
			"receiptLineNo": index,
			"receiptLineName": row.item_name[:200],
			"receiptLinePrice": round(unit_price, 6),
			"receiptLineQuantity": round(qty, 6),
			"receiptLineTotal": round(line_total, 2),
			"taxPercent": round(percent, 2),
			"taxID": tax_id,
		}
		if hs_code:
			line["receiptLineHSCode"] = str(hs_code)
		lines.append(line)

		if tax_inclusive:
			tax_amount = line_total * percent / (100 + percent) if percent else 0
			sales_with_tax = line_total
		else:
			tax_amount = line_total * percent / 100
			sales_with_tax = line_total + tax_amount
		key = (tax_id, percent)
		tax_groups[key]["taxAmount"] += tax_amount
		tax_groups[key]["salesAmountWithTax"] += sales_with_tax

	taxes = [
		{
			"taxPercent": round(percent, 2),
			"taxID": tax_id,
			"taxAmount": round(values["taxAmount"], 2),
			"salesAmountWithTax": round(values["salesAmountWithTax"], 2),
		}
		for (tax_id, percent), values in sorted(tax_groups.items())
	]

	total = sign * abs(flt(doc.rounded_total or doc.grand_total))
	payments = []
	allocated = 0.0
	for payment in doc.get("payments") or []:
		amount = sign * abs(flt(payment.amount))
		if not amount:
			continue
		remaining = total - allocated
		if abs(amount) > abs(remaining):
			amount = remaining
		if not amount:
			break
		payments.append(
			{
				"moneyTypeCode": _money_type(device, payment),
				"paymentAmount": round(amount, 2),
			}
		)
		allocated += amount
	if round(total - allocated, 2):
		payments.append(
			{
				"moneyTypeCode": "Credit",
				"paymentAmount": round(total - allocated, 2),
			}
		)

	receipt = {
		"receiptType": receipt_type,
		"receiptCurrency": doc.currency.upper(),
		"receiptCounter": counter,
		"receiptGlobalNo": global_no,
		"invoiceNo": doc.name,
		"receiptDate": _receipt_date(doc),
		"receiptLinesTaxInclusive": tax_inclusive,
		"receiptLines": lines,
		"receiptTaxes": taxes,
		"receiptPayments": payments,
		"receiptTotal": round(total, 2),
		"receiptPrintForm": "Receipt48",
		"username": doc.owner,
		"userNameSurname": frappe.get_cached_value("User", doc.owner, "full_name") or doc.owner,
	}
	if customer.get("posa_zimra_tin"):
		receipt["buyerData"] = {
			"buyerRegisterName": customer.customer_name,
			"buyerTIN": customer.posa_zimra_tin,
			**(
				{"VATNumber": customer.posa_zimra_vat_number}
				if customer.get("posa_zimra_vat_number")
				else {}
			),
		}
	if is_credit:
		original = frappe.get_cached_doc("Sales Invoice", doc.return_against)
		if not original.get("posa_fiscal_receipt_id"):
			frappe.throw(_("The original invoice was not accepted by FDMS"))
		receipt["receiptNotes"] = doc.get("remarks") or f"Credit note against {original.name}"
		receipt["creditDebitNote"] = {"receiptID": int(original.posa_fiscal_receipt_id)}
	return receipt


def _receipt_signature_content(device, receipt):
	return receipt_signature_content(
		device.device_id,
		receipt,
		device.last_receipt_hash,
	)


def _qr_values(device, receipt, signature_bytes):
	qr_data = hashlib.md5(signature_bytes).hexdigest()[:16]
	date = get_datetime(receipt["receiptDate"]).strftime("%d%m%Y")
	url = (
		f"{device.qr_url.rstrip('/')}/"
		f"{int(device.device_id):010d}{date}{int(receipt['receiptGlobalNo']):010d}{qr_data}"
	)
	code = "-".join(qr_data[index : index + 4] for index in range(0, 16, 4))
	return url, code


def _signature_bytes(signature):
	if not isinstance(signature, dict) or not signature.get("signature"):
		return b""
	try:
		return base64.b64decode(signature["signature"], validate=True)
	except (TypeError, ValueError):
		return b""


def _provider_qr_values(device, receipt, response, signature):
	qr_url = (
		response.get("receiptQrUrl")
		or response.get("receiptQRUrl")
		or response.get("qrUrl")
		or response.get("qr_url")
	)
	verification_code = (
		response.get("receiptVerificationCode")
		or response.get("verificationCode")
		or response.get("verification_code")
	)
	signature_bytes = _signature_bytes(signature)
	if (not qr_url or not verification_code) and signature_bytes and device.qr_url:
		calculated_url, calculated_code = _qr_values(device, receipt, signature_bytes)
		qr_url = qr_url or calculated_url
		verification_code = verification_code or calculated_code
	return qr_url or "", verification_code or ""


def _update_counters(device, receipt):
	counters = _json(device.fiscal_counters_json, {})
	prefix = "CreditNote" if receipt["receiptType"] == "CreditNote" else "Sale"
	for tax in receipt["receiptTaxes"]:
		for counter_type, value in (
			(f"{prefix}ByTax", tax["salesAmountWithTax"]),
			(f"{prefix}TaxByTax", tax["taxAmount"]),
		):
			key = "|".join(
				[
					counter_type,
					receipt["receiptCurrency"],
					str(tax["taxID"]),
					f"{flt(tax.get('taxPercent')):.2f}",
				]
			)
			counters[key] = round(flt(counters.get(key)) + flt(value), 2)
	for payment in receipt["receiptPayments"]:
		key = "|".join(
			["BalanceByMoneyType", receipt["receiptCurrency"], payment["moneyTypeCode"]]
		)
		counters[key] = round(
			flt(counters.get(key)) + flt(payment["paymentAmount"]), 2
		)
	device.fiscal_counters_json = json.dumps(counters, sort_keys=True)


def open_day(device):
	if device.fiscal_day_status in ("FiscalDayOpened", "FiscalDayCloseFailed"):
		return device.fiscal_day_no
	opened = now_datetime()
	next_no = int(device.fiscal_day_no or 0) + 1
	payload = {
		"deviceID": int(device.device_id),
		"fiscalDayOpened": _format_datetime(opened),
		"fiscalDayNo": next_no,
	}
	response = _call(device, "POST", "OpenDay", payload)
	response = _result(response)
	device.fiscal_day_no = int(response.get("fiscalDayNo") or next_no)
	device.fiscal_day_opened = opened
	device.fiscal_day_status = "FiscalDayOpened"
	device.receipt_counter = 0
	device.fiscal_counters_json = "{}"
	device.save(ignore_permissions=True)
	return device.fiscal_day_no


def fiscalise_invoice(doc, method=None):
	"""Sales Invoice on-submit hook."""
	device = _device_for_profile(doc.pos_profile, lock=True)
	if not device:
		return
	if doc.get("posa_fiscal_status") == "Accepted":
		return

	try:
		open_day(device)
		global_no = int(device.receipt_global_no or 0) + 1
		counter = int(device.receipt_counter or 0) + 1
		receipt = _build_receipt(device, doc, global_no, counter)
		if device.provider == "Direct FDMS":
			signature = _sign(device, _receipt_signature_content(device, receipt))
			signature.pop("_signature_bytes")
			receipt["receiptDeviceSignature"] = signature
		response = _call(
			device,
			"POST",
			"SubmitReceipt",
			{"deviceID": int(device.device_id), "receipt": receipt},
		)
		response = _result(response)
		signature = receipt.get("receiptDeviceSignature") or response.get(
			"receiptDeviceSignature"
		)
		if not signature or not signature.get("hash"):
			frappe.throw(
				_("Fiscal provider did not return a valid receipt device signature")
			)
		qr_url, verification_code = _provider_qr_values(
			device, receipt, response, signature
		)

		device.receipt_global_no = global_no
		device.receipt_counter = counter
		device.last_receipt_hash = signature["hash"]
		_update_counters(device, receipt)
		device.save(ignore_permissions=True)

		values = {
			"posa_fiscal_status": "Accepted",
			"posa_fiscal_receipt_id": str(response.get("receiptID") or ""),
			"posa_fiscal_device_id": int(device.device_id),
			"posa_fiscal_day_no": int(device.fiscal_day_no),
			"posa_fiscal_receipt_global_no": global_no,
			"posa_fiscal_qr_url": qr_url,
			"posa_fiscal_verification_code": verification_code,
			"posa_fiscal_receipt_hash": signature["hash"],
			"posa_fiscal_server_signature": json.dumps(
				response.get("receiptServerSignature") or {}, sort_keys=True
			),
			"posa_fiscal_error": None,
		}
		frappe.db.set_value("Sales Invoice", doc.name, values, update_modified=False)
		doc.update(values)
	except Exception as error:
		message = str(error)[:500]
		frappe.db.set_value(
			"Sales Invoice",
			doc.name,
			{"posa_fiscal_status": "Failed", "posa_fiscal_error": message},
			update_modified=False,
		)
		if device.block_on_failure:
			raise
		frappe.log_error(title=f"Fiscalisation failed: {doc.name}", message=frappe.get_traceback())


def _counter_rows(device):
	rows = []
	for key, value in _json(device.fiscal_counters_json, {}).items():
		if not flt(value):
			continue
		parts = key.split("|")
		row = {
			"fiscalCounterType": parts[0],
			"fiscalCounterCurrency": parts[1],
			"fiscalCounterValue": flt(value),
		}
		if parts[0] == "BalanceByMoneyType":
			row["fiscalCounterMoneyType"] = parts[2]
		else:
			row["fiscalCounterTaxID"] = int(parts[2])
			row["fiscalCounterTaxPercent"] = flt(parts[3])
		rows.append(row)
	return rows


@frappe.whitelist()
def close_day(device_name):
	device = frappe.get_doc("Zimbabwe Fiscal Device", device_name)
	device.check_permission("write")
	if device.fiscal_day_status not in ("FiscalDayOpened", "FiscalDayCloseFailed"):
		return {"status": device.fiscal_day_status}
	counters = _counter_rows(device)
	if not device.fiscal_day_opened:
		frappe.throw(_("Fiscal day opening date is missing"))
	signature_content = fiscal_day_signature_content(
		device.device_id,
		device.fiscal_day_no,
		get_datetime(device.fiscal_day_opened),
		counters,
	)
	payload = {
		"deviceID": int(device.device_id),
		"fiscalDayNo": int(device.fiscal_day_no),
		"fiscalDayCounters": counters,
		"receiptCounter": int(device.receipt_counter),
	}
	if device.provider == "Direct FDMS":
		signature = _sign(device, signature_content)
		signature.pop("_signature_bytes")
		payload["fiscalDayDeviceSignature"] = signature
	response = _call(device, "POST", "CloseDay", payload)
	response = _result(response)
	device.fiscal_day_status = response.get("fiscalDayStatus") or "FiscalDayCloseInitiated"
	device.save(ignore_permissions=True)
	return response


@frappe.whitelist()
def get_device_configuration(device_name):
	"""Retrieve the registered taxpayer/device configuration from the connector."""
	device = frappe.get_doc("Zimbabwe Fiscal Device", device_name)
	device.check_permission("write")
	response = _result(_call(device, "GET", "GetConfig", {}))
	qr_url = response.get("qrUrl") or response.get("receiptQrUrl")
	if qr_url:
		device.qr_url = qr_url
		device.save(ignore_permissions=True)
	return response


@frappe.whitelist()
def refresh_device_status(device_name):
	"""Refresh the authoritative FDMS fiscal-day status."""
	device = frappe.get_doc("Zimbabwe Fiscal Device", device_name)
	device.check_permission("write")
	response = _result(_call(device, "GET", "GetStatus", {}))
	for fieldname, response_key in (
		("fiscal_day_status", "fiscalDayStatus"),
		("fiscal_day_no", "fiscalDayNo"),
		("fiscal_day_opened", "fiscalDayOpened"),
	):
		if response.get(response_key) is not None:
			device.set(fieldname, response[response_key])
	device.save(ignore_permissions=True)
	return response


def close_day_for_pos_shift(doc, method=None):
	opening = frappe.get_cached_doc("POS Opening Shift", doc.pos_opening_shift)
	device = _device_for_profile(opening.pos_profile)
	if device and device.close_with_pos_shift:
		close_day(device.name)


def get_qr_data_uri(value):
	"""Jinja helper used by the bundled receipt format."""
	if not value:
		return ""
	try:
		import qrcode
	except ImportError:
		return ""
	image = qrcode.make(value)
	buffer = io.BytesIO()
	image.save(buffer, format="PNG")
	return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
