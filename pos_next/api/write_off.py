"""Remainders nobody will collect: whole-gourde money against a due with cents.

The POS Profile's write-off account and limit say how much of a shortfall the business
absorbs instead of carrying it as a receivable (ERPNext applies the same rule to consolidated
POS invoices). Checkout and later receipts both settle within those terms, so a sale paid
4300 against 4300.01 ends Paid instead of Overdue by 0.01.
"""

import frappe
from frappe.utils import flt


def write_off_terms(pos_profile):
	"""The profile's write-off account, cost center and limit, or None when it absorbs nothing."""
	if not pos_profile:
		return None
	terms = frappe.db.get_value(
		"POS Profile",
		pos_profile,
		["write_off_account", "write_off_cost_center", "write_off_limit"],
		as_dict=True,
	)
	if not terms or not terms.write_off_account or flt(terms.write_off_limit) <= 0:
		return None
	return terms


def auto_write_off_checkout_remainder(invoice_doc, pos_profile):
	"""Money was taken and what is left is within the limit: let ERPNext write it off.

	Sets the fields ERPNext's totals engine reads (write_off_outstanding_amount_automatically,
	write_off_account) and recomputes, so the invoice submits Paid with the remainder booked
	to the write-off account. A sale with nothing taken is a credit sale, not a remainder,
	and a write-off the cashier chose explicitly is kept as is.
	"""
	if invoice_doc.doctype != "Sales Invoice" or invoice_doc.get("is_return"):
		return False
	if flt(invoice_doc.get("write_off_amount")):
		return False
	if sum(flt(p.amount) for p in invoice_doc.get("payments") or []) <= 0:
		return False
	terms = write_off_terms(pos_profile)
	if not terms:
		return False
	remainder = flt(invoice_doc.get("outstanding_amount"), invoice_doc.precision("outstanding_amount"))
	if not 0 < remainder <= flt(terms.write_off_limit):
		return False
	invoice_doc.write_off_account = terms.write_off_account
	invoice_doc.write_off_cost_center = terms.write_off_cost_center or invoice_doc.get("cost_center")
	invoice_doc.write_off_outstanding_amount_automatically = 1
	invoice_doc.calculate_taxes_and_totals()
	return True


def write_off_receipt_remainder(pe, invoice, amount):
	"""A later receipt that leaves a remainder within the limit settles the invoice in full.

	The Payment Entry allocates the whole due and books the remainder as a deduction to the
	write-off account - what ERPNext's own "Write Off Difference Amount" does by hand.
	"""
	due = flt(invoice.outstanding_amount)
	remainder = flt(due - flt(amount), invoice.precision("outstanding_amount"))
	terms = write_off_terms(invoice.get("pos_profile"))
	if not terms or not 0 < remainder <= flt(terms.write_off_limit):
		return False
	refs = [
		r
		for r in pe.get("references")
		if r.reference_doctype == "Sales Invoice" and r.reference_name == invoice.name
	]
	if not refs:
		return False
	refs[0].allocated_amount = due
	pe.append(
		"deductions",
		{
			"account": terms.write_off_account,
			"cost_center": terms.write_off_cost_center
			or invoice.get("cost_center")
			or frappe.get_cached_value("Company", pe.company, "cost_center"),
			"amount": remainder,
		},
	)
	return True
