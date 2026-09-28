import unittest
from unittest.mock import MagicMock, patch

from pos_next.api import invoices


class TestPaymentAccountFallback(unittest.TestCase):
	"""With no account configured, only a Cash-type mode may land on the company cash account."""

	def setUp(self):
		self.db = MagicMock()
		self.db.sql.return_value = []  # no POS Payment Method default account
		self.types = {"Cash": "Cash", "Natcash": "Phone", "Mon Cash": "Phone"}

		def db_get_value(doctype, name, fieldname=None, *a, **k):
			if doctype == "Mode of Payment Account":
				return None
			if doctype == "Mode of Payment":
				return self.types.get(name)
			return None

		self.db.get_value.side_effect = db_get_value
		company = {"default_cash_account": "1110 - Cash - NM", "default_bank_account": "1201 - Bank - NM"}
		patches = [
			patch.object(invoices.frappe, "db", self.db),
			patch.object(
				invoices.frappe, "get_value", side_effect=lambda dt, name, field: company.get(field)
			),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_cash_type_mode_uses_the_cash_account(self):
		self.assertEqual(invoices.get_payment_account("Cash", "NM"), {"account": "1110 - Cash - NM"})

	def test_mobile_money_named_cash_does_not(self):
		self.assertEqual(invoices.get_payment_account("Natcash", "NM"), {"account": "1201 - Bank - NM"})
		self.assertEqual(invoices.get_payment_account("Mon Cash", "NM"), {"account": "1201 - Bank - NM"})
