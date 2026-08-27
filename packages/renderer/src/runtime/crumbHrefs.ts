/**
 * Make breadcrumb ancestor links point at real URLs.
 *
 * `services/page_nav.py` injects Breadcrumb nodes whose hrefs come straight
 * from the route-tree contract, and contract keys are parameterised by
 * design: `/conferences/[id]` names the detail ROUTE, not a URL. Shipping
 * that string to the browser produces a link to the literal path
 * `/conferences/[id]`, which the catch-all router reads as a record whose
 * id is "[id]" — a 404.
 *
 * Only the request knows the concrete id, so substitution happens at render
 * time. It happens on the SERVER (see `schema-page.tsx`) rather than in a
 * client component reading `location`, because those disagree: SSR would
 * emit the param form and hydration the concrete one, and React reports
 * that as a mismatch.
 *
 * When the id is missing, or the href needs more distinct values than the
 * one the request carries, the href is DROPPED and the label kept. That is
 * the rule `RouteBreadcrumb.tsx` already states for the shell trail: a
 * crumb that 404s is worse than a crumb that doesn't link.
 */

/** Next-style `[id]` and the Express-style `:id` the corpus also ships. */
function isParam(segment: string): boolean {
  return segment.startsWith("[") || segment.startsWith(":");
}

/** One href → the concrete URL, or `undefined` when it cannot be trusted.
 *
 * Every crumb href is an ANCESTOR of the current route, so its segments line
 * up positionally with the current pathname's leading segments — that is what
 * lets a param at index i take the concrete segment at index i, and it is the
 * same rule `RouteBreadcrumb.hrefFor` applies to the shell trail. When no
 * pathname reached us, fall back to the single `?id=` the routers thread for
 * the detail query; that covers one param and no more. */
function resolveHref(
  href: string,
  id: string | undefined,
  pathname: string | undefined,
): string | undefined {
  const parts = href.split("/");
  const params = parts.filter(isParam);
  if (params.length === 0) return href;          // nothing to substitute

  if (pathname) {
    const concrete = pathname.split("/");
    // A crumb longer than the current path is not an ancestor of it — the
    // contract and the URL disagree, so trust neither.
    if (parts.length > concrete.length) return undefined;
    const out = parts.map((seg, i) => (isParam(seg) ? concrete[i] : seg));
    // A param that lands on an empty or still-parameterised segment resolved
    // to nothing usable.
    if (out.some((seg, i) => isParam(parts[i]) && (!seg || isParam(seg)))) {
      return undefined;
    }
    return out.join("/");
  }

  if (!id) return undefined;                     // no value to substitute with
  // Two slots need two values; the request carries one. Filling both with
  // the same id would produce a confidently wrong URL.
  if (params.length > 1) return undefined;
  return parts.map((seg) => (isParam(seg) ? id : seg)).join("/");
}

type CrumbItem = { label?: string; href?: string };

export type CrumbContext = {
  /** The record id for the page's dynamic segment — the `?id=` the routers
   *  already thread through so the detail query can run. */
  id?: string;
  /** The concrete request path (`/conferences/<uuid>/sessions`). Preferred
   *  when present: it resolves multi-param hrefs, and it works on literal
   *  routes like `/conferences/<uuid>/sessions/new` where the router matched
   *  a static schema and therefore threaded no id at all. */
  pathname?: string;
};

/**
 * Return a copy of `page` whose Breadcrumb hrefs are concrete URLs.
 *
 * The input is never mutated: page schemas are cached across requests, and
 * one request's id must not leak into the next.
 *
 * Accepts a bare id string for callers that only have that.
 */
export function resolveCrumbHrefs<T>(
  page: T,
  ctx: CrumbContext | string | undefined,
): T {
  const { id, pathname } =
    typeof ctx === "string" ? { id: ctx, pathname: undefined } : (ctx ?? {});
  if (!page || typeof page !== "object") return page;

  const rewrite = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(rewrite);
    if (!node || typeof node !== "object") return node;

    const src = node as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(src)) out[key] = rewrite(value);

    if (src.type === "Breadcrumb") {
      const props = (out.props ?? {}) as Record<string, unknown>;
      const items = props.items;
      if (Array.isArray(items)) {
        out.props = {
          ...props,
          items: (items as CrumbItem[]).map((item) => {
            if (!item || typeof item !== "object" || typeof item.href !== "string") {
              return item;
            }
            const href = resolveHref(item.href, id, pathname);
            if (href === undefined) {
              const { href: _dropped, ...rest } = item;
              return rest;
            }
            return { ...item, href };
          }),
        };
      }
    }
    return out;
  };

  return rewrite(page) as T;
}
