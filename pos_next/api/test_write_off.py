"""Remainders within the POS Profile's write-off limit are absorbed, not carried as dues."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt
from pypika.functions import Sum

from pos_next.api import partial_payments, write_off
from pos_next.test_promotions import (
	_resolve_customer_group,
	_resolve_item_group,
	_resolve_mode_of_payment,
	_resolve_territory,
)

CUSTOMER = "_Test Write-Off Customer"
ITEM = "_Test Write-Off Item"


class TestWriteOffRemainder(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.get_all(
			"Company",
			filters={"default_receivable_account": ["is", "set"], "default_income_account": ["is", "set"]},
			fields=["name", "default_receivable_account", "default_income_account", "cost_center"],
			order_by="creation asc",
			limit=1,
		)[0]
		cls.mode_of_payment = _resolve_mode_of_payment(cls.company.name)
		cls.write_off_account = frappe.get_all(
			"Account",
			filters={"company": cls.company.name, "root_type": "Expense", "is_group": 0, "disabled": 0},
			order_by="name asc",
			limit=1,
			pluck="name",
		)[0]
		cls.terms = frappe._dict(
			write_off_account=cls.write_off_account,
			write_off_cost_center=cls.company.cost_center,
			write_off_limit=1,
		)
		frappe.get_doc(
			doctype="Customer",
			customer_name=CUSTOMER,
			customer_group=_resolve_customer_group(),
			territory=_resolve_territory(),
		).insert(ignore_permissions=True, ignore_if_duplicate=True)
		frappe.get_doc(
			doctype="Item", item_code=ITEM, item_group=_resolve_item_group(), stock_uom="Nos", is_stock_item=0
		).insert(ignore_permissions=True, ignore_if_duplicate=True)

	def setUp(self):
		frappe.db.savepoint("write_off_remainder")

	def tearDown(self):
		frappe.db.rollback(save_point="write_off_remainder")

	def _pos_sale(self, rate, paid):
		c = self.company
		doc = frappe.get_doc(
			doctype="Sales Invoice",
			company=c.name,
			currency=frappe.get_cached_value("Company", c.name, "default_currency"),
			conversion_rate=1,
			customer=CUSTOMER,
			is_pos=1,
			disable_rounded_total=1,  # the POS sends exact totals; the remainder is the cents
			debit_to=c.default_receivable_account,
			cost_center=c.cost_center,
			items=[{"item_code": ITEM, "qty": 1, "rate": rate, "income_account": c.default_income_account}],
			payments=[{"mode_of_payment": self.mode_of_payment, "amount": paid}],
		)
		doc.run_method("set_missing_values")
		doc.calculate_taxes_and_totals()
		return doc

	def _account_balance(self, account, voucher):
		gle = frappe.qb.DocType("GL Entry")
		query = frappe.qb.from_(gle).select(Sum(gle.debit - gle.credit))
		return flt(
			query.where(
				(gle.account == account) & (gle.voucher_no == voucher) & (gle.is_cancelled == 0)
			).run()[0][0]
		)

	def test_checkout_remainder_within_limit_is_written_off(self):
		doc = self._pos_sale(rate=100.01, paid=100)
		self.assertEqual(flt(doc.outstanding_amount, 2), 0.01)

		with patch.object(write_off, "write_off_terms", return_value=self.terms):
			self.assertTrue(write_off.auto_write_off_checkout_remainder(doc, "any profile"))
		doc.insert(ignore_permissions=True).submit()

		doc.reload()
		self.assertEqual(
			(flt(doc.write_off_amount, 2), flt(doc.outstanding_amount, 2), doc.status), (0.01, 0, "Paid")
		)
		self.assertEqual(self._account_balance(self.write_off_account, doc.name), 0.01)

	def test_checkout_remainder_above_limit_stays_due(self):
		doc = self._pos_sale(rate=102, paid=100)
		with patch.object(write_off, "write_off_terms", return_value=self.terms):
			self.assertFalse(write_off.auto_write_off_checkout_remainder(doc, "any profile"))
		self.assertFalse(doc.get("write_off_outstanding_amount_automatically"))
		self.assertEqual(flt(doc.outstanding_amount, 2), 2)

	def test_checkout_with_nothing_taken_is_a_credit_sale_not_a_remainder(self):
		doc = self._pos_sale(rate=0.5, paid=0)
		with patch.object(write_off, "write_off_terms", return_value=self.terms):
			self.assertFalse(write_off.auto_write_off_checkout_remainder(doc, "any profile"))
		self.assertEqual(flt(doc.outstanding_amount, 2), 0.5)

	def test_explicit_write_off_is_kept(self):
		doc = self._pos_sale(rate=100.01, paid=100)
		doc.write_off_amount = 0.01
		with patch.object(write_off, "write_off_terms", return_value=self.terms):
			self.assertFalse(write_off.auto_write_off_checkout_remainder(doc, "any profile"))

	def test_receipt_remainder_within_limit_settles_the_invoice(self):
		sale = self._pos_sale(rate=100.01, paid=0)
		sale.flags.pos_next_credit_sale = 1
		sale.insert(ignore_permissions=True).submit()
		self.assertEqual(
			flt(frappe.db.get_value("Sales Invoice", sale.name, "outstanding_amount"), 2), 100.01
		)

		with patch.object(write_off, "write_off_terms", return_value=self.terms):
			pe_name = partial_payments.create_payment_entry(sale.name, 100, self.mode_of_payment)

		pe = frappe.get_doc("Payment Entry", pe_name)
		self.assertEqual(
			(flt(pe.paid_amount, 2), flt(pe.total_allocated_amount, 2), flt(pe.difference_amount, 2)),
			(100, 100.01, 0),
		)
		self.assertEqual(
			[(d.account, flt(d.amount, 2)) for d in pe.deductions], [(self.write_off_account, 0.01)]
		)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", sale.name, ["outstanding_amount", "status"]), (0, "Paid")
		)
		self.assertEqual(self._account_balance(self.write_off_account, pe_name), 0.01)

	def test_receipt_remainder_above_limit_stays_due(self):
		sale = self._pos_sale(rate=105, paid=0)
		sale.flags.pos_next_credit_sale = 1
		sale.insert(ignore_permissions=True).submit()

		with patch.object(write_off, "write_off_terms", return_value=self.terms):
			partial_payments.create_payment_entry(sale.name, 100, self.mode_of_payment)

		self.assertEqual(
			frappe.db.get_value("Sales Invoice", sale.name, ["outstanding_amount", "status"]),
			(5, "Partly Paid"),
		)
