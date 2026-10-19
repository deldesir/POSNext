"""Put back the standard ERPNext grants the bare cashier fixture displaced on existing sites.

after_migrate does the same on every migrate; the patch records that it ran once.
"""

import frappe


def execute():
	from pos_next.permissions import ensure_standard_grants

	restored = ensure_standard_grants()
	if restored:
		frappe.db.commit()
