// The POS is mounted under the site's sub-path (e.g. `/erp/pos`, see the IIAB nginx mount): the
// prefix is read once from the URL and every root path the app spells goes behind it. On the
// page it is what comes before `/pos`; inside a worker, what comes before `/assets/` of the
// worker script. Assets are served at the root as well, so they are left alone.
const path = (globalThis.location && globalThis.location.pathname) || "";
const cut = path.includes("/assets/") ? path.indexOf("/assets/") : path.indexOf("/pos");
export const SUBPATH = cut > 0 ? path.slice(0, cut).replace(/\/+$/, "") : "";

/** A root-relative site path spelled under the sub-path; anything else is returned as is. */
export function withSubpath(url) {
	if (!SUBPATH || typeof url !== "string" || !url.startsWith("/") || url.startsWith("//")) return url;
	if (url === SUBPATH || url.startsWith(SUBPATH + "/")) return url;
	return SUBPATH + url;
}

/** A frappe-ui request option set with its url spelled under the sub-path. */
export function withSubpathRequest(options) {
	if (!options || typeof options !== "object" || typeof options.url !== "string") return options;
	const url = options.url;
	const spelled = url.startsWith("/") || url.startsWith("http") ? withSubpath(url) : withSubpath("/api/method/" + url);
	return spelled === url ? options : { ...options, url: spelled };
}
