import unittest
from unittest.mock import MagicMock, patch

import frappe

from pos_next.api import payment_entry_hooks as hooks


def _receipt(**overrides):
	doc = frappe._dict(
		{
			"docstatus": 1,
			"payment_type": "Receive",
			"party_type": "Customer",
			"mode_of_payment": "Cash",
			"paid_to": "1110 - Cash - NM",
			"company": "NM",
			"posa_pos_opening_shift": None,
		}
	)
	doc.update(overrides)
	doc.set = lambda k, v: doc.__setitem__(k, v)
	return doc


class TestStampReceiptWithShift(unittest.TestCase):
	"""A customer receipt submitted from the desk joins the submitter's open shift
	when it was taken by a method that till offers."""

	def setUp(self):
		self.db = MagicMock()
		self.db.has_column.return_value = True
		self.db.get_value.return_value = "Till A"  # the shift's profile
		self.till_modes = ["Cash", "Natcash"]
		self.account_modes = {"1110 - Cash - NM": "Cash"}
		patches = [
			patch.object(hooks.frappe, "db", self.db),
			patch.object(hooks, "_shift_field_available", side_effect=lambda: bool(self.db.has_column())),
			patch.object(hooks, "get_session_open_shift", return_value="POSA-OS-26-0000042"),
			patch.object(hooks, "profile_payment_modes", side_effect=lambda profile: list(self.till_modes)),
			patch.object(
				hooks,
				"receipt_mode_of_payment",
				side_effect=lambda d: d.get("mode_of_payment") or self.account_modes.get(d.get("paid_to")),
			),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_desk_cash_receipt_is_stamped_at_submit(self):
		doc = _receipt()
		hooks.stamp_pos_opening_shift(doc)
		self.assertEqual(doc["posa_pos_opening_shift"], "POSA-OS-26-0000042")
		self.db.get_value.assert_called_once_with("POS Opening Shift", "POSA-OS-26-0000042", "pos_profile")

	def test_a_blank_mode_is_filled_from_the_account_and_stamped(self):
		doc = _receipt(mode_of_payment=None)
		hooks.stamp_pos_opening_shift(doc)
		self.assertEqual(doc["mode_of_payment"], "Cash")
		self.assertEqual(doc["posa_pos_opening_shift"], "POSA-OS-26-0000042")

	def test_a_bank_transfer_the_till_cannot_take_stays_back_office(self):
		doc = _receipt(mode_of_payment=None, paid_to="1202 - Sogebank HTG - MPA")
		hooks.stamp_pos_opening_shift(doc)
		self.assertIsNone(doc["posa_pos_opening_shift"])
		self.assertIsNone(doc["mode_of_payment"])
		doc = _receipt(mode_of_payment="Wire Transfer")
		hooks.stamp_pos_opening_shift(doc)
		self.assertIsNone(doc["posa_pos_opening_shift"])

	def test_drafts_payments_out_and_non_customers_are_skipped(self):
		for doc in (_receipt(docstatus=0), _receipt(payment_type="Pay"), _receipt(party_type="Supplier")):
			hooks.stamp_pos_opening_shift(doc)
			self.assertIsNone(doc["posa_pos_opening_shift"])

	def test_pos_path_value_is_kept(self):
		doc = _receipt(posa_pos_opening_shift="POSA-OS-26-0000001")
		hooks.stamp_pos_opening_shift(doc)
		self.assertEqual(doc["posa_pos_opening_shift"], "POSA-OS-26-0000001")

	def test_no_open_shift_means_back_office(self):
		with patch.object(hooks, "get_session_open_shift", return_value=None):
			doc = _receipt()
			hooks.stamp_pos_opening_shift(doc)
		self.assertIsNone(doc["posa_pos_opening_shift"])

	def test_missing_column_is_a_no_op(self):
		self.db.has_column.return_value = False
		doc = _receipt()
		hooks.stamp_pos_opening_shift(doc)
		self.assertIsNone(doc["posa_pos_opening_shift"])
