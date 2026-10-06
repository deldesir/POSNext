import { describe, expect, it } from "vitest"
import { roundGrandTotal } from "../currency"

describe("roundGrandTotal", () => {
	it("keeps the exact total when the profile shows exact amounts", () => {
		expect(roundGrandTotal(4300.01, true)).toBe(4300.01)
		expect(roundGrandTotal(41.66, true)).toBe(41.66)
	})

	it("rounds to the whole currency unit when the profile rounds totals, like ERPNext's rounded_total", () => {
		expect(roundGrandTotal(4300.01, false)).toBe(4300)
		expect(roundGrandTotal(41.66, false)).toBe(42)
		expect(roundGrandTotal(1945.98, false)).toBe(1946)
	})

	it("defaults to exact amounts", () => {
		expect(roundGrandTotal(10.4)).toBe(10.4)
	})

	it("treats garbage as zero", () => {
		expect(roundGrandTotal(Number.NaN, false)).toBe(0)
	})
})
