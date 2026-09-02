import base64
import hashlib
import unittest

from posawesome.posawesome.api.fiscal_utils import (
	cents,
	fiscal_day_signature_content,
	receipt_signature_content,
)


class ZimbabweFiscalSignatureTest(unittest.TestCase):
	def test_cent_conversion_uses_decimal_half_up(self):
		self.assertEqual(cents("12.345"), "1235")
		self.assertEqual(cents("-0.005"), "-1")

	def test_zimra_receipt_signature_concatenation(self):
		receipt = {
			"receiptType": "FiscalInvoice",
			"receiptCurrency": "ZWL",
			"receiptCounter": 2,
			"receiptGlobalNo": 432,
			"receiptDate": "2019-09-19T15:43:12",
			"receiptTotal": "9450.00",
			"receiptTaxes": [
				{
					"taxID": 1,
					"taxCode": "A",
					"taxPercent": None,
					"taxAmount": "0.00",
					"salesAmountWithTax": "2500.00",
				},
				{
					"taxID": 2,
					"taxCode": "B",
					"taxPercent": 0,
					"taxAmount": "0.00",
					"salesAmountWithTax": "3500.00",
				},
				{
					"taxID": 3,
					"taxCode": "C",
					"taxPercent": 15,
					"taxAmount": "150.00",
					"salesAmountWithTax": "1150.00",
				},
				{
					"taxID": 3,
					"taxCode": "D",
					"taxPercent": 15,
					"taxAmount": "300.00",
					"salesAmountWithTax": "2300.00",
				},
			],
		}
		content = receipt_signature_content(
			321,
			receipt,
			"hNVJXP/ACOiE8McD3pKsDlqBXpuaUqQOfPnMyfZWI9k=",
		)
		self.assertEqual(
			content,
			"321FISCALINVOICEZWL4322019-09-19T15:43:12945000"
			"A0250000B0.000350000C15.0015000115000D15.0030000230000"
			"hNVJXP/ACOiE8McD3pKsDlqBXpuaUqQOfPnMyfZWI9k=",
		)
		digest = base64.b64encode(hashlib.sha256(content.encode()).digest()).decode()
		self.assertEqual(digest, "eHAAOVqxrRVRliVOsik4sONXJ10nckqCWIhPyoMyguM=")

	def test_fiscal_day_signature_sorting_and_date(self):
		content = fiscal_day_signature_content(
			321,
			84,
			"2019-09-23T08:00:00",
			[
				{
					"fiscalCounterType": "BalanceByMoneyType",
					"fiscalCounterCurrency": "USD",
					"fiscalCounterMoneyType": "Cash",
					"fiscalCounterValue": "37.00",
				},
				{
					"fiscalCounterType": "SaleByTax",
					"fiscalCounterCurrency": "USD",
					"fiscalCounterTaxID": 3,
					"fiscalCounterTaxPercent": 14.5,
					"fiscalCounterValue": "25.00",
				},
			],
		)
		self.assertEqual(
			content,
			"321842019-09-23"
			"BALANCEBYMONEYTYPEUSDCASH3700"
			"SALEBYTAXUSD14.502500",
		)


if __name__ == "__main__":
	unittest.main()
