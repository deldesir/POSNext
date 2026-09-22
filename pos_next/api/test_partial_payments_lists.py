import unittest
from unittest.mock import MagicMock, patch

from pos_next.api import partial_payments as pp


class TestOpenInvoiceQueries(unittest.TestCase):
	"""Partial / unpaid lists and summaries are driven by outstanding_amount, not paid_amount."""

	def setUp(self):
		# frappe.db is a site-bound proxy; outside a request it must be replaced whole
		self.db = MagicMock()
		self.db.exists.return_value = True
		patches = [
			patch.object(pp.frappe, "db", self.db),
			patch.object(pp, "_has_pos_profile_access", return_value=True),
			patch.object(pp, "enrich_invoice_with_payment_history", side_effect=lambda inv, include_metadata=True: inv),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def sql(self, rows):
		self.db.sql.reset_mock()
		self.db.sql.return_value = rows
		return self.db.sql

	def test_partly_paid_condition_uses_the_amount_due(self):
		self.assertIn("outstanding_amount <", pp.PARTLY_PAID_SQL)
		self.assertIn("rounded_total", pp.PARTLY_PAID_SQL)
		self.assertNotIn("paid_amount", pp.PARTLY_PAID_SQL)
		self.assertNotIn("paid_amount", pp.OPEN_INVOICE_SQL)

	def test_partial_list_queries_with_the_partly_paid_condition(self):
		sql = self.sql([{"name": "SINV-1"}])
		rows = pp.get_partial_paid_invoices("Till", limit=7)
		self.assertEqual(rows, [{"name": "SINV-1"}])
		query, values = sql.call_args[0]
		self.assertIn(pp.PARTLY_PAID_SQL, query)
		self.assertEqual(values["limit"], 7)
		self.assertEqual(values["tolerance"], pp.AMOUNT_TOLERANCE)
		self.assertEqual(values["pos_profile"], "Till")

	def test_unpaid_list_queries_every_open_invoice(self):
		sql = self.sql([])
		pp.get_unpaid_invoices("Till")
		query, values = sql.call_args[0]
		self.assertIn(f"AND {pp.OPEN_INVOICE_SQL}", query)
		self.assertNotIn("rounded_total", query)
		self.assertEqual(values["limit"], pp.DEFAULT_INVOICE_LIMIT)

	def test_summaries_report_what_was_paid_so_far(self):
		row = {"count": "2", "total_outstanding": "10160", "total_paid": "7765", "total_grand_total": "17925"}
		sql = self.sql([row])
		summary = pp.get_partial_payment_summary("Till")
		self.assertEqual(summary, {"count": 2, "total_outstanding": 10160.0, "total_paid": 7765.0, "total_grand_total": 17925.0})
		query = sql.call_args[0][0]
		self.assertIn("- outstanding_amount", query)  # paid so far = amount due - outstanding
		self.assertIn(pp.PARTLY_PAID_SQL, query)

		sql = self.sql([row])
		pp.get_unpaid_summary("Till")
		self.assertIn(f"AND {pp.OPEN_INVOICE_SQL}", sql.call_args[0][0])
