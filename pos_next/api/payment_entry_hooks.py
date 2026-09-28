"""Payment Entry hooks."""

import frappe

from pos_next.api.partial_payments import SHIFT_FIELD, _shift_field_available, get_session_open_shift


def stamp_pos_opening_shift(doc, method=None):
	"""Give a customer receipt submitted outside the POS app the submitter's open shift.

	The POS path (``partial_payments.create_payment_entry``) sets the shift
	itself.  A receipt typed in the desk Payment Entry form while the cashier
	is running a shift is money in that drawer all the same, yet it carried no
	shift and so never reached a closing.  Only at submit, only for money
	received from a customer, and never over a value already set.
	"""
	if doc.docstatus != 1 or doc.get("payment_type") != "Receive" or doc.get("party_type") != "Customer":
		return
	if doc.get(SHIFT_FIELD) or not _shift_field_available():
		return

	shift = get_session_open_shift()
	if shift:
		doc.set(SHIFT_FIELD, shift)
