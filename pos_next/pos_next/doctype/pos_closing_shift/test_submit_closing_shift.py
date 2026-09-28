import datetime
import json
import unittest
from unittest.mock import MagicMock, patch

import frappe

from pos_next.pos_next.doctype.pos_closing_shift import pos_closing_shift as pcs

OPENING = "POSA-OS-26-0000042"


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

	def test_a_counted_mode_the_rebuild_no_longer_expects_is_kept(self):
		fresh = {"payment_reconciliation": [_row("Cash", 100)]}
		pcs.merge_counted_amounts(
			fresh,
			{"payment_reconciliation": [_row("Cash", 100, closing=100), _row("Natcash", 500, closing=500)]},
		)
		natcash = fresh["payment_reconciliation"][1]
		self.assertEqual(
			(
				natcash["mode_of_payment"],
				natcash["expected_amount"],
				natcash["closing_amount"],
				natcash["difference"],
			),
			("Natcash", 0, 500, 500),
		)

	def test_modes_the_client_did_not_count_stay_untouched(self):
		fresh = {"payment_reconciliation": [_row("Cash", 100), _row("Wire Transfer", 0)]}
		pcs.merge_counted_amounts(fresh, {"payment_reconciliation": [_row("Cash", 100, closing=100)]})
		self.assertEqual(fresh["payment_reconciliation"][1]["closing_amount"], None)
		pcs.merge_counted_amounts(fresh, {})
		self.assertEqual(fresh["payment_reconciliation"][0]["closing_amount"], 100)
		self.assertEqual(len(fresh["payment_reconciliation"]), 2)


class TestSubmitClosingShift(unittest.TestCase):
	def setUp(self):
		self.db = MagicMock()
		self.db.get_value.return_value = "Open"
		self.opening = MagicMock()
		self.opening.user = "cashier@example.com"
		self.opening.as_dict.return_value = {"name": OPENING, "pos_profile": "Till A"}
		self.built_doc = MagicMock()
		self.built_doc.name = "POSA-CS-26-0000007"
		self.fresh = {
			"doctype": "POS Closing Shift",
			"pos_opening_shift": OPENING,
			"period_end_date": datetime.datetime(2026, 9, 28, 17, 5, 0),
			"grand_total": 5000,
			"payment_reconciliation": [_row("Cash", 5000)],
		}
		patches = [
			patch.object(pcs.frappe, "db", self.db),
			patch.object(pcs.frappe, "session", MagicMock(user="cashier@example.com")),
			patch.object(pcs.frappe, "get_roles", return_value=["POSNext Cashier"]),
			patch.object(
				pcs.frappe, "throw", side_effect=lambda msg, *a, **k: (_ for _ in ()).throw(ValueError(msg))
			),
			patch.object(pcs, "_", side_effect=lambda m: m),
			patch.object(
				pcs.frappe,
				"get_doc",
				side_effect=lambda *a: self.opening if a[:1] == ("POS Opening Shift",) else self.built_doc,
			),
			patch.object(pcs, "make_closing_shift_from_opening", return_value=self.fresh),
		]
		self.mocks = {}
		for p in patches:
			mock = p.start()
			self.mocks[getattr(p, "attribute", None)] = mock
			self.addCleanup(p.stop)

	def _client(self, closing=5000):
		return {
			"doctype": "POS Closing Shift",
			"pos_opening_shift": OPENING,
			"grand_total": 4000,  # stale
			"payment_reconciliation": [_row("Cash", 4000, closing=closing)],
		}

	def test_the_closing_is_rebuilt_on_the_server_at_submit(self):
		name = pcs.submit_closing_shift(json.dumps(self._client()))

		self.assertEqual(name, "POSA-CS-26-0000007")
		rebuild = self.mocks["make_closing_shift_from_opening"]
		rebuild.assert_called_once()
		self.assertEqual(json.loads(rebuild.call_args.args[0])["name"], OPENING)
		# The opening shift row is locked before anything else is read.
		self.db.get_value.assert_called_once_with("POS Opening Shift", OPENING, "status", for_update=True)
		# Built from the server's figures with the cashier's count on top, in the
		# text form the dialog used to send back.
		built_from = self.mocks["get_doc"].call_args.args[0]
		self.assertEqual(built_from["grand_total"], 5000)
		self.assertEqual(built_from["period_end_date"], "2026-09-28 17:05:00")
		self.assertEqual(built_from["payment_reconciliation"][0]["closing_amount"], 5000)
		self.assertEqual(built_from["payment_reconciliation"][0]["difference"], 0)
		self.built_doc.save.assert_called_once()
		self.built_doc.submit.assert_called_once()

	def test_return_closing_hands_back_the_saved_figures(self):
		result = pcs.submit_closing_shift(self._client(closing=4990), return_closing=True)
		self.assertEqual(result["name"], "POSA-CS-26-0000007")
		self.assertEqual(result["closing"]["name"], "POSA-CS-26-0000007")
		self.assertEqual(result["closing"]["docstatus"], 1)
		self.assertEqual(result["closing"]["grand_total"], 5000)
		self.assertEqual(result["closing"]["payment_reconciliation"][0]["difference"], -10)
		self.assertIsInstance(result["closing"]["period_end_date"], str)

	def test_a_shift_already_closed_is_refused_before_any_rebuild(self):
		self.db.get_value.return_value = "Closed"
		with self.assertRaises(ValueError):
			pcs.submit_closing_shift(json.dumps(self._client()))
		self.mocks["make_closing_shift_from_opening"].assert_not_called()

	def test_an_unknown_shift_is_refused(self):
		self.db.get_value.return_value = None
		with self.assertRaises(ValueError):
			pcs.submit_closing_shift(json.dumps({"pos_opening_shift": "POSA-OS-26-9999999"}))

	def test_another_cashier_cannot_close_the_shift_but_a_manager_can(self):
		self.opening.user = "someone.else@example.com"
		with self.assertRaises(ValueError):
			pcs.submit_closing_shift(json.dumps(self._client()))
		self.mocks["make_closing_shift_from_opening"].assert_not_called()
		with patch.object(pcs.frappe, "get_roles", return_value=["Nexus POS Manager"]):
			self.assertEqual(pcs.submit_closing_shift(json.dumps(self._client())), "POSA-CS-26-0000007")

	def test_missing_or_malformed_payloads_are_refused(self):
		with self.assertRaises(ValueError):
			pcs.submit_closing_shift(json.dumps({"payment_reconciliation": []}))
		with self.assertRaises(ValueError):
			pcs.submit_closing_shift(json.dumps([1, 2, 3]))
		self.db.get_value.assert_not_called()
