/**
 * "Allow Negative Stock" on a till is an opt-in to the company's permission
 * (Stock Settings), never the permission itself.
 * @vitest-environment jsdom
 */
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("frappe-ui", () => ({
	call: vi.fn(),
	createResource: () => ({ submit: vi.fn(), reload: vi.fn(), fetch: vi.fn() }),
}));
vi.mock("@/stores/bootstrap", () => ({
	useBootstrapStore: () => ({ getPreloadedPOSSettings: () => null }),
}));

const { usePOSSettingsStore } = await import("../posSettings");

const till = (overrides) => {
	const store = usePOSSettingsStore();
	Object.assign(store.settings, {
		enabled: 1,
		allow_negative_stock: 0,
		_global_allow_negative_stock: 0,
		...overrides,
	});
	return store;
};

describe("posSettings negative stock policy", () => {
	beforeEach(() => setActivePinia(createPinia()));

	it("keeps enforcing stock when the company says no, even if the till opted in", () => {
		const store = till({ allow_negative_stock: 1, _global_allow_negative_stock: 0 });
		expect(store.isNegativeStockAllowed()).toBe(false);
		expect(store.shouldEnforceStockValidation()).toBe(true);
		expect(store.allowNegativeStock).toBe(false);
	});

	it("lets an opted-in till sell past zero when the company allows it", () => {
		const store = till({ allow_negative_stock: 1, _global_allow_negative_stock: 1 });
		expect(store.isNegativeStockAllowed()).toBe(true);
		expect(store.shouldEnforceStockValidation()).toBe(false);
	});

	it("keeps enforcing on a till that did not opt in, whatever the company allows", () => {
		const store = till({ allow_negative_stock: 0, _global_allow_negative_stock: 1 });
		expect(store.isNegativeStockAllowed()).toBe(false);
		expect(store.shouldEnforceStockValidation()).toBe(true);
	});

	it("leaves the decision to the server when the settings row is disabled", () => {
		const store = till({ enabled: 0, allow_negative_stock: 1, _global_allow_negative_stock: 1 });
		expect(store.isNegativeStockAllowed()).toBe(false);
		expect(store.shouldEnforceStockValidation()).toBe(false);
	});

	it("starts from a closed company permission until the server says otherwise", () => {
		const store = usePOSSettingsStore();
		expect(store.settings._global_allow_negative_stock).toBe(0);
		store.resetSettings();
		expect(store.settings._global_allow_negative_stock).toBe(0);
	});
});
