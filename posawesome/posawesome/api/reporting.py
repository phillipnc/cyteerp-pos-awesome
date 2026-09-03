"""Pure aggregation helpers for POS reports and dashboards.

The functions in this module deliberately do not import Frappe. Keeping the
accounting arithmetic separate from database access makes it possible to test
mixed-currency behaviour without a running ERPNext site.
"""

from collections import defaultdict
from datetime import time, timedelta


def _get(row, key, default=None):
	if isinstance(row, dict):
		return row.get(key, default)
	return getattr(row, key, default)


def _number(value):
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _currency(value, fallback):
	return str(value or fallback or "").strip().upper()


def _signed(value, is_return):
	number = abs(_number(value))
	return -number if is_return else number


def _posting_hour(value):
	if isinstance(value, time):
		return value.hour
	if isinstance(value, timedelta):
		return int(value.total_seconds() // 3600) % 24
	text = str(value or "").strip()
	try:
		return int(text.split(":", 1)[0]) % 24
	except (TypeError, ValueError):
		return 0


def aggregate_shift(
	invoices,
	payments,
	items,
	*,
	company_currency,
	cash_mode="Cash",
	cash_mode_by_shift=None,
	payment_entries=None,
	opening_balances=None,
):
	"""Aggregate a shift without adding unlike currencies together.

	Company KPIs use ERPNext ``base_*`` fields. Invoice-currency totals are
	grouped by currency, while tender reconciliation is grouped by physical
	tender currency and Mode of Payment.
	"""
	payment_entries = payment_entries or []
	opening_balances = opening_balances or []
	cash_mode_by_shift = cash_mode_by_shift or {}
	company_currency = _currency(company_currency, "")
	invoice_map = {_get(row, "name"): row for row in invoices}

	company = {
		"sales": 0.0,
		"returns": 0.0,
		"net_total": 0.0,
		"discount": 0.0,
	}
	currency_groups = defaultdict(
		lambda: {
			"invoice_count": 0,
			"return_count": 0,
			"sales": 0.0,
			"returns": 0.0,
			"net_total": 0.0,
			"discount": 0.0,
			"company_sales": 0.0,
			"company_returns": 0.0,
			"company_net_total": 0.0,
			"company_discount": 0.0,
		}
	)
	hourly = defaultdict(lambda: {"amount": 0.0, "count": 0})

	for invoice in invoices:
		is_return = bool(_get(invoice, "is_return"))
		currency = _currency(_get(invoice, "currency"), company_currency)
		group = currency_groups[currency]
		invoice_total = abs(_number(_get(invoice, "grand_total")))
		base_total = abs(_number(_get(invoice, "base_grand_total")))
		net_total = abs(_number(_get(invoice, "net_total")))
		base_net_total = abs(_number(_get(invoice, "base_net_total")))
		invoice_discount = abs(_number(_get(invoice, "discount_amount")))
		base_discount = abs(_number(_get(invoice, "base_discount_amount")))

		if is_return:
			group["return_count"] += 1
			group["returns"] += invoice_total
			group["net_total"] -= net_total
			group["company_returns"] += base_total
			group["company_net_total"] -= base_net_total
			company["returns"] += base_total
			company["net_total"] -= base_net_total
		else:
			group["invoice_count"] += 1
			group["sales"] += invoice_total
			group["net_total"] += net_total
			group["discount"] += invoice_discount
			group["company_sales"] += base_total
			group["company_net_total"] += base_net_total
			group["company_discount"] += base_discount
			company["sales"] += base_total
			company["net_total"] += base_net_total
			company["discount"] += base_discount
			hour = _posting_hour(_get(invoice, "posting_time"))
			hourly[hour]["amount"] += base_total
			hourly[hour]["count"] += 1

	top_items = defaultdict(lambda: {"qty": 0.0, "amount": 0.0})
	total_stock_qty = 0.0
	for item in items:
		invoice = invoice_map.get(_get(item, "parent"))
		if not invoice or bool(_get(invoice, "is_return")):
			continue
		stock_qty = abs(_number(_get(item, "stock_qty") or _get(item, "qty")))
		selling_qty = abs(_number(_get(item, "qty") or _get(item, "stock_qty")))
		total_stock_qty += stock_qty
		key = (
			_get(item, "item_code"),
			_get(item, "item_name"),
			_get(item, "stock_uom") or _get(item, "uom"),
		)
		top_items[key]["qty"] += stock_qty
		top_items[key]["amount"] += abs(
			_number(_get(item, "base_net_amount") or _get(item, "base_amount"))
		)

		price_list_rate = _number(_get(item, "price_list_rate"))
		rate = _number(_get(item, "rate"))
		base_price_list_rate = _number(_get(item, "base_price_list_rate"))
		base_rate = _number(_get(item, "base_rate"))
		invoice_currency = _currency(_get(invoice, "currency"), company_currency)
		if price_list_rate > rate:
			currency_groups[invoice_currency]["discount"] += (
				price_list_rate - rate
			) * selling_qty
		if base_price_list_rate > base_rate:
			line_discount = (base_price_list_rate - base_rate) * selling_qty
			company["discount"] += line_discount
			currency_groups[invoice_currency]["company_discount"] += line_discount

	tender_groups = defaultdict(
		lambda: {
			"opening_amount": 0.0,
			"transaction_amount": 0.0,
			"company_opening_amount": 0.0,
			"company_transaction_amount": 0.0,
		}
	)

	def tender_group(mode, currency):
		mode = str(mode or "").strip() or "Unspecified"
		currency = _currency(currency, company_currency)
		return (mode, currency), tender_groups[(mode, currency)]

	for row in opening_balances:
		key, group = tender_group(_get(row, "mode_of_payment"), _get(row, "currency"))
		amount = _number(_get(row, "amount") or _get(row, "opening_amount"))
		company_amount = _number(_get(row, "company_amount"))
		if not company_amount:
			company_amount = amount * _number(_get(row, "company_exchange_rate") or 1)
		group["opening_amount"] += amount
		group["company_opening_amount"] += company_amount

	for row in payments:
		invoice = invoice_map.get(_get(row, "parent"))
		if not invoice:
			continue
		is_return = bool(_get(invoice, "is_return"))
		invoice_currency = _currency(_get(invoice, "currency"), company_currency)
		tender_currency = _currency(_get(row, "posa_tender_currency"), invoice_currency)
		tender_amount = _get(row, "posa_tender_amount")
		if tender_amount in (None, ""):
			tender_amount = _get(row, "amount")
		company_amount = _get(row, "base_amount")
		if company_amount in (None, ""):
			company_amount = _number(_get(row, "amount")) * _number(
				_get(invoice, "conversion_rate") or 1
			)
		_, group = tender_group(_get(row, "mode_of_payment"), tender_currency)
		group["transaction_amount"] += _signed(tender_amount, is_return)
		group["company_transaction_amount"] += _signed(company_amount, is_return)

	for entry in payment_entries:
		currency = _currency(
			_get(entry, "paid_to_account_currency") or _get(entry, "currency"),
			company_currency,
		)
		amount = _get(entry, "received_amount")
		if amount in (None, ""):
			amount = _get(entry, "paid_amount")
		company_amount = _get(entry, "base_received_amount")
		if company_amount in (None, ""):
			company_amount = _number(amount) * _number(_get(entry, "company_exchange_rate") or 1)
		_, group = tender_group(_get(entry, "mode_of_payment"), currency)
		group["transaction_amount"] += _number(amount)
		group["company_transaction_amount"] += _number(company_amount)

	# The SPA presents change in the invoice currency. Record that physical cash
	# movement explicitly instead of silently subtracting it from an unrelated
	# foreign-currency tender row.
	for invoice in invoices:
		if bool(_get(invoice, "is_return")):
			continue
		change = abs(_number(_get(invoice, "change_amount")))
		if not change:
			continue
		currency = _currency(_get(invoice, "currency"), company_currency)
		base_change = abs(_number(_get(invoice, "base_change_amount")))
		if not base_change:
			base_change = change * _number(_get(invoice, "conversion_rate") or 1)
		change_mode = cash_mode_by_shift.get(
			_get(invoice, "posa_pos_opening_shift"),
			cash_mode,
		)
		_, group = tender_group(change_mode, currency)
		group["transaction_amount"] -= change
		group["company_transaction_amount"] -= base_change

	payment_mix = []
	for (mode, currency), values in tender_groups.items():
		expected = values["opening_amount"] + values["transaction_amount"]
		company_expected = (
			values["company_opening_amount"] + values["company_transaction_amount"]
		)
		payment_mix.append(
			{
				"key": f"{mode}::{currency}",
				"mode_of_payment": mode,
				"currency": currency,
				**values,
				"expected_amount": expected,
				"company_expected_amount": company_expected,
				# Compatibility with older clients.
				"amount": expected,
			}
		)
	payment_mix.sort(key=lambda row: (row["mode_of_payment"], row["currency"]))

	currency_totals = []
	for currency, values in sorted(currency_groups.items()):
		currency_totals.append(
			{
				"currency": currency,
				**values,
				"net_sales": values["sales"] - values["returns"],
				"company_net_sales": values["company_sales"] - values["company_returns"],
			}
		)

	item_rows = [
		{
			"item_code": key[0],
			"item_name": key[1],
			"stock_uom": key[2],
			**values,
		}
		for key, values in top_items.items()
	]
	item_rows.sort(key=lambda row: (-row["amount"], str(row["item_code"])))

	hourly_rows = [
		{"hour": hour, **values}
		for hour, values in sorted(hourly.items())
	]

	invoice_count = sum(row["invoice_count"] for row in currency_totals)
	return_count = sum(row["return_count"] for row in currency_totals)
	return {
		"company_currency": company_currency,
		"invoice_count": invoice_count,
		"return_count": return_count,
		"grand_total": company["sales"],
		"total_returned": company["returns"],
		"net_sales": company["sales"] - company["returns"],
		"net_total": company["net_total"],
		"total_discount": company["discount"],
		"average_basket": company["sales"] / invoice_count if invoice_count else 0.0,
		"total_qty": total_stock_qty,
		"currency_totals": currency_totals,
		"payment_mix": payment_mix,
		"top_items": item_rows[:8],
		"hourly": hourly_rows,
	}
