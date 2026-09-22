import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

// printInvoice.js pulls in browser-only modules (IndexedDB worker, QZ Tray); the
// receipt builder needs none of them.
vi.mock("@/utils/apiWrapper", () => ({ call: vi.fn() }));
vi.mock("@/utils/offline/offlineReceiptCache", () => ({ getOfflineReceiptPayload: vi.fn() }));
vi.mock("@/utils/offline/sync", () => ({ getOfflineInvoiceByOfflineId: vi.fn() }));
vi.mock("@/utils/offline/workerClient", () => ({ offlineWorker: {} }));
vi.mock("@/utils/qzTray", () => ({ printHTML: vi.fn(), printRawCommands: vi.fn() }));

let buildReceiptHTML;
let configureReceipt;

beforeAll(async () => {
	globalThis.__ = (msg, replace) =>
		replace ? msg.replace(/{(\d+)}/g, (_, n) => replace[n] ?? _) : msg;
	({ buildReceiptHTML, configureReceipt } = await import("../printInvoice"));
});

beforeEach(() => configureReceipt({ print_uom_after_quantity: 0 }));

/** Visible text of the receipt, whitespace collapsed. */
function text(html) {
	return html
		.replace(/<[^>]+>/g, " ")
		.replace(/&nbsp;/g, " ")
		.replace(/\s+/g, " ")
		.trim();
}

const sale = {
	name: "SINV-0001",
	company: "Test Company",
	currency: "HTG",
	posting_date: "2026-09-21",
	posting_time: "08:44:21",
	customer_name: "Walk-in",
	total: 8525.08,
	grand_total: 8525.08,
	rounding_adjustment: -0.08,
	rounded_total: 8525,
	paid_amount: 8525,
	payments: [
		{ mode_of_payment: "Cash", amount: 8525 },
		{ mode_of_payment: "Card", amount: 0 },
	],
	items: [
		{
			item_name: "Geometry set",
			qty: 5,
			uom: "Box (12)",
			price_list_rate: 850,
			rate: 750,
			amount: 3750,
		},
		{ item_name: "Pencil", qty: 36, uom: "Box (12)", price_list_rate: 100, rate: 96.53, amount: 3475.08 },
		{ item_name: "Eraser", qty: 2, uom: "Box (20)", price_list_rate: 200, rate: 200, amount: 400 },
		{ item_name: "Crayon", qty: 1, uom: "Pack (12)", price_list_rate: 900, rate: 900, amount: 900 },
	],
};

describe("buildReceiptHTML", () => {
	it("hides the UOM unless Print UOM after Quantity is on", () => {
		expect(text(buildReceiptHTML(sale))).toContain("5 × 850.00 4,250.00");

		configureReceipt({ print_uom_after_quantity: 1 });
		expect(text(buildReceiptHTML(sale))).toContain("5 Box (12) × 850.00 4,250.00");
	});

	it("shows the whole line discount, so lines add up to the subtotal", () => {
		const out = text(buildReceiptHTML(sale));
		// 5 × (850 - 750), not the per-unit 100
		expect(out).toContain("Discount -500.00");
		expect(out).toContain("Discount -124.92");
		expect(out).toContain("Subtotal 8,525.08");
	});

	it("prints the rounded total that was actually paid", () => {
		const out = text(buildReceiptHTML(sale));
		expect(out).toContain("Rounding -0.08");
		expect(out).toMatch(/Total \S* ?8,525\.00/);
		expect(out).not.toMatch(/Total \S* ?8,525\.08/);
	});

	it("skips zero payment rows", () => {
		const out = text(buildReceiptHTML(sale));
		expect(out).toContain("Cash 8,525.00");
		expect(out).not.toContain("Card");
	});

	it("prints a return as a credit note with positive amounts", () => {
		const ret = {
			...sale,
			name: "SINV-0002",
			is_return: 1,
			return_against: "SINV-0001",
			total: -2600,
			grand_total: -2600,
			rounding_adjustment: 0,
			rounded_total: -2600,
			paid_amount: -2600,
			payments: [{ mode_of_payment: "Cash", amount: -2600 }],
			items: [{ item_name: "Notebook", qty: -1, uom: "Case", price_list_rate: 2600, rate: 2600, amount: -2600 }],
		};
		const out = text(buildReceiptHTML(ret));
		expect(out).toContain("Credit Note");
		expect(out).toContain("Return of SINV-0001");
		expect(out).toContain("1 × 2,600.00 2,600.00");
		expect(out).toMatch(/Refund Total \S* ?2,600\.00/);
		expect(out).toContain("Cash 2,600.00");
		expect(out).not.toContain("-2,600");
	});

	it("shows the balance due on a credit sale", () => {
		const credit = { ...sale, rounding_adjustment: 0, rounded_total: 0, grand_total: 400, total: 400, paid_amount: 0, payments: [], outstanding_amount: 400, items: [sale.items[2]] };
		expect(text(buildReceiptHTML(credit))).toMatch(/Balance Due \S* ?400\.00/);
	});

	it("prints the sales team and coupon when present", () => {
		const out = text(
			buildReceiptHTML({
				...sale,
				sales_team: [{ sales_person: "SP-1", sales_person_name: "Ana" }, { sales_person: "Ben" }],
				coupon_code: "WELCOME10",
			}),
		);
		expect(out).toContain("Sales Person Ana, Ben");
		expect(out).toContain("Coupon WELCOME10");
		expect(text(buildReceiptHTML(sale))).not.toContain("Sales Person");
	});

	it("escapes names coming from the database", () => {
		const html = buildReceiptHTML({ ...sale, customer_name: "<b>x</b>", items: [{ ...sale.items[2], item_name: "A & B <i>" }] });
		expect(html).toContain("&lt;b&gt;x&lt;/b&gt;");
		expect(html).toContain("A &amp; B &lt;i&gt;");
	});
});
