"""Refuse stock documents whose lines carry a conversion factor the item does not know.

When a line's UOM is not the item's stock UOM, ERPNext looks the factor up in the
item's UOM table when the UOM is chosen. If the UOM is not in that table yet, the
lookup silently falls back to 1.0, and a factor typed or fetched earlier is never
re-checked when the table changes. A "Caisse 24" received with factor 1 books 2
units instead of 48, values each at the price of a whole case, and every later sale
carries that cost. This check runs on validate and stops the document instead.
"""

import frappe
from frappe import _
from frappe.utils import flt

# Relative tolerance for comparing factors (they are stored with 9 decimals)
FACTOR_TOLERANCE = 1e-6


def expected_conversion_factor(item_code, uom, stock_uom):
	"""Factor the item (or its template) defines for `uom`, else the global UOM
	conversion between the two units, else None when nothing is defined."""
	if not item_code or not uom or uom == stock_uom:
		return 1.0
	variant_of = frappe.get_cached_value("Item", item_code, "variant_of")
	for code in (item_code, variant_of):
		if not code:
			continue
		factor = frappe.db.get_value("UOM Conversion Detail", {"parent": code, "uom": uom}, "conversion_factor")
		if factor:
			return flt(factor)
	from erpnext.stock.doctype.item.item import get_uom_conv_factor

	factor = get_uom_conv_factor(uom, stock_uom)
	return flt(factor) if factor else None


def line_problems(doc):
	"""Messages for every item row whose conversion factor is missing or disagrees
	with what the item defines. Rows in the stock UOM are ERPNext's own business."""
	problems = []
	for row in doc.get("items") or []:
		item_code, uom = row.get("item_code"), row.get("uom")
		if not item_code or not uom:
			continue
		stock_uom = row.get("stock_uom") or frappe.get_cached_value("Item", item_code, "stock_uom")
		if uom == stock_uom:
			continue
		expected = expected_conversion_factor(item_code, uom, stock_uom)
		actual = flt(row.get("conversion_factor"))
		if expected is None:
			problems.append(
				_("Row {0}: no conversion factor is defined for {1} on item {2}. Add {1} to the item's UOM table before using it.").format(
					row.idx, frappe.bold(uom), frappe.bold(item_code)
				)
			)
		elif abs(actual - expected) > FACTOR_TOLERANCE * max(1.0, expected):
			problems.append(
				_("Row {0}: conversion factor {1} for {2} on item {3} does not match the item's {4}. Re-select the UOM to refresh it.").format(
					row.idx, frappe.bold(actual), frappe.bold(uom), frappe.bold(item_code), frappe.bold(expected)
				)
			)
	return problems


def validate_conversion_factors(doc, method=None):
	"""doc_events validate hook for the stock-moving transaction doctypes."""
	if doc.get("is_return"):
		# a return mirrors the original document's lines, whatever the item says today
		return
	problems = line_problems(doc)
	if problems:
		frappe.throw("<br>".join(problems), title=_("UOM conversion check"))
