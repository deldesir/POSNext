import unittest
from unittest.mock import MagicMock, patch

import frappe

from pos_next.api import credit_sales


class TestCustomerBalance(unittest.TestCase):
	def setUp(self):
		self.db = MagicMock()
		patches = [
			patch.object(credit_sales.frappe, "db", self.db),
			patch.object(
				credit_sales.frappe,
				"throw",
				side_effect=lambda msg, *a, **k: (_ for _ in ()).throw(ValueError(msg)),
			),
			patch.object(credit_sales, "_", side_effect=lambda m: m),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_balance_is_owed_minus_credit(self):
		self.db.sql.side_effect = [[frappe._dict(total=15000)], [frappe._dict(total=-2500)]]
		self.assertEqual(
			credit_sales.get_customer_balance("CUST-1", "NM"),
			{"total_outstanding": 15000, "total_credit": 2500, "net_balance": 12500},
		)
		owed_sql, owed_params = self.db.sql.call_args_list[0].args
		credit_sql, _ = self.db.sql.call_args_list[1].args
		self.assertIn("outstanding_amount > 0", owed_sql)
		self.assertIn("company = %(company)s", owed_sql)
		self.assertEqual(owed_params, {"customer": "CUST-1", "company": "NM"})
		self.assertIn("outstanding_amount < 0", credit_sql)
		self.assertIn(
			"is_return = 0 OR IFNULL(return_against, '') = '' OR update_outstanding_for_self = 1", credit_sql
		)
		for sql in (owed_sql, credit_sql):
			self.assertIn("docstatus = 1", sql)
			self.assertNotIn("get_all", sql)

	def test_company_is_optional_and_empty_sums_are_zero(self):
		self.db.sql.side_effect = [[frappe._dict(total=0)], []]
		result = credit_sales.get_customer_balance("CUST-2")
		self.assertEqual(result, {"total_outstanding": 0, "total_credit": 0, "net_balance": 0})
		self.assertNotIn("company =", self.db.sql.call_args_list[0].args[0])

	def test_a_failing_query_is_not_hidden_behind_zeros(self):
		self.db.sql.side_effect = RuntimeError("db down")
		with self.assertRaises(RuntimeError):
			credit_sales.get_customer_balance("CUST-3", "NM")

	def test_customer_is_required(self):
		with self.assertRaises(ValueError):
			credit_sales.get_customer_balance("", "NM")
