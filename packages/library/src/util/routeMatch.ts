/**
 * "Is this authored route the page the browser is on?" — asked once, here.
 *
 * Two components need the answer and were each getting it wrong in a different
 * way:
 *
 *   • `Redirect` compared nothing at all, so a self-referential alias either
 *     bounced once to a 404 or pinned the page on "Redirecting…" forever.
 *   • `NavLink` compared `currentPath === dest` by exact string, and
 *     `currentPath` is only ever supplied by the generated app's own wrapper —
 *     so in the preview renderer no NavLink was ever marked current and
 *     `aria-current` never appeared on any page.
 *
 * The thing that makes exact equality wrong is the same in both cases: a page
 * authored as `/items` is served at `/items` in the shipped app and at
 * `/p/<project>/items` in the preview renderer. A route is therefore matched as
 * a **trailing whole-path suffix**, which is true under any base path and still
 * false for a different route that merely ends in the same letters
 * (`/line-items` does not match `/items`).
 */

/** Strip query, hash and trailing slashes. "/items/?x=1" and "/items" are one path. */
export function normalisePath(path: string): string {
  const bare = path.split("?")[0].split("#")[0];
  const trimmed = bare.replace(/\/+$/, "");
  return trimmed === "" ? "/" : trimmed;
}

/**
 * True when `route` names the page `currentPath` is showing.
 *
 * `route` must be app-absolute (start with "/"); anything else — an external
 * URL, a bare fragment, an empty string — is never a match. Returns false when
 * `currentPath` is unknown (server render): the server cannot answer this, and
 * guessing would make the first client paint disagree with it.
 */
export function pathMatchesRoute(
  route: string | undefined,
  currentPath: string | undefined,
): boolean {
  if (!route || !currentPath) return false;
  const target = normalisePath(route);
  const here = normalisePath(currentPath);
  if (target === here) return true;
  // "/" is a suffix of every path in spirit and of none in fact: navigating to
  // the root from "/p/x/items" is a real move, not a self-reference.
  if (target === "/") return false;
  // `target` carries its own leading "/", so endsWith is already a
  // whole-segment test — "/line-items" does not end with "/items".
  return target.startsWith("/") && here.endsWith(target);
}

/** The path the browser is on, or undefined off the browser. */
export function currentBrowserPath(): string | undefined {
  return typeof window !== "undefined" ? window.location.pathname : undefined;
}
