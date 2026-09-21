import { call } from "@/utils/apiWrapper";
import { DEFAULT_CURRENCY, DEFAULT_LOCALE, formatCurrency, formatCurrencyNumber } from "@/utils/currency";
import { logger } from "@/utils/logger";
import { getOfflineReceiptPayload } from "@/utils/offline/offlineReceiptCache";
import { getOfflineInvoiceByOfflineId } from "@/utils/offline/sync";
import { offlineWorker } from "@/utils/offline/workerClient";
import {
	printHTML as qzPrintHTML,
	printRawCommands as qzPrintRawCommands,
} from "@/utils/qzTray";

const log = logger.create("PrintInvoice");

const DEFAULT_PRINT_FORMAT = "POS Next Receipt";
// POS Profile name -> { printFormat, letterhead }, resolved once per session
const profilePrintSettingsCache = new Map();

// ============================================================================
// Shared helpers
// ============================================================================

/**
 * Fall back to summing payment rows when paid_amount is not set —
 * offline invoices lack paid_amount until server submission.
 */
function derivePaidAmount(invoiceData) {
	if (invoiceData.paid_amount != null) return invoiceData.paid_amount;
	if (!Array.isArray(invoiceData.payments)) return 0;
	return invoiceData.payments.reduce((sum, p) => sum + (Number.parseFloat(p.amount) || 0), 0);
}

/** Sales Invoices not yet on the server (offline queue / local receipt id). */
export function isLocalOnlyInvoiceName(name) {
	return (
		typeof name === "string" &&
		(name.startsWith("OFFLINE-") || name.startsWith("pos_offline_"))
	);
}

/**
 * Fire-and-forget: flag the queued invoice as printed so a later edit
 * can warn the cashier a physical receipt is already in the customer's hands.
 * Silently no-ops for synced / server-side invoices.
 */
function flagOfflineInvoicePrinted(invoiceName) {
	if (!isLocalOnlyInvoiceName(invoiceName)) return;
	// Don't await — printing should never block on this bookkeeping call.
	offlineWorker.markOfflineInvoicePrinted(invoiceName).catch((err) => {
		log.warn("Failed to mark offline invoice printed:", err?.message || err);
	});
}

/**
 * Build a minimal printable receipt doc from a raw queued invoice payload
 * (the dict stored in IndexedDB invoice_queue.data). Used when sessionStorage
 * has been wiped but the invoice is still in the local queue.
 */
function receiptDocFromQueuedInvoice(offlineId, raw) {
	const items = Array.isArray(raw.items) ? raw.items : [];
	const payments = Array.isArray(raw.payments) ? raw.payments : [];
	const grandTotal = Number.parseFloat(raw.grand_total) || 0;
	const paidAmount = payments.reduce((sum, p) => sum + (Number.parseFloat(p.amount) || 0), 0);
	return {
		name: offlineId,
		doctype: "Sales Invoice",
		is_offline: true,
		pos_profile: raw.pos_profile,
		posting_date: raw.posting_date || new Date().toISOString().slice(0, 10),
		company: raw.company,
		customer_name: raw.customer,
		items: items.map((item) => ({
			...item,
			quantity: item.quantity ?? item.qty,
		})),
		grand_total: grandTotal,
		total_taxes_and_charges: Number.parseFloat(raw.total_tax) || 0,
		discount_amount: Number.parseFloat(raw.total_discount) || 0,
		payments,
		paid_amount: paidAmount,
		change_amount: Number.parseFloat(raw.change_amount) || 0,
		outstanding_amount: Math.max(0, grandTotal - paidAmount),
		status: grandTotal - paidAmount < 0.01 ? "Paid" : "Unpaid",
		docstatus: 0,
	};
}

/**
 * Hydrate a local-only invoice from cache. Checks sessionStorage first
 * (fast path, survives within the tab), then falls back to IndexedDB
 * (survives page reloads while the invoice is still in the offline queue).
 * Prevents server print / get_invoice for synthetic pos_offline_* ids.
 */
