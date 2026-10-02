import unittest
from unittest.mock import MagicMock, patch

import frappe

from pos_next.api import sales_invoice_hooks as hooks


def _invoice(**overrides):
	doc = frappe._dict(
		{
			"docstatus": 1,
			"is_pos": 1,
			"is_consolidated": 0,
			"pos_profile": "Till A",
			"posa_pos_opening_shift": None,
		}
	)
	doc.update(overrides)
	return doc


class TestStampPosOpeningShift(unittest.TestCase):
	"""A POS invoice submitted from the desk joins the submitter's open shift on that profile."""

	def setUp(self):
		self.db = MagicMock()
		self.db.get_value.return_value = "POSA-OS-26-0000042"
		patches = [
			patch.object(hooks.frappe, "db", self.db),
			patch.object(hooks.frappe, "session", MagicMock(user="cashier@example.com")),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_desk_pos_invoice_is_stamped_at_submit(self):
		doc = _invoice()
		hooks.stamp_pos_opening_shift(doc)
		self.assertEqual(doc.posa_pos_opening_shift, "POSA-OS-26-0000042")
		filters = self.db.get_value.call_args.args[1]
		self.assertEqual(filters["user"], "cashier@example.com")
		self.assertEqual(filters["pos_profile"], "Till A")
		self.assertEqual(filters["status"], "Open")
		self.assertEqual(filters["docstatus"], 1)

	def test_drafts_are_left_alone(self):
		doc = _invoice(docstatus=0)
		hooks.stamp_pos_opening_shift(doc)
		self.assertIsNone(doc.posa_pos_opening_shift)
		self.db.get_value.assert_not_called()

	def test_pos_app_value_is_kept_while_that_shift_is_open(self):
		self.db.get_value.side_effect = (
			lambda doctype, *a, **k: "Open"
			if doctype == "POS Opening Shift" and isinstance(a[0], str)
			else None
		)
		doc = _invoice(posa_pos_opening_shift="POSA-OS-26-0000001")
		hooks.stamp_pos_opening_shift(doc)
		self.assertEqual(doc.posa_pos_opening_shift, "POSA-OS-26-0000001")
		self.assertEqual(self.db.get_value.call_count, 1)

	def test_invoice_synced_into_a_closed_shift_moves_to_the_open_one(self):
		# First call: status of the carried shift; second call: the open shift lookup.
		self.db.get_value.side_effect = ["Closed", "POSA-OS-26-0000042"]
		doc = _invoice(posa_pos_opening_shift="POSA-OS-26-0000001")
		hooks.stamp_pos_opening_shift(doc)
		self.assertEqual(doc.posa_pos_opening_shift, "POSA-OS-26-0000042")

	def test_selling_into_a_closed_shift_without_an_open_one_is_refused(self):
		self.db.get_value.side_effect = ["Closed", None]
		doc = _invoice(posa_pos_opening_shift="POSA-OS-26-0000001")
		with (
			patch.object(
				hooks.frappe, "throw", side_effect=lambda msg, *a, **k: (_ for _ in ()).throw(ValueError(msg))
			),
			patch.object(hooks, "_", side_effect=lambda m: m),
		):
			with self.assertRaises(ValueError) as ctx:
				hooks.stamp_pos_opening_shift(doc)
		self.assertIn("POSA-OS-26-0000001 is closed", str(ctx.exception))

	def test_a_desk_invoice_without_any_shift_is_still_accepted(self):
		self.db.get_value.return_value = None
		doc = _invoice()
		hooks.stamp_pos_opening_shift(doc)
		self.assertIsNone(doc.posa_pos_opening_shift)

	def test_non_pos_and_consolidated_invoices_are_skipped(self):
		for doc in (_invoice(is_pos=0), _invoice(is_consolidated=1), _invoice(pos_profile=None)):
			hooks.stamp_pos_opening_shift(doc)
			self.assertIsNone(doc.posa_pos_opening_shift)
		self.db.get_value.assert_not_called()

	def test_no_open_shift_on_that_profile_means_back_office(self):
		self.db.get_value.return_value = None
		doc = _invoice()
		hooks.stamp_pos_opening_shift(doc)
		self.assertIsNone(doc.posa_pos_opening_shift)

	def test_validate_runs_the_stamp(self):
		with (
			patch.object(hooks, "apply_tax_inclusive"),
			patch.object(hooks, "auto_assign_loyalty_program_on_invoice"),
			patch.object(hooks, "sync_return_loyalty_program"),
			patch.object(hooks, "allow_zero_valuation_for_pos"),
			patch.object(hooks, "stamp_pos_opening_shift") as stamp,
		):
			doc = _invoice()
			hooks.validate(doc)
		stamp.assert_called_once_with(doc)
