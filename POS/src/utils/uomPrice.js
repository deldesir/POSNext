/**
 * Local UOM price resolution.
 *
 * The catalogue payload carries every Item Price the item has (`uom_prices`,
 * keyed by UOM) plus the UOM conversion table (`item_uoms`). This resolves the
 * price of a UOM from that payload alone, so the UOM picker, the cart and the
 * edit dialog all quote the same number, online or offline.
 *
 * Rules, in order:
 * 1. an Item Price for the requested UOM is used as-is;
 * 2. otherwise the price of the smallest pack that has one is scaled by the
 *    conversion factors (the same pack the server picks for the tile);
 * 3. otherwise the tile price is scaled from the tile's own UOM.
 * Returns 0 when the item has no price at all.
 */

function positive(value) {
	const n = Number(value);
	return Number.isFinite(n) && n > 0 ? n : 0;
}

/**
 * Conversion factor of a UOM for an item (stock UOM = 1).
 * @param {Object} item
 * @param {string} uom
 * @returns {number} 0 when unknown
 */
export function conversionFactorFor(item, uom) {
	if (!item || !uom) return 0;
	if (uom === item.stock_uom) return 1;
	const row = (item.item_uoms || []).find((u) => u.uom === uom);
	return positive(row?.conversion_factor);
}

/**
 * The priced UOM closest to a single unit: `{ uom, rate, factor }` or null.
 * @param {Object} item
 */
export function smallestPricedPack(item) {
	const prices = item?.uom_prices || {};
	let best = null;
	for (const [uom, rate] of Object.entries(prices)) {
		const price = positive(rate);
		const factor = conversionFactorFor(item, uom);
		if (!price || !factor) continue;
		if (!best || factor < best.factor || (factor === best.factor && uom < best.uom)) {
			best = { uom, rate: price, factor };
		}
	}
	return best;
}

/**
 * Price of one `uom` of `item`, from the catalogue payload.
 * @param {Object} item - catalogue/cart item (uom_prices, item_uoms, stock_uom, rate, conversion_factor)
 * @param {string} uom - target UOM
 * @param {number} [conversionFactor] - target UOM's factor, when the caller already knows it
 * @returns {number}
 */
export function resolveLocalUomPrice(item, uom, conversionFactor) {
	if (!item || !uom) return 0;

	const listed = positive(item.uom_prices?.[uom]);
	if (listed) return listed;

	const targetFactor = positive(conversionFactor) || conversionFactorFor(item, uom);
	if (!targetFactor) return 0;

	const pack = smallestPricedPack(item);
	if (pack) return (pack.rate / pack.factor) * targetFactor;

	// No Item Price rows at all: fall back to the tile price in the tile's UOM
	const tileRate = positive(item.price_list_rate) || positive(item.rate);
	const tileFactor = positive(item.conversion_factor) || 1;
	return tileRate ? (tileRate / tileFactor) * targetFactor : 0;
}