export async function hydrateLocalOnlyInvoice(invoiceData) {
	if (!invoiceData?.name || !isLocalOnlyInvoiceName(invoiceData.name)) return invoiceData;
	if (invoiceData.items?.length > 0) return invoiceData;

	const cached = getOfflineReceiptPayload(invoiceData.name);
	if (cached?.items?.length > 0) return cached;

	// sessionStorage wiped (page reload) — rebuild from IndexedDB queue.
	try {
		const queued = await getOfflineInvoiceByOfflineId(invoiceData.name);
		if (queued?.items?.length > 0) {
			return receiptDocFromQueuedInvoice(invoiceData.name, queued);
		}
	} catch (err) {
		log.warn("IndexedDB hydrate fallback failed:", err?.message || err);
	}

	return invoiceData;
}

// ============================================================================
// Local receipt (offline invoices, QZ Tray for local docs, popup fallback)
// Mirrors the "POS Next Receipt" print format so a receipt reads the same
// whichever path produced it.
// ============================================================================

const RECEIPT_CONTEXT = "POS Receipt";
const RECEIPT_OPTIONS_KEY = "pos_next_receipt_options";

function loadReceiptOptions() {
	try {
		const stored = window.localStorage?.getItem(RECEIPT_OPTIONS_KEY);
		if (stored) return { printUomAfterQuantity: false, ...JSON.parse(stored) };
	} catch {
		// storage unavailable (private window, blocked site data)
	}
	return { printUomAfterQuantity: false };
}

let receiptOptions = loadReceiptOptions();

/**
 * Apply the receipt-relevant Print Settings from the bootstrap payload.
 * Kept in localStorage so an offline reload still prints the same way.
 * @param {{print_uom_after_quantity?: number|boolean}|null} printSettings
 */
export function configureReceipt(printSettings) {
	if (!printSettings) return;
	receiptOptions = {
		printUomAfterQuantity: Boolean(Number(printSettings.print_uom_after_quantity)),
	};
	try {
		window.localStorage?.setItem(RECEIPT_OPTIONS_KEY, JSON.stringify(receiptOptions));
	} catch {
		// storage unavailable: the in-memory value still applies this session
	}
}

const t = (msg, replace = null) => __(msg, replace, RECEIPT_CONTEXT);

