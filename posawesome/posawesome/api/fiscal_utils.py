"""Pure Zimbabwe FDMS formatting helpers.

These functions deliberately do not import Frappe so the signature rules can be
tested outside a bench and checked against ZIMRA's published vectors.
"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP


def cents(value):
	"""Convert a monetary value to the integer-cent representation used by FDMS."""
	return str(
		int(
			(Decimal(str(value or 0)) * Decimal("100")).quantize(
				Decimal("1"),
				rounding=ROUND_HALF_UP,
			)
		)
	)


def tax_percent(value):
	"""FDMS signs a missing exempt percentage as blank and numeric rates to 2 dp."""
	if value is None or value == "":
		return ""
	return f"{Decimal(str(value)):.2f}"


def receipt_signature_content(device_id, receipt, previous_receipt_hash=None):
	parts = [
		str(int(device_id)),
		str(receipt["receiptType"]).upper(),
		str(receipt["receiptCurrency"]).upper(),
		str(int(receipt["receiptGlobalNo"])),
		str(receipt["receiptDate"]),
		cents(receipt["receiptTotal"]),
	]
	for row in sorted(
		receipt.get("receiptTaxes") or [],
		key=lambda value: (
			int(value["taxID"]),
			str(value.get("taxCode") or ""),
		),
	):
		parts.extend(
			[
				str(row.get("taxCode") or ""),
				tax_percent(row.get("taxPercent")),
				cents(row["taxAmount"]),
				cents(row["salesAmountWithTax"]),
			]
		)
	if previous_receipt_hash and int(receipt.get("receiptCounter") or 0) > 1:
		parts.append(str(previous_receipt_hash))
	return "".join(parts)


def fiscal_day_signature_content(device_id, fiscal_day_no, fiscal_day_opened, counters):
	if isinstance(fiscal_day_opened, datetime):
		day = fiscal_day_opened.strftime("%Y-%m-%d")
	else:
		day = str(fiscal_day_opened)[:10]
	parts = [str(int(device_id)), str(int(fiscal_day_no)), day]
	for row in sorted(
		(value for value in counters if Decimal(str(value.get("fiscalCounterValue") or 0))),
		key=lambda value: (
			str(value["fiscalCounterType"]),
			str(value["fiscalCounterCurrency"]),
			int(value.get("fiscalCounterTaxID") or 0),
			str(value.get("fiscalCounterMoneyType") or ""),
		),
	):
		parts.extend(
			[
				str(row["fiscalCounterType"]).upper(),
				str(row["fiscalCounterCurrency"]).upper(),
				(
					tax_percent(row.get("fiscalCounterTaxPercent"))
					if row.get("fiscalCounterTaxID") is not None
					else str(row.get("fiscalCounterMoneyType") or "").upper()
				),
				cents(row["fiscalCounterValue"]),
			]
		)
	return "".join(parts)
