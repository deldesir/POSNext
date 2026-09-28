import { describe, expect, it } from "vitest"
import { isCashPaymentMethod } from "../paymentMethods"

describe("isCashPaymentMethod", () => {
	it("trusts the Mode of Payment type", () => {
		expect(isCashPaymentMethod({ mode_of_payment: "Cash", type: "Cash" })).toBe(
			true,
		)
		expect(
			isCashPaymentMethod({ mode_of_payment: "Wire Transfer", type: "Bank" }),
		).toBe(false)
	})

	it("does not call mobile money cash because of its name", () => {
		expect(
			isCashPaymentMethod({ mode_of_payment: "Natcash", type: "Phone" }),
		).toBe(false)
		expect(
			isCashPaymentMethod({ mode_of_payment: "Mon Cash", type: "Phone" }),
		).toBe(false)
		expect(
			isCashPaymentMethod({
				mode_of_payment: "Natcash",
				type: "Phone",
				account_type: "Bank",
			}),
		).toBe(false)
	})

	it("lets the linked account's type win over the mode type", () => {
		expect(
			isCashPaymentMethod({
				mode_of_payment: "Petty",
				type: "General",
				account_type: "Cash",
			}),
		).toBe(true)
		expect(
			isCashPaymentMethod({
				mode_of_payment: "Cash",
				type: "Cash",
				account_type: "Bank",
			}),
		).toBe(false)
		expect(
			isCashPaymentMethod({
				mode_of_payment: "Store Credit",
				type: "General",
				account_type: "Receivable",
			}),
		).toBe(false)
	})

	it("falls back to the name only when no type is known", () => {
		expect(isCashPaymentMethod({ mode_of_payment: "Cash" })).toBe(true)
		expect(isCashPaymentMethod({ mode_of_payment: "نقدي" })).toBe(true)
		expect(isCashPaymentMethod({ mode_of_payment: "Card" })).toBe(false)
	})

	it("is false for nothing", () => {
		expect(isCashPaymentMethod(null)).toBe(false)
		expect(isCashPaymentMethod(undefined)).toBe(false)
		expect(isCashPaymentMethod({})).toBe(false)
	})
})