function escapeHTML(value) {
	return String(value ?? "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

function num(value) {
	return Number.parseFloat(value) || 0;
}

function formatQty(value) {
	const rounded = Math.round(value * 1000) / 1000;
	return rounded.toLocaleString(DEFAULT_LOCALE, { maximumFractionDigits: 3 });
}

function receiptLine(label, value, cls = "") {
	return `<div class="pnr-line ${cls}"><span class="pnr-l">${label}</span><span class="pnr-r">${value}</span></div>`;
}

const RECEIPT_STYLES = `
	@page { margin: 0; }
	* { margin: 0; padding: 0; box-sizing: border-box; }
	body { margin: 0; padding: 4mm; background: #fff; }
	@media print {
		body { padding: 0 2mm; }
		.no-print { display: none; }
	}
	.pnr {
		width: 100%; max-width: 72mm; margin: 0 auto;
		font-family: "DejaVu Sans", Arial, Helvetica, sans-serif;
		font-size: 12px; line-height: 1.35; color: #000;
	}
	.pnr-center { text-align: center; }
	.pnr-company { font-size: 15px; font-weight: 700; letter-spacing: 0.3px; text-transform: uppercase; }
	.pnr-title { margin: 8px 0 6px; font-size: 13px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; }
	.pnr-banner { border: 1.5px solid #000; padding: 3px; margin: 0 0 6px; font-weight: 700; letter-spacing: 1px; text-align: center; text-transform: uppercase; }
	.pnr-rule { border-top: 1px dashed #000; margin: 6px 0; height: 0; }
	.pnr-line { display: table; width: 100%; }
	.pnr-line > .pnr-l { display: table-cell; text-align: left; vertical-align: top; word-wrap: break-word; padding-right: 6px; }
	.pnr-line > .pnr-r { display: table-cell; text-align: right; vertical-align: bottom; white-space: nowrap; width: 1%; }
	.pnr-meta { font-size: 11px; margin: 1px 0; table-layout: fixed; }
	.pnr-meta > .pnr-l { width: 30%; }
	.pnr-meta > .pnr-r { width: 70%; white-space: normal; vertical-align: top; }
	.pnr-head { font-size: 10px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; border-bottom: 1px solid #000; padding-bottom: 2px; margin-bottom: 4px; }
	.pnr-item { margin-bottom: 5px; page-break-inside: avoid; break-inside: avoid; }
	.pnr-item-name { font-weight: 700; word-wrap: break-word; }
	.pnr-item-calc { font-size: 11.5px; }
	.pnr-note { font-size: 10.5px; }
	.pnr-note > .pnr-l { padding-left: 8px; }
	.pnr-count { font-size: 10.5px; }
	.pnr-sum { margin: 1px 0; }
	.pnr-grand { font-size: 16px; font-weight: 700; border-top: 1.5px solid #000; border-bottom: 1.5px solid #000; padding: 4px 0; margin: 5px 0; }
	.pnr-due { font-weight: 700; border: 1.5px solid #000; padding: 3px 4px; margin-top: 5px; }
	.pnr-thanks { font-size: 11.5px; font-weight: 700; margin-top: 8px; }
`;

/**
 * Inner receipt HTML (no shell). Used for local/offline invoices and QZ Tray.
 */
export function buildReceiptHTML(invoiceData) {
	const isReturn = Boolean(invoiceData.is_return);
	const sgn = isReturn ? -1 : 1;
	const money = (value) => formatCurrencyNumber(num(value));
	const moneyWithSymbol = (value) =>
		formatCurrency(num(value), invoiceData.currency || DEFAULT_CURRENCY);

	const items = invoiceData.items || [];
	const itemsHtml = items
		.map((item) => {
			const qty = num(item.quantity ?? item.qty) * sgn;
			const rate = num(item.rate);
			const listRate = num(item.price_list_rate);
			const discounted = listRate > rate && !item.is_free_item;
			const unit = discounted ? listRate : rate;
			const gross = qty * unit;
			const net = item.amount != null ? num(item.amount) * sgn : qty * rate;
			const uom =
				receiptOptions.printUomAfterQuantity && item.uom ? ` ${escapeHTML(__(item.uom))}` : "";
			const qtyText = `${formatQty(qty)}${uom}`;
			const pct = num(item.discount_percentage)
				? ` ${formatQty(num(item.discount_percentage))} %`
				: "";
			return `
				<div class="pnr-item">
					<div class="pnr-item-name">${escapeHTML(item.item_name || item.item_code)}</div>
					${
						item.is_free_item
							? receiptLine(qtyText, t("Free"), "pnr-item-calc")
							: receiptLine(`${qtyText} ×&nbsp;${money(unit)}`, money(gross), "pnr-item-calc")
					}
					${discounted ? receiptLine(`${t("Discount")}${pct}`, `-${money(gross - net)}`, "pnr-note") : ""}
					${
						item.serial_no
							? receiptLine(
									`${t("Serial No")} ${escapeHTML(String(item.serial_no).replace(/\n/g, ", "))}`,
									"",
									"pnr-note"
							  )
							: ""
					}
					${item.batch_no ? receiptLine(`${t("Batch")} ${escapeHTML(item.batch_no)}`, "", "pnr-note") : ""}
				</div>`;
		})
		.join("");

	const grandTotal = num(invoiceData.grand_total);
	const roundedTotal = num(invoiceData.rounded_total);
	const totalDue =
		roundedTotal && !invoiceData.disable_rounded_total ? roundedTotal : grandTotal;
	const rounding = invoiceData.disable_rounded_total ? 0 : num(invoiceData.rounding_adjustment);
	const discount = Math.abs(num(invoiceData.discount_amount));
	const taxes = num(invoiceData.total_taxes_and_charges);
	const subtotal =
		invoiceData.total != null ? num(invoiceData.total) : grandTotal - taxes + discount - rounding;
	const payments = (invoiceData.payments || []).filter((p) => num(p.amount));
	const paidAmount = derivePaidAmount(invoiceData);
	const change = num(invoiceData.change_amount);
	const outstanding = num(invoiceData.outstanding_amount);
	const customer = invoiceData.customer_name || invoiceData.customer;
	const postedAt = invoiceData.posting_date
		? `${invoiceData.posting_date}${
				invoiceData.posting_time ? ` ${String(invoiceData.posting_time).slice(0, 5)}` : ""
		  }`
		: new Date().toLocaleString();

	return `
		<div class="pnr">
			<div class="pnr-center">
				<div class="pnr-company">${escapeHTML(invoiceData.company || "")}</div>
				<div class="pnr-title">${escapeHTML(
					invoiceData.header || (isReturn ? t("Credit Note") : t("Invoice"))
				)}</div>
			</div>
			${invoiceData.is_offline ? `<div class="pnr-banner">${t("Offline, pending sync")}</div>` : ""}

			${receiptLine(t("No."), escapeHTML(invoiceData.name), "pnr-meta")}
			${receiptLine(t("Date"), escapeHTML(postedAt), "pnr-meta")}
			${
				isReturn && invoiceData.return_against
					? receiptLine(t("Return of"), escapeHTML(invoiceData.return_against), "pnr-meta")
					: ""
			}
			${customer ? receiptLine(t("Customer"), escapeHTML(customer), "pnr-meta") : ""}

			<div class="pnr-rule"></div>

			${receiptLine(t("Item"), t("Amount"), "pnr-head")}
			${itemsHtml}
			<div class="pnr-count">${t("Items: {0}", [items.length])}</div>

			<div class="pnr-rule"></div>

			${discount || taxes || rounding ? receiptLine(t("Subtotal"), money(subtotal * sgn), "pnr-sum") : ""}
			${discount ? receiptLine(t("Discount"), `-${money(discount)}`, "pnr-sum") : ""}
			${taxes ? receiptLine(__("Tax"), money(taxes * sgn), "pnr-sum") : ""}
			${rounding ? receiptLine(t("Rounding"), money(rounding * sgn), "pnr-sum") : ""}
			${receiptLine(isReturn ? t("Refund Total") : t("Total"), moneyWithSymbol(totalDue * sgn), "pnr-grand")}

			${payments
				.map((p) => receiptLine(escapeHTML(__(p.mode_of_payment)), money(num(p.amount) * sgn), "pnr-sum"))
				.join("")}
			${
				payments.length > 1 || change
					? receiptLine(isReturn ? t("Refunded") : t("Paid"), money(num(paidAmount) * sgn), "pnr-sum")
					: ""
			}
			${change > 0 ? receiptLine(t("Change"), money(change), "pnr-sum") : ""}
			${
				!isReturn && outstanding > 0
					? receiptLine(t("Balance Due"), moneyWithSymbol(outstanding), "pnr-due")
					: ""
			}

			<div class="pnr-center pnr-thanks">${escapeHTML(
				invoiceData.footer || t("Thank you for your business!")
			)}</div>
		</div>`;
}

function buildReceiptDocumentHTML(invoiceData, { includeControls = false } = {}) {
	const controls = includeControls
		? `
			<div class="no-print" style="text-align: center; margin-top: 20px;">
				<button onclick="window.print()" style="padding: 10px 20px; font-size: 14px; cursor: pointer;">${__(
					"Print Receipt"
				)}</button>
				<button onclick="window.close()" style="padding: 10px 20px; font-size: 14px; cursor: pointer; margin-left: 10px;">${__(
					"Close"
				)}</button>
			</div>`
		: "";
	return `
		<!DOCTYPE html>
		<html>
		<head>
			<meta charset="UTF-8">
			<title>${__("Invoice - {0}", [invoiceData.name])}</title>
			<style>${RECEIPT_STYLES}</style>
		</head>
		<body>
			${buildReceiptHTML(invoiceData)}
			${controls}
		</body>
		</html>`;
}

/**
 * Resolve print format & letterhead from a POS Profile.
 * Returns defaults when the profile lookup fails so callers always get a value.
 */
async function resolvePrintSettings(posProfile, printFormat, letterhead) {
	if (printFormat) return { printFormat, letterhead };

	if (posProfile) {
		if (!profilePrintSettingsCache.has(posProfile)) {
			try {
				const doc = await call("frappe.client.get", {
					doctype: "POS Profile",
					name: posProfile,
				});
				if (doc) {
					profilePrintSettingsCache.set(posProfile, {
						printFormat: doc.print_format || DEFAULT_PRINT_FORMAT,
						letterhead: doc.letter_head || null,
					});
				}
			} catch (err) {
				log.warn("Could not fetch POS Profile print settings:", err);
			}
		}
		const cached = profilePrintSettingsCache.get(posProfile);
		if (cached) {
			return { printFormat: cached.printFormat, letterhead: letterhead || cached.letterhead };
		}
	}

	return { printFormat: DEFAULT_PRINT_FORMAT, letterhead };
}

/**
 * Seed the print settings of the session's POS Profile (from the bootstrap
 * payload) so the first print does not wait on a lookup: browsers only allow
 * the print window shortly after the cashier's click.
 * @param {{name: string, print_format?: string, letter_head?: string}|null} posProfile
 */
export function rememberProfilePrintSettings(posProfile) {
	if (!posProfile?.name) return;
	profilePrintSettingsCache.set(posProfile.name, {
		printFormat: posProfile.print_format || DEFAULT_PRINT_FORMAT,
		letterhead: posProfile.letter_head || null,
	});
}

/**
 * Print language for an invoice: the document's own language (ERPNext fills it
 * from the customer / system default, and desk printing uses it too). Empty
 * means "let the server use the signed-in user's language".
 */
function printLanguage(invoiceData) {
	return invoiceData?.language || "";
}

// ============================================================================
// Browser printing (opens /printview in a new window)
// ============================================================================

/**
 * Open Frappe's /printview in a new browser window.
 * The page includes trigger_print=1 so the OS print dialog appears automatically.
 * Falls back to the hardcoded receipt template if the popup is blocked.
 */
export async function printInvoice(invoiceData, printFormat = null, letterhead = null) {
	try {
		if (!invoiceData?.name) throw new Error("Invalid invoice data");

		invoiceData = await hydrateLocalOnlyInvoice(invoiceData);

		// Pending offline / local IDs are not in ERPNext — use embedded receipt HTML.
		if (isLocalOnlyInvoiceName(invoiceData.name)) {
			if (invoiceData.items?.length > 0) return printInvoiceCustom(invoiceData);
			throw new Error(
				__(
					"This offline receipt is no longer in browser storage. Sync the invoice, then print from history."
				)
			);
		}

		const doctype = invoiceData.doctype || "Sales Invoice";
		// No explicit format: use the invoice's POS Profile (the checkout path lands here)
		const settings = await resolvePrintSettings(invoiceData.pos_profile, printFormat, letterhead);
		const format = settings.printFormat;
		const letterheadName = settings.letterhead;

		const params = new URLSearchParams({
			doctype,
			name: invoiceData.name,
			format,
			no_letterhead: letterheadName ? 0 : 1,
			trigger_print: 1,
			_t: Date.now(),
		});
		const lang = printLanguage(invoiceData);
		if (lang) params.append("_lang", lang);
		if (letterheadName) params.append("letterhead", letterheadName);

					// Determine subpath dynamically
			let subpath = "";
			if (window.frappe && frappe.router && frappe.router._subpath_prefix) {
				subpath = frappe.router._subpath_prefix;
			} else if (window.location.pathname.startsWith("/erp")) {
				subpath = "/erp";
			}
			subpath = subpath.trim().replace(/\/+$/, "");

			const printUrl = `${subpath}/printview?${params.toString()}`;
			const printWindow = window.open(printUrl, "_blank", "width=800,height=600");
		if (!printWindow) {
			throw new Error("Popup blocked — check your browser settings.");
		}
		return true;
	} catch (error) {
		log.error("Browser print failed:", error);
		if (isLocalOnlyInvoiceName(invoiceData?.name) && !(invoiceData.items?.length > 0)) {
			throw error;
		}
		return printInvoiceCustom(invoiceData);
	}
}

/**
 * Fetch an invoice by name, resolve its POS Profile print settings,
 * then open the browser print window.
 */
export async function printInvoiceByName(invoiceName, printFormat = null, letterhead = null) {
	if (isLocalOnlyInvoiceName(invoiceName)) {
		const localDoc = await hydrateLocalOnlyInvoice({ name: invoiceName });
		if (!localDoc.items?.length) {
			throw new Error(
				__(
					"This offline receipt is no longer in browser storage. Complete checkout again or sync, then print from history."
				)
			);
		}
		const settings = await resolvePrintSettings(localDoc.pos_profile, printFormat, letterhead);
		return printInvoice(localDoc, settings.printFormat, settings.letterhead);
	}
	const invoiceDoc = await call("pos_next.api.invoices.get_invoice", {
		invoice_name: invoiceName,
	});
	if (!invoiceDoc) throw new Error("Invoice not found");

	const settings = await resolvePrintSettings(invoiceDoc.pos_profile, printFormat, letterhead);
	return printInvoice(invoiceDoc, settings.printFormat, settings.letterhead);
}

// ============================================================================
// Silent printing (QZ Tray — no browser dialog)
// ============================================================================

export async function silentPrintDoc(doctype, name, printFormat, lang = "") {
	const result = await call("frappe.www.printview.get_html_and_style", {
		doc: doctype,
		name,
		print_format: printFormat,
		no_letterhead: 1,
		// read by Frappe's request language resolution, not by the method itself
		...(lang ? { _lang: lang } : {}),
	});

	const html = result?.html || result?.message?.html;
	const style = result?.style || result?.message?.style || "";
	if (!html) throw new Error("Failed to get print HTML from server");

	const fullHTML = `<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><style>${style}</style></head>
<body>${html}</body>
</html>`;

	await qzPrintHTML(fullHTML);
	return true;
}

/**
 * Fetch the server-rendered print HTML and send it to a thermal printer
 * via QZ Tray. Uses Frappe's get_html_and_style API which returns the
 * print format HTML + its inline styles (standard.css, print style, custom CSS).
 * Note: print.bundle.css (Bootstrap grid/tables) is NOT included — print
 * formats that rely on Bootstrap layout classes may render differently.
 * Paper size and margins are controlled by the QZ Tray config in qzTray.js.
 */
export async function silentPrintInvoice(invoiceName, printFormat = null, invoiceData = null) {
	if (isLocalOnlyInvoiceName(invoiceName)) {
		const doc = await hydrateLocalOnlyInvoice({ name: invoiceName });
		if (doc.items?.length > 0) return silentPrintInvoiceFromDoc(doc);
		throw new Error(
			__(
				"This offline receipt is no longer in browser storage. Use browser print from the success dialog after checkout."
			)
		);
	}
	const { printFormat: format } = await resolvePrintSettings(invoiceData?.pos_profile, printFormat, null);

	await silentPrintDoc("Sales Invoice", invoiceName, format, printLanguage(invoiceData));
	log.info(`Silent print sent for ${invoiceName}`);
	return true;
}

/**
 * Silent-print a full invoice dict using the same HTML as the offline receipt fallback.
 */
export async function silentPrintInvoiceFromDoc(invoiceData) {
	const fullHTML = buildReceiptDocumentHTML(invoiceData, { includeControls: false });
	await qzPrintHTML(fullHTML);
	log.info(`Silent print (local receipt) for ${invoiceData?.name}`);
	flagOfflineInvoicePrinted(invoiceData?.name);
	return true;
}

/**
 * Try silent print, fall back to browser print on failure.
 * silentPrintInvoice → qzPrintHTML → connect() handles auto-reconnect
 * internally, so no separate connection logic is needed here.
 */
export async function printWithSilentFallback(invoiceData, printFormat = null) {
	invoiceData = await hydrateLocalOnlyInvoice(invoiceData);
	const invoiceName = invoiceData?.name;
	if (!invoiceName) throw new Error("Invalid invoice data — missing name");

	if (isLocalOnlyInvoiceName(invoiceName) && invoiceData.items?.length > 0) {
		try {
			await silentPrintInvoiceFromDoc(invoiceData);
			return { method: "silent", success: true };
		} catch (err) {
			log.warn("Silent local receipt failed, falling back to browser:", err?.message || err);
		}
		try {
			printInvoiceCustom(invoiceData);
			return { method: "browser", success: true };
		} catch (err) {
			log.error("Browser print for local receipt failed:", err);
			return { method: "browser", success: false };
		}
	}

	try {
		await silentPrintInvoice(invoiceName, printFormat, invoiceData);
		return { method: "silent", success: true };
	} catch (err) {
		log.warn("Silent print failed, falling back to browser:", err?.message || err);
	}

	try {
		await printInvoiceByName(invoiceName, printFormat);
		return { method: "browser", success: true };
	} catch (err) {
		log.error("Browser print fallback also failed:", err);
		return { method: "browser", success: false };
	}
}

// ============================================================================
// Hardcoded receipt fallback (used only when /printview popup is blocked)
// ============================================================================

/**
 * Renders the receipt locally in a popup window. Used offline, for pending
 * local-only invoices, and as the fallback when /printview is unavailable.
 */
export function printInvoiceCustom(invoiceData) {
	const printWindow = window.open("", "_blank", "width=350,height=600");
	if (!printWindow) {
		log.error("Cannot open print window — popup blocked.");
		throw new Error(__("Popup blocked — check your browser settings."));
	}

	const printContent = buildReceiptDocumentHTML(invoiceData, { includeControls: true });

	printWindow.document.write(printContent);
	printWindow.document.close();
	printWindow.onload = () => {
		setTimeout(() => printWindow.print(), 250);
	};
	flagOfflineInvoicePrinted(invoiceData?.name);
	return true;
}
