import unittest
from datetime import timedelta

from posawesome.posawesome.api.reporting import (
	aggregate_customer_performance,
	aggregate_item_performance,
	aggregate_sales_performance,
	aggregate_shift,
	build_payment_status_rows,
)


class ShiftReportingTest(unittest.TestCase):
	def test_discounts_use_selling_qty_and_change_uses_shift_cash_mode(self):
		result = aggregate_shift(
			[
				{
					"name": "SINV-1",
					"posa_pos_opening_shift": "SHIFT-1",
					"is_return": 0,
					"currency": "USD",
					"conversion_rate": 1,
					"grand_total": 18,
					"base_grand_total": 18,
					"net_total": 18,
					"base_net_total": 18,
					"change_amount": 2,
					"base_change_amount": 2,
				}
			],
			[
				{
					"parent": "SINV-1",
					"mode_of_payment": "Cash USD",
					"amount": 20,
					"base_amount": 20,
					"posa_tender_currency": "USD",
					"posa_tender_amount": 20,
				}
			],
			[
				{
					"parent": "SINV-1",
					"item_code": "CASE",
					"item_name": "Case",
					"qty": 2,
					"stock_qty": 24,
					"stock_uom": "Nos",
					"price_list_rate": 10,
					"rate": 9,
					"base_price_list_rate": 10,
					"base_rate": 9,
					"base_net_amount": 18,
				}
			],
			company_currency="USD",
			cash_mode_by_shift={"SHIFT-1": "Cash USD"},
		)

		self.assertEqual(result["total_qty"], 24)
		self.assertEqual(result["total_discount"], 2)
		self.assertEqual(result["currency_totals"][0]["discount"], 2)
		self.assertEqual(result["payment_mix"][0]["key"], "Cash USD::USD")
		self.assertEqual(result["payment_mix"][0]["transaction_amount"], 18)

	def test_mixed_currency_totals_and_physical_tender_stay_separate(self):
		invoices = [
			{
				"name": "SINV-USD",
				"is_return": 0,
				"currency": "USD",
				"conversion_rate": 1,
				"grand_total": 100,
				"base_grand_total": 100,
				"net_total": 95,
				"base_net_total": 95,
				"discount_amount": 5,
				"base_discount_amount": 5,
				"change_amount": 10,
				"base_change_amount": 10,
				"posting_time": "09:15:00",
			},
			{
				"name": "SINV-ZWG",
				"is_return": 0,
				"currency": "ZWG",
				"conversion_rate": 1 / 14,
				"grand_total": 1400,
				"base_grand_total": 100,
				"net_total": 1330,
				"base_net_total": 95,
				"discount_amount": 70,
				"base_discount_amount": 5,
				"change_amount": 0,
				"base_change_amount": 0,
				"posting_time": timedelta(hours=10, minutes=20),
			},
			{
				"name": "SINV-RETURN",
				"is_return": 1,
				"currency": "USD",
				"conversion_rate": 1,
				"grand_total": -20,
				"base_grand_total": -20,
				"net_total": -18,
				"base_net_total": -18,
				"discount_amount": 0,
				"base_discount_amount": 0,
				"posting_time": "11:00:00",
			},
		]
		payments = [
			{
				"parent": "SINV-USD",
				"mode_of_payment": "Cash",
				"amount": 120,
				"base_amount": 120,
				"posa_tender_currency": "USD",
				"posa_tender_amount": 120,
			},
			{
				"parent": "SINV-ZWG",
				"mode_of_payment": "EcoCash",
				"amount": 1400,
				"base_amount": 100,
				"posa_tender_currency": "ZWG",
				"posa_tender_amount": 1400,
			},
			{
				"parent": "SINV-RETURN",
				"mode_of_payment": "Cash",
				"amount": -20,
				"base_amount": -20,
				"posa_tender_currency": "USD",
				"posa_tender_amount": -20,
			},
		]
		items = [
			{
				"parent": "SINV-USD",
				"item_code": "ITEM-1",
				"item_name": "Item One",
				"stock_qty": 2,
				"stock_uom": "Nos",
				"price_list_rate": 60,
				"rate": 50,
				"base_price_list_rate": 60,
				"base_rate": 50,
				"base_net_amount": 95,
			},
			{
				"parent": "SINV-ZWG",
				"item_code": "ITEM-1",
				"item_name": "Item One",
				"stock_qty": 2,
				"stock_uom": "Nos",
				"price_list_rate": 700,
				"rate": 650,
				"base_price_list_rate": 50,
				"base_rate": 46.4285714286,
				"base_net_amount": 95,
			},
			{
				"parent": "SINV-RETURN",
				"item_code": "ITEM-1",
				"item_name": "Item One",
				"stock_qty": -1,
				"stock_uom": "Nos",
				"base_net_amount": -18,
			},
		]

		result = aggregate_shift(
			invoices,
			payments,
			items,
			company_currency="USD",
			cash_mode="Cash",
			payment_entries=[
				{
					"mode_of_payment": "Card",
					"paid_to_account_currency": "USD",
					"received_amount": 30,
					"base_received_amount": 30,
				}
			],
			opening_balances=[
				{
					"mode_of_payment": "Cash",
					"currency": "USD",
					"amount": 50,
					"company_amount": 50,
				}
			],
		)

		self.assertEqual(result["company_currency"], "USD")
		self.assertEqual(result["invoice_count"], 2)
		self.assertEqual(result["return_count"], 1)
		self.assertAlmostEqual(result["grand_total"], 200)
		self.assertAlmostEqual(result["total_returned"], 20)
		self.assertAlmostEqual(result["net_sales"], 180)
		self.assertAlmostEqual(result["net_total"], 172)
		self.assertAlmostEqual(result["total_qty"], 4)
		self.assertAlmostEqual(result["total_discount"], 37.1428571428)

		currencies = {row["currency"]: row for row in result["currency_totals"]}
		self.assertAlmostEqual(currencies["USD"]["net_sales"], 80)
		self.assertAlmostEqual(currencies["ZWG"]["net_sales"], 1400)
		self.assertAlmostEqual(currencies["USD"]["company_net_sales"], 80)
		self.assertAlmostEqual(currencies["ZWG"]["company_net_sales"], 100)
		self.assertAlmostEqual(currencies["USD"]["discount"], 25)
		self.assertAlmostEqual(currencies["ZWG"]["discount"], 170)

		tenders = {row["key"]: row for row in result["payment_mix"]}
		self.assertAlmostEqual(tenders["Cash::USD"]["opening_amount"], 50)
		self.assertAlmostEqual(tenders["Cash::USD"]["transaction_amount"], 90)
		self.assertAlmostEqual(tenders["Cash::USD"]["expected_amount"], 140)
		self.assertAlmostEqual(tenders["EcoCash::ZWG"]["expected_amount"], 1400)
		self.assertAlmostEqual(tenders["EcoCash::ZWG"]["company_expected_amount"], 100)
		self.assertAlmostEqual(tenders["Card::USD"]["expected_amount"], 30)

		self.assertEqual(result["top_items"][0]["stock_uom"], "Nos")
		self.assertAlmostEqual(result["top_items"][0]["qty"], 4)
		self.assertAlmostEqual(result["top_items"][0]["amount"], 190)
		self.assertEqual(result["hourly"], [
			{"hour": 9, "amount": 100.0, "count": 1},
			{"hour": 10, "amount": 100.0, "count": 1},
		])

	def test_closing_counts_and_variances_are_currency_separated(self):
		result = aggregate_shift(
			[],
			[],
			[],
			company_currency="USD",
			opening_balances=[
				{
					"mode_of_payment": "Cash",
					"currency": "USD",
					"amount": 50,
					"company_amount": 50,
				},
				{
					"mode_of_payment": "Cash",
					"currency": "ZWG",
					"amount": 700,
					"company_amount": 50,
				},
			],
			closing_balances=[
				{
					"mode_of_payment": "Cash",
					"currency": "USD",
					"expected_amount": 150,
					"closing_amount": 148,
					"company_expected_amount": 150,
					"company_closing_amount": 148,
				},
				{
					"mode_of_payment": "Cash",
					"currency": "ZWG",
					"expected_amount": 1400,
					"closing_amount": 1414,
					"company_expected_amount": 100,
					"company_closing_amount": 101,
				},
			],
		)

		tenders = {row["key"]: row for row in result["payment_mix"]}
		self.assertEqual(tenders["Cash::USD"]["closing_shift_count"], 1)
		self.assertEqual(tenders["Cash::USD"]["difference"], -2)
		self.assertEqual(tenders["Cash::USD"]["company_difference"], -2)
		self.assertEqual(tenders["Cash::ZWG"]["difference"], 14)
		self.assertEqual(tenders["Cash::ZWG"]["company_difference"], 1)

	def test_sales_performance_uses_company_values_and_complete_cost_data(self):
		invoices = [
			{
				"name": "SINV-1",
				"posting_date": "2026-09-20",
				"is_return": 0,
				"base_grand_total": 115,
				"base_net_total": 100,
				"base_discount_amount": 5,
				"base_total_taxes_and_charges": 15,
			},
			{
				"name": "SINV-RET-1",
				"posting_date": "2026-09-20",
				"is_return": 1,
				"base_grand_total": -23,
				"base_net_total": -20,
				"base_discount_amount": 0,
				"base_total_taxes_and_charges": -3,
			},
		]
		items = [
			{
				"parent": "SINV-1",
				"stock_qty": 2,
				"incoming_rate": 30,
			},
			{
				"parent": "SINV-RET-1",
				"stock_qty": -1,
				"incoming_rate": 30,
			},
		]

		rows = aggregate_sales_performance(
			invoices,
			items,
			company_currency="USD",
		)

		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row["gross_sales"], 115)
		self.assertEqual(row["returns"], 23)
		self.assertEqual(row["sales_after_returns"], 92)
		self.assertEqual(row["net_revenue"], 80)
		self.assertEqual(row["cogs"], 30)
		self.assertEqual(row["gross_profit"], 50)
		self.assertTrue(row["has_cost_data"])

	def test_payment_status_preserves_tender_currency_pairs(self):
		rows = build_payment_status_rows(
			[
				{
					"name": "SINV-1",
					"currency": "USD",
					"is_return": 0,
					"base_grand_total": 100,
					"base_paid_amount": 75,
					"base_outstanding_amount": 25,
				}
			],
			[
				{
					"parent": "SINV-1",
					"mode_of_payment": "Cash",
					"posa_tender_currency": "USD",
				},
				{
					"parent": "SINV-1",
					"mode_of_payment": "EcoCash",
					"posa_tender_currency": "ZWG",
				},
			],
			company_currency="USD",
		)

		self.assertEqual(rows[0]["payment_status"], "Partly Paid")
		self.assertTrue(rows[0]["is_split_payment"])
		self.assertEqual(
			rows[0]["tender_currencies"],
			"Cash · USD, EcoCash · ZWG",
		)

	def test_item_performance_uses_stock_qty_and_signed_returns(self):
		invoices = [
			{"name": "SINV-1", "is_return": 0},
			{"name": "SINV-RET-1", "is_return": 1},
		]
		items = [
			{
				"parent": "SINV-1",
				"item_code": "ITEM-1",
				"qty": 2,
				"stock_qty": 24,
				"base_net_amount": 120,
				"base_price_list_rate": 6,
				"base_rate": 5,
				"incoming_rate": 3,
			},
			{
				"parent": "SINV-RET-1",
				"item_code": "ITEM-1",
				"qty": -1,
				"stock_qty": -12,
				"base_net_amount": -60,
				"base_price_list_rate": 5,
				"base_rate": 5,
				"incoming_rate": 3,
			},
		]

		rows = aggregate_item_performance(
			invoices,
			items,
			company_currency="USD",
		)

		self.assertEqual(rows[0]["sold_qty"], 24)
		self.assertEqual(rows[0]["returned_qty"], 12)
		self.assertEqual(rows[0]["net_qty"], 12)
		self.assertEqual(rows[0]["net_revenue"], 60)
		self.assertEqual(rows[0]["cogs"], 36)
		self.assertEqual(rows[0]["gross_profit"], 24)
		self.assertEqual(rows[0]["discount"], 2)

	def test_customer_performance_keeps_returns_signed(self):
		rows = aggregate_customer_performance(
			[
				{
					"customer": "CUST-1",
					"customer_name": "Retail Customer",
					"posting_date": "2026-09-01",
					"is_return": 0,
					"base_grand_total": 100,
				},
				{
					"customer": "CUST-1",
					"customer_name": "Retail Customer",
					"posting_date": "2026-09-10",
					"is_return": 0,
					"base_grand_total": 50,
				},
				{
					"customer": "CUST-1",
					"customer_name": "Retail Customer",
					"posting_date": "2026-09-11",
					"is_return": 1,
					"base_grand_total": -20,
				},
			],
			company_currency="USD",
		)

		self.assertEqual(rows[0]["invoice_count"], 2)
		self.assertEqual(rows[0]["return_count"], 1)
		self.assertEqual(rows[0]["gross_sales"], 150)
		self.assertEqual(rows[0]["net_value"], 130)
		self.assertEqual(rows[0]["average_sale"], 75)
		self.assertTrue(rows[0]["is_repeat_customer"])


if __name__ == "__main__":
	unittest.main()
