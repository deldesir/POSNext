# Copyright (c) 2025, Youssef Restom and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


class POSSettings(Document):
	"""Per-profile till settings.

	`allow_negative_stock` here is the till's opt-in to the company's permission in
	Stock Settings; it never writes that permission. Whether the company may hold
	negative stock stays a Stock Manager decision made in Stock Settings.
	"""

	def validate(self):
		"""Validate POS Settings"""
		# Guard against None values and validate discount percentage
		max_discount = flt(self.max_discount_allowed)
		if max_discount < 0 or max_discount > 100:
			frappe.throw("Max Discount Allowed must be between 0 and 100")

		# Guard against None values and validate search limit
		if self.use_limit_search:
			search_limit = cint(self.search_limit)
			if search_limit <= 0:
				frappe.throw("Search Limit must be greater than 0")

		# Validate use_exact_amount cannot be enabled with credit sale or partial payment
		if cint(self.use_exact_amount):
			if cint(self.allow_credit_sale):
				frappe.throw(
					"'Use Exact Amount for Non-Cash' cannot be enabled together with 'Allow Credit Sale'. "
					"Please disable Credit Sale first."
				)
			if cint(self.allow_partial_payment):
				frappe.throw(
					"'Use Exact Amount for Non-Cash' cannot be enabled together with 'Allow Partial Payment'. "
					"Please disable Partial Payment first."
				)


@frappe.whitelist()
def get_pos_settings(pos_profile):
	"""
	Get POS Settings for a specific POS Profile.

	Also carries the company-wide Stock Settings value as
	`_global_allow_negative_stock`, so the till knows whether its own
	`allow_negative_stock` opt-in is in force.
	"""
	from frappe import _

	if not pos_profile:
		return None

	# Check if user has access to this POS Profile
	has_access = frappe.db.exists("POS Profile User", {"parent": pos_profile, "user": frappe.session.user})

	if not has_access and not frappe.has_permission("POS Settings", "read"):
		frappe.throw(_("You don't have access to this POS Profile"))

	from pos_next.api.constants import merge_pos_settings

	row = frappe.db.get_value("POS Settings", {"pos_profile": pos_profile}, "*", as_dict=True)

	# If no settings exist, create default settings
	if not row:
		row = create_default_settings(pos_profile)

	# Runtime flags (miraaya_installed, magento_loyalty_available) are not columns
	settings = merge_pos_settings(row)

	with_global_negative_stock_flag(settings)

	from pos_next.integrations.registry import extend_bootstrap_settings

	extend_bootstrap_settings(settings, pos_profile)

	return settings


def with_global_negative_stock_flag(settings):
	"""Add the company-wide negative-stock permission the till's opt-in depends on.

	Read-only for the till: the value is owned by Stock Settings.
	"""
	settings["_global_allow_negative_stock"] = cint(
		frappe.db.get_single_value("Stock Settings", "allow_negative_stock") or 0
	)
	return settings


def create_default_settings(pos_profile):
	"""Create default POS Settings for a POS Profile"""
	doc = frappe.new_doc("POS Settings")
	doc.pos_profile = pos_profile
	doc.enabled = 1
	doc.insert()

	return doc.as_dict()


@frappe.whitelist()
def update_pos_settings(pos_profile, settings):
	"""Update POS Settings for a POS Profile"""
	import json

	from frappe import _

	if isinstance(settings, str):
		settings = json.loads(settings)

	# Check if user has access to this POS Profile
	has_access = frappe.db.exists("POS Profile User", {"parent": pos_profile, "user": frappe.session.user})

	if not has_access and not frappe.has_permission("POS Settings", "write"):
		frappe.throw(_("You don't have permission to update this POS Profile"))

	# Check if settings exist
	existing = frappe.db.exists("POS Settings", {"pos_profile": pos_profile})

	if existing:
		doc = frappe.get_doc("POS Settings", existing)
		doc.update(settings)
		doc.save()
	else:
		doc = frappe.new_doc("POS Settings")
		doc.pos_profile = pos_profile
		doc.update(settings)
		doc.insert()

	return with_global_negative_stock_flag(doc.as_dict())
