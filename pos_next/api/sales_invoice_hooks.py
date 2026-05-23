# Copyright (c) 2025, BrainWise and contributors
# For license information, please see license.txt

"""
Sales Invoice Hooks
Event handlers for Sales Invoice document events
"""

import frappe
from frappe import _
from frappe.utils import cint, flt


def validate(doc, method=None):
	"""
	Validate hook for Sales Invoice.
	Apply tax inclusive settings based on POS Profile configuration.
	Auto-assign loyalty program to customer if enabled.

	Args:
		doc: Sales Invoice document
		method: Hook method name (unused)
	"""
	apply_tax_inclusive(doc)
	auto_assign_loyalty_program_on_invoice(doc)
	validate_payment_permissions(doc)


def apply_tax_inclusive(doc):
	"""
	Mark taxes as inclusive based on POS Profile setting.

	This function reads the tax_inclusive setting from POS Settings
	and applies it to all taxes in the invoice (except Actual charge type).

	Args:
		doc: Sales Invoice document
	"""
	if not doc.pos_profile:
		return

	try:
		# Get POS Settings for this profile
		pos_settings = frappe.db.get_value(
			"POS Settings",
			{"pos_profile": doc.pos_profile},
			["tax_inclusive"],
			as_dict=True
		)
		tax_inclusive = pos_settings.get("tax_inclusive", 0) if pos_settings else 0
	except Exception:
		tax_inclusive = 0

	has_changes = False
	for tax in doc.get("taxes", []):
		# Skip Actual charge type - these can't be inclusive
		if tax.charge_type == "Actual":
			if tax.included_in_print_rate:
				tax.included_in_print_rate = 0
				has_changes = True
			continue

		# Apply tax inclusive setting
		if tax_inclusive and not tax.included_in_print_rate:
			tax.included_in_print_rate = 1
			has_changes = True
		elif not tax_inclusive and tax.included_in_print_rate:
			tax.included_in_print_rate = 0
			has_changes = True

	# Recalculate if we made changes
	if has_changes:
		doc.calculate_taxes_and_totals()


def auto_assign_loyalty_program_on_invoice(doc):
	"""
	Auto-assign loyalty program to customer if loyalty is enabled in POS Settings
	but customer doesn't have a loyalty program yet.

	This ensures customers created before loyalty was enabled can still earn points.

	Args:
		doc: Sales Invoice document
	"""
	if not doc.is_pos or not doc.pos_profile or not doc.customer:
		return

	# Check if customer already has a loyalty program
	customer_loyalty = frappe.db.get_value("Customer", doc.customer, "loyalty_program")
	if customer_loyalty:
		return

	# Get POS Settings
	pos_settings = frappe.db.get_value(
		"POS Settings",
		{"pos_profile": doc.pos_profile},
		["enable_loyalty_program", "default_loyalty_program"],
		as_dict=True
	)

	if not pos_settings:
		return

	if not cint(pos_settings.get("enable_loyalty_program")):
		return

	loyalty_program = pos_settings.get("default_loyalty_program")
	if not loyalty_program:
		return

	# Assign loyalty program to customer
	frappe.db.set_value(
		"Customer",
		doc.customer,
		"loyalty_program",
		loyalty_program,
		update_modified=False
	)


def before_cancel(doc, method=None):
	"""
	Before Cancel hook for Sales Invoice.
	Cancel any credit redemption journal entries.

	Args:
		doc: Sales Invoice document
		method: Hook method name (unused)
	"""
	try:
		from pos_next.api.credit_sales import cancel_credit_journal_entries
		cancel_credit_journal_entries(doc.name)
	except Exception as e:
		frappe.log_error(
			title="Credit Sale JE Cancellation Error",
			message=f"Invoice: {doc.name}, Error: {str(e)}\n{frappe.get_traceback()}"
		)
		# Don't block invoice cancellation if JE cancellation fails
		frappe.msgprint(
			_("Warning: Some credit journal entries may not have been cancelled. Please check manually."),
			alert=True,
			indicator="orange"
		)


def validate_payment_permissions(doc):
	"""
	Validate if the cashier has permission to sell at credit or partial payment
	based on their POS Settings.
	"""
	if not doc.is_pos or not doc.pos_profile or doc.is_return:
		return

	# Only check for Sales Invoice
	if doc.doctype != "Sales Invoice":
		return

	# Get POS Settings for this profile
	pos_settings = frappe.db.get_value(
		"POS Settings",
		{"pos_profile": doc.pos_profile},
		["allow_credit_sale", "allow_partial_payment", "allow_customer_credit_payment"],
		as_dict=True
	)

	if not pos_settings:
		return

	allow_credit_sale = cint(pos_settings.get("allow_credit_sale"))
	allow_partial_payment = cint(pos_settings.get("allow_partial_payment"))
	allow_customer_credit_payment = cint(pos_settings.get("allow_customer_credit_payment"))

	# Calculate paid amount from payment entries
	paid_amount = flt(sum(flt(p.amount) for p in doc.get("payments", [])))
	grand_total = flt(doc.grand_total)

	# Check for Customer Credit redemption flag
	has_customer_credit = getattr(doc.flags, "pos_next_redeemed_customer_credit", 0) or getattr(doc, "pos_next_redeemed_customer_credit", 0)

	if has_customer_credit:
		if not allow_customer_credit_payment:
			frappe.throw(_("Customer credit payment is not allowed for this POS Profile."))
		return

	# Full Credit Sale: no payments recorded, grand_total > 0
	if paid_amount == 0 and grand_total > 0:
		if not allow_credit_sale:
			frappe.throw(_("Credit sale is not allowed for this POS Profile."))

	# Partial Payment: 0 < paid_amount < grand_total
	elif 0 < paid_amount < grand_total:
		# Allow a small threshold for floating point comparisons (e.g. 0.01)
		if grand_total - paid_amount > 0.01:
			if not allow_partial_payment:
				frappe.throw(_("Partial payment is not allowed for this POS Profile."))
