/**
 * Payment method classification.
 *
 * The Mode of Payment type (Cash / Bank / Phone / General) is the source of
 * truth for what a method is, with the linked account's type ahead of it when
 * the payload carries one.  Names are only inspected when no type is known:
 * "Natcash" and "Mon Cash" are mobile money, not cash, and a name test would
 * call them cash.
 */

/**
 * Whether a payment method is cash: money that lands in the drawer, may be
 * overpaid, and gives change back.
 * @param {{account_type?: string, type?: string, mode_of_payment?: string, name?: string} | null | undefined} method
 * @returns {boolean}
 */
export function isCashPaymentMethod(method) {
	if (!method) return false

	const accountType = String(method.account_type || "").toLowerCase()
	if (accountType) return accountType === "cash"

	const type = String(method.type || "").toLowerCase()
	if (type) return type === "cash"

	// Last resort for payloads that carry no type at all (old offline caches).
	const name = String(method.mode_of_payment || method.name || "").toLowerCase()
	return name.includes("cash") || name.includes("نقد")
}
