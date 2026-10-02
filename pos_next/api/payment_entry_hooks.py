"""Payment Entry hooks."""

import frappe

from pos_next.api.partial_payments import SHIFT_FIELD, _shift_field_available, get_session_open_shift
from pos_next.api.payment_modes import profile_payment_modes, receipt_mode_of_payment


def stamp_pos_opening_shift(doc, method=None):
	"""Give a customer receipt submitted outside the POS app the submitter's open shift.

	The POS path (``partial_payments.create_payment_entry``) sets the shift
	itself.  A receipt typed in the desk Payment Entry form while the cashier
	is running a shift is money in that drawer all the same, yet it carried no
	shift and so never reached a closing.

	Only receipts taken by a method the till offers belong to it.  A wholesale
	customer's bank transfer keyed in by the same person stays a back-office
	document: it is not in the drawer and the cash-up has no bucket for it.
	A receipt whose mode is blank takes the mode its receiving account implies,
	so the closing can reconcile it.  Only at submit, only for money received
	from a customer, and never over a value already set.
	"""
	if doc.docstatus != 1 or doc.get("payment_type") != "Receive" or doc.get("party_type") != "Customer":
		return
	if doc.get(SHIFT_FIELD) or not _shift_field_available():
		return

	shift = get_session_open_shift()
	if not shift:
		return

	mode = receipt_mode_of_payment(doc)
	till_modes = profile_payment_modes(frappe.db.get_value("POS Opening Shift", shift, "pos_profile"))
	if not mode or mode not in till_modes:
		return

	if not doc.get("mode_of_payment"):
		doc.mode_of_payment = mode
	doc.set(SHIFT_FIELD, shift)
