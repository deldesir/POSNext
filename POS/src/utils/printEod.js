import { logger } from "@/utils/logger";

import { silentPrintDoc } from "./printInvoice";

const log = logger.create("PrintEod");

const EOD_PRINT_FORMAT = "POS Next EOD Report";

/**
 * Open the server-rendered print view for a document in a new window and
 * trigger the browser's print dialog. Used as a fallback when QZ Tray silent
 * printing is unavailable (e.g. an Android till, or no desktop QZ Tray).
 */
function browserPrintDoc(doctype, name, printFormat) {
	let subpath = "";
	if (window.frappe?.router?._subpath_prefix) {
		subpath = window.frappe.router._subpath_prefix;
	} else if (window.location.pathname.startsWith("/erp")) {
		subpath = "/erp";
	}
	subpath = subpath.trim().replace(/\/+$/, "");

	const params = new URLSearchParams({
		doctype,
		name,
		format: printFormat,
		no_letterhead: 1,
		_lang: "en",
		trigger_print: 1,
		_t: Date.now(),
	});

	const printWindow = window.open(
		`${subpath}/printview?${params.toString()}`,
		"_blank",
		"width=800,height=600",
	);
	if (!printWindow) {
		throw new Error(__("Popup blocked — check your browser settings."));
	}
}

export async function printEODReport(closingShiftName) {
	// Try silent thermal printing via QZ Tray first (desktop tills), then fall
	// back to browser print so the EOD report still prints on Android tills or
	// wherever QZ Tray isn't set up — mirroring the receipt print path.
	try {
		await silentPrintDoc("POS Closing Shift", closingShiftName, EOD_PRINT_FORMAT);
	} catch (err) {
		log.warn("Silent EOD print failed, falling back to browser:", err?.message || err);
		browserPrintDoc("POS Closing Shift", closingShiftName, EOD_PRINT_FORMAT);
	}
}
