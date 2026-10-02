import unittest
from unittest.mock import MagicMock, patch

import frappe

from pos_next.api import payment_modes as pm


class TestReceiptModeOfPayment(unittest.TestCase):
	def test_the_receipts_own_mode_wins(self):
		with patch.object(pm.frappe, "get_all") as get_all:
			self.assertEqual(
				pm.receipt_mode_of_payment(frappe._dict(mode_of_payment="Natcash", paid_to="1206 - NatCash")),
				"Natcash",
			)
		get_all.assert_not_called()

	def test_a_blank_mode_takes_the_one_its_account_implies(self):
		with patch.object(pm.frappe, "get_all", return_value=["Cash"]) as get_all:
			self.assertEqual(
				pm.receipt_mode_of_payment(
					frappe._dict(mode_of_payment=None, paid_to="1110 - Cash - NM", company="NM")
				),
				"Cash",
			)
		self.assertEqual(
			get_all.call_args.kwargs["filters"], {"default_account": "1110 - Cash - NM", "company": "NM"}
		)

	def test_an_unmapped_or_ambiguous_account_gives_nothing(self):
		with patch.object(pm.frappe, "get_all", return_value=[]):
			self.assertIsNone(
				pm.receipt_mode_of_payment(frappe._dict(paid_to="1202 - Sogebank HTG - MPA", company="MPA"))
			)
		with patch.object(pm.frappe, "get_all", return_value=["Cash", "Petty Cash"]):
			self.assertIsNone(pm.receipt_mode_of_payment(frappe._dict(paid_to="1110 - Cash", company="MPA")))
		self.assertIsNone(pm.mode_of_payment_for_account(None, "MPA"))

	def test_profile_modes_in_profile_order(self):
		with patch.object(pm.frappe, "get_all", return_value=["Cash", "Natcash"]) as get_all:
			self.assertEqual(pm.profile_payment_modes("Till A"), ["Cash", "Natcash"])
		self.assertEqual(get_all.call_args.kwargs["order_by"], "idx")
		self.assertEqual(pm.profile_payment_modes(None), [])
