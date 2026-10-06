import frappe
from frappe.utils import flt


def execute():
	"""Shifts closed before the credit-notes figures existed: derive them from their rows.

	A credit note is a return invoice with no payment rows (refunded to customer credit)."""
	frappe.reload_doc("pos_next", "doctype", "pos_closing_shift")
	rows = frappe.db.sql(
		"""
		select r.parent, r.sales_invoice, si.base_grand_total
		from `tabSales Invoice Reference` r
		join `tabSales Invoice` si on si.name = r.sales_invoice
		where r.parenttype = 'POS Closing Shift' and si.is_return = 1 and si.docstatus = 1
		  and not exists (select 1 from `tabSales Invoice Payment` p where p.parent = si.name)
		""",
		as_dict=True,
	)
	per_shift = {}
	for r in rows:
		total, count = per_shift.get(r.parent, (0, 0))
		per_shift[r.parent] = (total + abs(flt(r.base_grand_total)), count + 1)
	for shift, (total, count) in per_shift.items():
		frappe.db.set_value(
			"POS Closing Shift",
			shift,
			{"credit_notes_total": total, "credit_notes_count": count},
			update_modified=False,
		)
