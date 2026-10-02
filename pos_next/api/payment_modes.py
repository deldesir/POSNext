"""Which mode of payment a receipt belongs to, and which modes a till offers."""

import frappe


def profile_payment_modes(pos_profile):
	"""Modes of payment a POS profile offers, in profile order."""
	if not pos_profile:
		return []
	return frappe.get_all(
		"POS Payment Method",
		filters={"parent": pos_profile, "parenttype": "POS Profile"},
		fields=["mode_of_payment"],
		order_by="idx",
		pluck="mode_of_payment",
	)


def mode_of_payment_for_account(account, company):
	"""The mode of payment whose account for ``company`` is ``account``, if exactly one is set up."""
	if not account:
		return None
	modes = frappe.get_all(
		"Mode of Payment Account",
		filters={"default_account": account, "company": company},
		fields=["parent"],
		pluck="parent",
		limit=2,
	)
	return modes[0] if len(modes) == 1 else None


def receipt_mode_of_payment(payment_entry):
	"""The mode of a receipt: what it says, else what its receiving account implies."""
	mode = payment_entry.get("mode_of_payment")
	if mode:
		return mode
	return mode_of_payment_for_account(payment_entry.get("paid_to"), payment_entry.get("company"))
