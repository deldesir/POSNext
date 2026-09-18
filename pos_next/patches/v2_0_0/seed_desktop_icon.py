import frappe
from frappe.utils.install import create_desktop_icons_for_app


def execute():
	"""Give existing sites the POS Next app tile.

	Frappe seeds Desktop Icons from ``add_to_apps_screen`` only on ``after_app_install``.
	Sites installed before the hook existed never got a tile, so seed once here. The
	seeder is idempotent: it only creates icons that do not exist yet, and does nothing on
	sites that use the Apps page instead of the icon grid.
	"""
	create_desktop_icons_for_app("pos_next")
	frappe.clear_cache()
