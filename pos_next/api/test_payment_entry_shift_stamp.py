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
			"posa_pos_opening_shift": None,
		}
	)
	doc.update(overrides)
	doc.set = lambda k, v: doc.__setitem__(k, v)
	return doc


class TestStampReceiptWithShift(unittest.TestCase):
	"""A customer receipt submitted from the desk joins the submitter's open shift."""

	def setUp(self):
		self.db = MagicMock()
		self.db.has_column.return_value = True
		patches = [
			patch.object(hooks, "_shift_field_available", side_effect=lambda: bool(self.db.has_column())),
			patch.object(hooks, "get_session_open_shift", return_value="POSA-OS-26-0000042"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_desk_receipt_is_stamped_at_submit(self):
		doc = _receipt()
		hooks.stamp_pos_opening_shift(doc)
		self.assertEqual(doc["posa_pos_opening_shift"], "POSA-OS-26-0000042")

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
