import unittest
from unittest.mock import MagicMock, patch

import frappe

from pos_next.api import shifts
from pos_next.pos_next.doctype.pos_closing_shift import pos_closing_shift as pcs

TARGET = "pos_next.pos_next.doctype.pos_closing_shift.pos_closing_shift.submit_closing_shift"


class TestSubmitClosingShiftWrapper(unittest.TestCase):
	"""The POS endpoint passes typed, user-facing errors through unchanged."""

	def setUp(self):
		patches = [
			patch.object(shifts.frappe, "log_error"),
			patch.object(
				shifts.frappe,
				"throw",
				side_effect=lambda msg, *a, **k: (_ for _ in ()).throw(RuntimeError(msg)),
			),
			patch.object(shifts, "_", side_effect=lambda m: m),
		]
		self.mocks = [p.start() for p in patches]
		for p in patches:
			self.addCleanup(p.stop)
		self.log_error, self.throw, _ = self.mocks

	def test_success_returns_name_status_and_closing(self):
		with patch(
			TARGET, return_value={"name": "POSA-CS-26-0000007", "closing": {"grand_total": 5}}
		) as submit:
			result = shifts.submit_closing_shift({"pos_opening_shift": "POSA-OS-26-0000042"})
		self.assertEqual(
			result, {"name": "POSA-CS-26-0000007", "status": "success", "closing": {"grand_total": 5}}
		)
		self.assertEqual(submit.call_args.kwargs, {"return_closing": True})
		self.assertIsInstance(submit.call_args.args[0], str)  # dict payloads are serialised

	def test_already_closed_keeps_its_type_and_is_not_logged(self):
		with patch(TARGET, side_effect=pcs.ShiftAlreadyClosedError("already closed")):
			with self.assertRaises(pcs.ShiftAlreadyClosedError):
				shifts.submit_closing_shift("{}")
		self.log_error.assert_not_called()
		self.throw.assert_not_called()

	def test_validation_and_permission_errors_pass_through(self):
		for exc in (
			frappe.ValidationError("bad"),
			frappe.MandatoryError("missing"),
			frappe.PermissionError("no"),
		):
			with patch(TARGET, side_effect=exc):
				with self.assertRaises(type(exc)):
					shifts.submit_closing_shift("{}")
		self.log_error.assert_not_called()

	def test_unexpected_errors_are_logged_and_wrapped(self):
		with patch(TARGET, side_effect=RuntimeError("boom")):
			with self.assertRaises(RuntimeError):
				shifts.submit_closing_shift("{}")
		self.log_error.assert_called_once()
		self.assertIn("boom", self.throw.call_args.args[0])
