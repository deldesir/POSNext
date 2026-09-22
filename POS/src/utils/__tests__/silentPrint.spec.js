import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const call = vi.fn();
const printHTML = vi.fn();
vi.mock("@/utils/apiWrapper", () => ({ call: (...args) => call(...args) }));
vi.mock("@/utils/offline/offlineReceiptCache", () => ({ getOfflineReceiptPayload: vi.fn() }));
vi.mock("@/utils/offline/sync", () => ({ getOfflineInvoiceByOfflineId: vi.fn() }));
vi.mock("@/utils/offline/workerClient", () => ({ offlineWorker: {} }));
vi.mock("@/utils/offline", () => ({ isOffline: () => false, getCachedItem: vi.fn() }));
vi.mock("@/utils/qzTray", () => ({
	printHTML: (...args) => printHTML(...args),
	printRawCommands: vi.fn(),
}));

let silentPrintInvoice;

beforeAll(async () => {
	globalThis.__ = (msg) => msg;
	({ silentPrintInvoice } = await import("../printInvoice"));
});

beforeEach(() => {
	call.mockReset();
	printHTML.mockReset();
	call.mockImplementation(async (method, args) => {
		if (method === "pos_next.api.invoices.get_invoice") {
			return { name: args.invoice_name, pos_profile: "Till 1", language: "fr" };
		}
		if (method === "frappe.client.get") {
			return { name: args.name, print_format: "Shop Receipt", letter_head: null };
		}
		if (method === "frappe.www.printview.get_html_and_style") {
			return { html: "<div>receipt</div>", style: "" };
		}
		throw new Error(`unexpected call ${method}`);
	});
});

describe("silentPrintInvoice", () => {
	it("prints with the invoice's POS Profile format and language when given only a name", async () => {
		await silentPrintInvoice("SINV-0001");

		const render = call.mock.calls.find(([m]) => m === "frappe.www.printview.get_html_and_style");
		expect(render[1]).toMatchObject({ name: "SINV-0001", print_format: "Shop Receipt", _lang: "fr" });
		expect(printHTML).toHaveBeenCalledTimes(1);
	});

	it("does not fetch the invoice when the format is given", async () => {
		await silentPrintInvoice("SINV-0001", "Other Format");

		expect(call.mock.calls.some(([m]) => m === "pos_next.api.invoices.get_invoice")).toBe(false);
		const render = call.mock.calls.find(([m]) => m === "frappe.www.printview.get_html_and_style");
		expect(render[1].print_format).toBe("Other Format");
		expect(render[1]._lang).toBeUndefined();
	});

	it("uses the document handed in without refetching it", async () => {
		await silentPrintInvoice("SINV-0002", null, { name: "SINV-0002", pos_profile: "Till 1", language: "en" });

		expect(call.mock.calls.some(([m]) => m === "pos_next.api.invoices.get_invoice")).toBe(false);
		const render = call.mock.calls.find(([m]) => m === "frappe.www.printview.get_html_and_style");
		expect(render[1]).toMatchObject({ print_format: "Shop Receipt", _lang: "en" });
	});
});
