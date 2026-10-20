"""Checks ERPNext's POS service refactor moved off the Sales Invoice document; POS Next must still win.

* a sale on account (no payment row) submits when `submit_invoice` vouched for it, and is
  refused when nothing did;
* a refused submission takes its own draft with it;
* optional apps annotate customer search results.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from pos_next.api import invoices
from pos_next.integrations import registry
from pos_next.overrides import sales_invoice as overrides


class _Doc(frappe._dict):
	"""The slice of a Sales Invoice the checks read, with attribute access like a Document."""

	def __init__(self, **values):
		flags = values.pop("flags", {})
		super().__init__(values)
		self.flags = frappe._dict(flags)


def _credit_sale(**flags):
	return _Doc(is_pos=1, grand_total=120.0, payments=[], flags=flags)


class TestPaymentRowsOptional(unittest.TestCase):
	def test_a_vouched_credit_sale_needs_no_payment_row(self):
		self.assertTrue(overrides.payment_rows_optional(_credit_sale(pos_next_credit_sale=1)))
		self.assertTrue(overrides.payment_rows_optional(_credit_sale(pos_next_redeemed_customer_credit=50)))

	def test_an_unvouched_sale_still_needs_one(self):
		self.assertFalse(overrides.payment_rows_optional(_credit_sale()))

	def test_a_sale_with_rows_or_nothing_to_pay_is_not_the_case(self):
		with_rows = _Doc(is_pos=1, grand_total=120.0, payments=[{"amount": 0}], flags={"pos_next_credit_sale": 1})
		self.assertFalse(overrides.payment_rows_optional(with_rows))
		nothing_due = _Doc(is_pos=1, grand_total=0, payments=[], flags={"pos_next_credit_sale": 1})
		self.assertFalse(overrides.payment_rows_optional(nothing_due))
		not_pos = _Doc(is_pos=0, grand_total=120.0, payments=[], flags={"pos_next_credit_sale": 1})
		self.assertFalse(overrides.payment_rows_optional(not_pos))

	@unittest.skipIf(overrides.POSService is None, "ERPNext without the POS service")
	def test_the_pos_service_honours_the_flag(self):
		service = overrides.POSService(_credit_sale(pos_next_credit_sale=1))
		service.validate_pos_paid_amount()  # must not raise
		with self.assertRaises(frappe.ValidationError):
			overrides.POSService(_credit_sale()).validate_pos_paid_amount()


class TestFailedDraftCleanup(unittest.TestCase):
	def test_a_draft_is_deleted_on_its_own_transaction(self):
		db = MagicMock()
		db.get_value.return_value = 0
		with patch.object(invoices.frappe, "db", db), patch.object(invoices.frappe, "delete_doc") as delete_doc:
			invoices._discard_failed_draft("ACC-SINV-X")
		db.rollback.assert_called_once()
		delete_doc.assert_called_once_with("Sales Invoice", "ACC-SINV-X", force=1, ignore_permissions=True)
		db.commit.assert_called_once()

	def test_a_submitted_invoice_is_never_touched(self):
		db = MagicMock()
		db.get_value.return_value = 1
		with patch.object(invoices.frappe, "db", db), patch.object(invoices.frappe, "delete_doc") as delete_doc:
			invoices._discard_failed_draft("ACC-SINV-Y")
		delete_doc.assert_not_called()
		db.commit.assert_not_called()

	def test_cleanup_failure_never_masks_the_refusal(self):
		db = MagicMock()
		db.get_value.side_effect = RuntimeError("gone")
		with patch.object(invoices.frappe, "db", db), patch.object(invoices.frappe, "log_error") as log_error:
			invoices._discard_failed_draft("ACC-SINV-Z")  # must not raise
		log_error.assert_called_once()


def _room_note(customers, pos_profile=None):
	for customer in customers:
		if customer.get("name") == "GUEST-1":
			customer["note"] = "Room 301"


def _broken_hook(customers, pos_profile=None):
	raise RuntimeError("hook down")


class TestCustomerAnnotation(unittest.TestCase):
	def test_hooks_add_notes_in_place(self):
		rows = [{"name": "GUEST-1", "customer_name": "A"}, {"name": "OTHER", "customer_name": "B"}]
		with patch.object(registry.frappe, "get_hooks", return_value=[f"{__name__}._room_note"]):
			registry.annotate_customers(rows, "Bar")
		self.assertEqual(rows[0]["note"], "Room 301")
		self.assertNotIn("note", rows[1])

	def test_a_failing_hook_is_logged_and_the_search_still_answers(self):
		rows = [{"name": "GUEST-1"}]
		with patch.object(registry.frappe, "get_hooks", return_value=[f"{__name__}._broken_hook", f"{__name__}._room_note"]), patch.object(
			registry.frappe, "log_error"
		) as log_error:
			registry.annotate_customers(rows, "Bar")
		log_error.assert_called_once()
		self.assertEqual(rows[0]["note"], "Room 301")

	def test_nothing_to_annotate_asks_no_hook(self):
		with patch.object(registry.frappe, "get_hooks") as get_hooks:
			self.assertEqual(registry.annotate_customers([], "Bar"), [])
		get_hooks.assert_not_called()
