import frappe


def execute():
	"""Linked POS returns post their credit against the original invoice; the due they stored
	on themselves duplicated that credit. Zero it wherever the ledger holds nothing against
	the return itself (see sales_invoice_hooks.zero_linked_return_outstanding)."""
	frappe.db.sql(
		"""
		update `tabSales Invoice` si
		set si.outstanding_amount = 0
		where si.docstatus = 1 and si.is_pos = 1 and si.is_return = 1
		  and ifnull(si.return_against, '') != '' and si.update_outstanding_for_self = 0
		  and abs(si.outstanding_amount) > 0.005
		  and not exists (
			select 1 from `tabGL Entry` gl
			join `tabAccount` a on a.name = gl.account
			where gl.is_cancelled = 0 and a.account_type = 'Receivable' and gl.against_voucher = si.name
		  )
		"""
	)
