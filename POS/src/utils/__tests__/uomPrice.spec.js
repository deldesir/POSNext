import { describe, expect, it } from "vitest";
import { conversionFactorFor, resolveLocalUomPrice, smallestPricedPack } from "../uomPrice";

// A retail item priced only by the pack, the way the catalogue endpoint ships it:
// the tile quotes the smallest priced pack in its own UOM.
const packOnly = {
	item_code: "PACK-ONLY",
	stock_uom: "Unité",
	rate: 300,
	price_list_rate: 300,
	uom: "3 Unité",
	conversion_factor: 3,
	item_uoms: [
		{ uom: "3 Unité", conversion_factor: 3 },
		{ uom: "Douzaine", conversion_factor: 12 },
		{ uom: "Boite (24)", conversion_factor: 24 },
	],
	uom_prices: { "3 Unité": 300, Douzaine: 1150, "Boite (24)": 2200 },
};

const unitPriced = {
	item_code: "UNIT-PRICED",
	stock_uom: "Unité",
	rate: 250,
	price_list_rate: 250,
	uom: "Unité",
	conversion_factor: 1,
	item_uoms: [
		{ uom: "3 Unité", conversion_factor: 3 },
		{ uom: "Douzaine", conversion_factor: 12 },
	],
	uom_prices: { Unité: 250, Douzaine: 2500 },
};

describe("conversionFactorFor", () => {
	it("is 1 for the stock UOM and the table value for others", () => {
		expect(conversionFactorFor(unitPriced, "Unité")).toBe(1);
		expect(conversionFactorFor(unitPriced, "Douzaine")).toBe(12);
	});

	it("is 0 for a UOM the item does not know", () => {
		expect(conversionFactorFor(unitPriced, "Caisse")).toBe(0);
		expect(conversionFactorFor(null, "Unité")).toBe(0);
	});
});

describe("smallestPricedPack", () => {
	it("picks the priced UOM closest to a single unit", () => {
		expect(smallestPricedPack(packOnly)).toEqual({
			uom: "3 Unité",
			rate: 300,
			factor: 3,
		});
	});

	it("ignores prices whose UOM has no conversion and returns null when nothing is priced", () => {
		expect(smallestPricedPack({ ...packOnly, uom_prices: { Caisse: 999 } })).toBeNull();
		expect(smallestPricedPack({ ...packOnly, uom_prices: {} })).toBeNull();
	});
});

describe("resolveLocalUomPrice", () => {
	it("returns the Item Price of the requested UOM as-is", () => {
		expect(resolveLocalUomPrice(packOnly, "Douzaine", 12)).toBe(1150);
		expect(resolveLocalUomPrice(unitPriced, "Douzaine")).toBe(2500);
	});

	it("derives an unpriced UOM from the smallest priced pack, not from the tile rate", () => {
		// Unité has no Item Price: 300 per 3 Unité -> 100 per unit
		expect(resolveLocalUomPrice(packOnly, "Unité", 1)).toBe(100);
		// 3 Unité has no Item Price on the unit-priced item: 250 per unit -> 750
		expect(resolveLocalUomPrice(unitPriced, "3 Unité")).toBe(750);
	});

	it("does not scale the tile rate by the target factor when the tile is a pack price", () => {
		// The old code did rate * conversionFactor = 300 * 12 = 3600 here
		const noDozenPrice = { ...packOnly, uom_prices: { "3 Unité": 300 } };
		expect(resolveLocalUomPrice(noDozenPrice, "Douzaine", 12)).toBe(1200);
	});

	it("falls back to the tile rate scaled from the tile UOM when no Item Price is known", () => {
		const tileOnly = { ...packOnly, uom_prices: {} };
		expect(resolveLocalUomPrice(tileOnly, "Unité", 1)).toBe(100);
		expect(resolveLocalUomPrice(tileOnly, "Douzaine", 12)).toBe(1200);
	});

	it("returns 0 for an unknown UOM or an unpriced item", () => {
		expect(resolveLocalUomPrice(packOnly, "Caisse")).toBe(0);
		expect(
			resolveLocalUomPrice(
				{ ...packOnly, rate: 0, price_list_rate: 0, uom_prices: {} },
				"Unité",
				1,
			),
		).toBe(0);
		expect(resolveLocalUomPrice(null, "Unité")).toBe(0);
	});
});
