"""Keep ERPNext's standard permission grants beside the cashier rows.

Custom DocPerm is all-or-nothing per DocType: as soon as one row exists for a
DocType, Frappe reads only Custom DocPerm for it and the standard DocPerm rows
stop applying. The cashier fixture (fixtures/custom_docperm.json) inserts bare
rows, so a fresh site lost every standard ERPNext grant on those DocTypes: Stock
User could no longer read Item, Accounts User lost Payment Entry, and so on.
Frappe's own add_permission avoids this by copying the standard rows first
(setup_custom_perms); this module does the same after the fact, idempotently,
for the DocTypes the fixture touches. It runs after install and after migrate.
"""

import json
import os

import frappe

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "custom_docperm.json")
META_FIELDS = {"name", "creation", "modified", "modified_by", "owner", "docstatus", "idx", "parent", "parenttype", "parentfield"}


def fixture_doctypes() -> list[str]:
	"""The DocTypes the cashier fixture carries rows for."""
	with open(FIXTURE) as fh:
		return sorted({row["parent"] for row in json.load(fh)})


def missing_standard_grants(doctype: str) -> list[dict]:
	"""Standard DocPerm rows with no Custom DocPerm counterpart on (role, permlevel, if_owner).

	Empty when the DocType has no Custom DocPerm at all: the standard rows apply then.
	"""
	custom = {
		(row.role, int(row.permlevel or 0), int(row.if_owner or 0))
		for row in frappe.get_all("Custom DocPerm", filters={"parent": doctype}, fields=["role", "permlevel", "if_owner"])
	}
	if not custom:
		return []
	return [
		row
		for row in frappe.get_all("DocPerm", filters={"parent": doctype}, fields=["*"])
		if (row.role, int(row.permlevel or 0), int(row.if_owner or 0)) not in custom
	]


def ensure_standard_grants(doctypes: list[str] | None = None) -> dict[str, int]:
	"""Re-insert, as Custom DocPerm, every standard grant the bare fixture rows displaced.

	Returns {doctype: rows restored}. Adds rows only; never removes or edits a grant,
	so a deliberate narrowing made on a site through Role Permission Manager survives
	as long as the role still has some row.
	"""
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

	restored = {}
	for doctype in doctypes or fixture_doctypes():
		if not frappe.db.exists("DocType", doctype):
			continue
		rows = missing_standard_grants(doctype)
		for row in rows:
			perm = frappe.new_doc("Custom DocPerm")
			perm.update({k: v for k, v in row.items() if k not in META_FIELDS})
			perm.parent, perm.parenttype, perm.parentfield = doctype, "DocType", "permissions"
			perm.insert(ignore_permissions=True)
		if rows:
			validate_permissions_for_doctype(doctype)
			frappe.clear_cache(doctype=doctype)
			restored[doctype] = len(rows)
	if restored:
		frappe.db.commit()
	return restored
