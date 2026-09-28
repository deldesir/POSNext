import json
import unittest
from unittest.mock import MagicMock, patch

import frappe

from pos_next.pos_next.doctype.pos_closing_shift import pos_closing_shift as pcs


def _row(mode, expected, closing=None, opening=0):
	return {
		"mode_of_payment": mode,
		"opening_amount": opening,
		"expected_amount": expected,
		"closing_amount": closing,
	}


class TestMergeCountedAmounts(unittest.TestCase):
	def test_only_the_counted_amounts_come_from_the_client(self):
		fresh = {
			"grand_total": 5000,
			"payment_reconciliation": [_row("Cash", 5100, opening=100), _row("Natcash", 900)],
		}
		counted = {
			"grand_total": 4000,  # stale: a sale was rung after the dialog opened
			"payment_reconciliation": [
				_row("Cash", 4100, closing=5100, opening=100),
				_row("Natcash", 900, closing=850),
			],
		}
		merged = pcs.merge_counted_amounts(fresh, counted)
		self.assertIs(merged, fresh)
		self.assertEqual(fresh["grand_total"], 5000)
		cash, natcash = fresh["payment_reconciliation"]
		self.assertEqual(
			(cash["expected_amount"], cash["closing_amount"], cash["difference"]), (5100, 5100, 0)
		)
		self.assertEqual(
			(natcash["expected_amount"], natcash["closing_amount"], natcash["difference"]), (900, 850, -50)
		)

	def test_modes_the_client_did_not_count_stay_untouched(self):
		fresh = {"payment_reconciliation": [_row("Cash", 100), _row("Wire Transfer", 0)]}
		pcs.merge_counted_amounts(fresh, {"payment_reconciliation": [_row("Cash", 100, closing=100)]})
		self.assertEqual(fresh["payment_reconciliation"][1]["closing_amount"], None)
		pcs.merge_counted_amounts(fresh, {})
		self.assertEqual(fresh["payment_reconciliation"][0]["closing_amount"], 100)


class TestSubmitClosingShift(unittest.TestCase):
	def test_the_closing_is_rebuilt_on_the_server_at_submit(self):
		opening = MagicMock()
		opening.as_dict.return_value = {"name": "POSA-OS-26-0000042", "pos_profile": "Till A"}
		built_doc = MagicMock(name="POSA-CS-26-0000007")
		built_doc.name = "POSA-CS-26-0000007"
		fresh = {
			"doctype": "POS Closing Shift",
			"pos_opening_shift": "POSA-OS-26-0000042",
			"grand_total": 5000,
			"payment_reconciliation": [_row("Cash", 5000)],
		}
		client = {
			"doctype": "POS Closing Shift",
			"pos_opening_shift": "POSA-OS-26-0000042",
			"grand_total": 4000,
			"payment_reconciliation": [_row("Cash", 4000, closing=5000)],
		}

		def get_doc(*args):
			if args == ("POS Opening Shift", "POSA-OS-26-0000042"):
				return opening
			return built_doc

		with (
			patch.object(pcs.frappe, "get_doc", side_effect=get_doc) as get_doc_mock,
			patch.object(pcs, "make_closing_shift_from_opening", return_value=fresh) as rebuild,
		):
			name = pcs.submit_closing_shift(json.dumps(client))

		self.assertEqual(name, "POSA-CS-26-0000007")
		rebuild.assert_called_once()
		self.assertEqual(json.loads(rebuild.call_args.args[0])["name"], "POSA-OS-26-0000042")
		# The document is built from the server's figures with the cashier's count on top.
		built_from = get_doc_mock.call_args.args[0]
		self.assertEqual(built_from["grand_total"], 5000)
		self.assertEqual(built_from["payment_reconciliation"][0]["closing_amount"], 5000)
		self.assertEqual(built_from["payment_reconciliation"][0]["difference"], 0)
		built_doc.save.assert_called_once()
		built_doc.submit.assert_called_once()

	def test_missing_opening_shift_is_refused(self):
		with (
			patch.object(pcs.frappe, "throw", side_effect=ValueError),
			patch.object(pcs, "_", side_effect=lambda m: m),
		):
			with self.assertRaises(ValueError):
				pcs.submit_closing_shift(json.dumps({"payment_reconciliation": []}))
