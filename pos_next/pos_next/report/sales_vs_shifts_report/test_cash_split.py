import unittest

import frappe

from pos_next.pos_next.report.sales_vs_shifts_report.sales_vs_shifts_report import split_cash_and_non_cash


class TestCashSplit(unittest.TestCase):
	def test_split_follows_the_mode_type_not_the_name(self):
		rows = [
			frappe._dict(mode="cash", type="Cash", amount=1000),
			frappe._dict(mode="natcash", type="Phone", amount=250),
			frappe._dict(mode="mon cash", type="Phone", amount=100),
			frappe._dict(mode="wire transfer", type="Bank", amount=50),
		]
		self.assertEqual(split_cash_and_non_cash(rows), {"cash": 1000, "non_cash": 400})

	def test_unknown_type_counts_as_non_cash_and_empty_is_zero(self):
		self.assertEqual(
			split_cash_and_non_cash([frappe._dict(mode="x", type=None, amount=5)]), {"cash": 0, "non_cash": 5}
		)
		self.assertEqual(split_cash_and_non_cash([]), {"cash": 0, "non_cash": 0})
