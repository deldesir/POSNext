import unittest
from unittest.mock import MagicMock, patch

from pos_next.api import partial_payments as pp


class TestReceiptShiftResolution(unittest.TestCase):
	"""A receipt taken at the till is tagged with the drawer that received it."""

	def setUp(self):
		self.db = MagicMock()
		patches = [
			patch.object(pp.frappe, "db", self.db),
			patch.object(
				pp.frappe, "throw", side_effect=lambda msg, *a, **k: (_ for _ in ()).throw(ValueError(msg))
			),
			patch.object(pp, "_", side_effect=lambda msg: msg),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_explicit_open_shift_is_kept(self):
		self.db.get_value.return_value = pp.frappe._dict(status="Open", docstatus=1)
		self.assertEqual(pp.resolve_pos_opening_shift("POSA-OS-26-0000009"), "POSA-OS-26-0000009")
		self.db.get_value.assert_called_once()

	def test_explicit_closed_shift_is_refused(self):
		self.db.get_value.return_value = pp.frappe._dict(status="Closed", docstatus=1)
		with self.assertRaises(ValueError):
			pp.resolve_pos_opening_shift("POSA-OS-26-0000009")

	def test_unknown_explicit_shift_is_refused(self):
		self.db.get_value.return_value = None
		with self.assertRaises(ValueError):
			pp.resolve_pos_opening_shift("POSA-OS-26-9999999")

	def test_falls_back_to_the_session_users_open_shift(self):
		with (
			patch.object(pp.frappe, "get_all", return_value=["POSA-OS-26-0000010"]) as get_all,
			patch.object(pp.frappe, "session", MagicMock(user="cashier@example.com")),
		):
			self.assertEqual(pp.resolve_pos_opening_shift(), "POSA-OS-26-0000010")
		filters = get_all.call_args.kwargs["filters"]
		self.assertEqual(filters["user"], "cashier@example.com")
		self.assertEqual(filters["status"], "Open")
		self.assertEqual(filters["docstatus"], 1)

	def test_no_open_shift_means_back_office(self):
		with (
			patch.object(pp.frappe, "get_all", return_value=[]),
			patch.object(pp.frappe, "session", MagicMock(user="manager@example.com")),
		):
			self.assertIsNone(pp.resolve_pos_opening_shift())

	def test_shift_field_guard_reads_the_schema(self):
		self.db.has_column.return_value = False
		self.assertFalse(pp._shift_field_available())
		self.db.has_column.assert_called_with("Payment Entry", "posa_pos_opening_shift")
