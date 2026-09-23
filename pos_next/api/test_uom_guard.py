import unittest
from unittest.mock import MagicMock, patch

from pos_next.api import uom_guard


class Row(dict):
	def __getattr__(self, k):
		return self.get(k)


def doc(rows, is_return=0):
	d = MagicMock()
	d.get = lambda k, default=None: {"items": [Row(r) for r in rows], "is_return": is_return}.get(k, default)
	return d


class TestUomGuard(unittest.TestCase):
	def setUp(self):
		self.db = MagicMock()
		self.item_table = {("CASE-ITEM", "Caisse 24"): 24.0, ("CARD-ITEM", "Caisse(20 BT)"): 5000.0}
		self.db.get_value.side_effect = lambda doctype, filters, field: (
			self.item_table.get((filters["parent"], filters["uom"])) if doctype == "UOM Conversion Detail" else None
		)
		self.global_factor = None
		patches = [
			patch.object(uom_guard.frappe, "db", self.db),
			patch.object(uom_guard.frappe, "get_cached_value", side_effect=lambda dt, name, field: None),
			patch.object(uom_guard.frappe, "bold", side_effect=lambda v: str(v)),
			patch.dict("sys.modules", {"erpnext.stock.doctype.item.item": MagicMock(get_uom_conv_factor=lambda uom, stock_uom: self.global_factor)}),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_matching_factor_passes(self):
		rows = [{"idx": 1, "item_code": "CASE-ITEM", "uom": "Caisse 24", "stock_uom": "Unité", "conversion_factor": 24}]
		self.assertEqual(uom_guard.line_problems(doc(rows)), [])

	def test_stock_uom_rows_are_ignored(self):
		rows = [{"idx": 1, "item_code": "CASE-ITEM", "uom": "Unité", "stock_uom": "Unité", "conversion_factor": 7}]
		self.assertEqual(uom_guard.line_problems(doc(rows)), [])

	def test_the_case_that_booked_2_units_instead_of_48(self):
		rows = [{"idx": 1, "item_code": "CASE-ITEM", "uom": "Caisse 24", "stock_uom": "Unité", "conversion_factor": 1}]
		problems = uom_guard.line_problems(doc(rows))
		self.assertEqual(len(problems), 1)
		self.assertIn("does not match the item's 24.0", problems[0])

	def test_the_case_that_booked_ten_times_too_much(self):
		rows = [{"idx": 3, "item_code": "CARD-ITEM", "uom": "Caisse(20 BT)", "stock_uom": "Unité", "conversion_factor": 50000}]
		problems = uom_guard.line_problems(doc(rows))
		self.assertIn("Row 3", problems[0])
		self.assertIn("50000.0", problems[0])

	def test_uom_missing_from_the_item_is_refused(self):
		rows = [{"idx": 2, "item_code": "BOX-ITEM", "uom": "Boite (50UNT)", "stock_uom": "Unité", "conversion_factor": 1}]
		problems = uom_guard.line_problems(doc(rows))
		self.assertIn("no conversion factor is defined for Boite (50UNT)", problems[0])

	def test_global_uom_table_counts_as_defined(self):
		self.global_factor = 0.001
		rows = [{"idx": 1, "item_code": "SUGAR", "uom": "Gram", "stock_uom": "Kg", "conversion_factor": 0.001}]
		self.assertEqual(uom_guard.line_problems(doc(rows)), [])
		rows[0]["conversion_factor"] = 1
		self.assertEqual(len(uom_guard.line_problems(doc(rows))), 1)

	def test_validate_throws_once_with_all_rows_and_skips_returns(self):
		rows = [
			{"idx": 1, "item_code": "CASE-ITEM", "uom": "Caisse 24", "stock_uom": "Unité", "conversion_factor": 1},
			{"idx": 2, "item_code": "BOX-ITEM", "uom": "Boite (50UNT)", "stock_uom": "Unité", "conversion_factor": 1},
		]
		with patch.object(uom_guard.frappe, "throw", side_effect=Exception("thrown")) as throw:
			with self.assertRaises(Exception):
				uom_guard.validate_conversion_factors(doc(rows))
			self.assertEqual(throw.call_args[0][0].count("Row "), 2)
			throw.reset_mock()
			uom_guard.validate_conversion_factors(doc(rows, is_return=1))
			throw.assert_not_called()
