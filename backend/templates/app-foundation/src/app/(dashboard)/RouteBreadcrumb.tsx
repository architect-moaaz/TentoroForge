"use client";

/**
 * Shell-rendered breadcrumb for routes the schema layer doesn't own.
 *
 * Most nested pages are page schemas, and services/page_nav.py injects a
 * Breadcrumb node into those directly. But ~300 nested routes across the
 * corpus ship as hand-written .tsx — template-injected pages like
 * /tasks/[id], or anything authored outside the schema pipeline. A JSON
 * pass cannot reach them, and regex-rewriting React source would be
 * fragile and undone by the next regeneration.
 *
 * So the shell renders the crumb for exactly those routes. Two rules keep
 * it honest:
 *
 *  - `owned_by_schema` routes render NOTHING here. Their page already
 *    carries a Breadcrumb, and two trails is worse than one.
 *  - Every crumb href comes from the route-tree contract's `parent`
 *    chain, which only ever names routes that exist. A crumb that 404s
 *    is worse than no crumb.
 *
 * The contract is src/contracts/route-tree.json, emitted by
 * services.page_nav.write_route_tree_contract during post-generation.
 */

import * as React from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

export type RouteNode = {
  parent: string | null;
  label: string;
  kind: string;
  dynamic: boolean;
  owned_by_schema: boolean;
};

/** A screen's tabs (`?tab=<key>`) and record panels (`?<param>=<id>`), by label. */
export type ScreenNode = {
  title: string;
  tabs?: Record<string, string>;
  panels?: Record<string, string>;
};

type Props = { routes: Record<string, RouteNode>; screens?: Record<string, ScreenNode> };

/** WHERE YOU ARE INSIDE A SCREEN: "Support desk › Open tickets › Ticket".
 *  A screen holds its records as tabs and panels on one route, so the trail
 *  is read from the search params the menu and links open them with. Only
 *  drawn when something inside the screen is open — a screen alone is its
 *  own title. */
function ScreenTrail({ screens }: { screens: Record<string, ScreenNode> }) {
  const pathname = usePathname() || "/";
  const search = useSearchParams();
  const screen = screens[pathname];
  if (!screen || !search) return null;
  const tabKey = search.get("tab");
  const tab = tabKey ? screen.tabs?.[tabKey] : undefined;
  const panel = Object.entries(screen.panels ?? {}).find(([param]) => search.get(param));
  if (!tab && !panel) return null;
  const crumbs: { label: string; href?: string }[] = [{ label: screen.title, href: pathname }];
  if (tab) crumbs.push({ label: tab, href: panel ? `${pathname}?tab=${encodeURIComponent(tabKey!)}` : undefined });
  if (panel) crumbs.push({ label: panel[1] });
  return (
    <nav aria-label="Breadcrumb" className="mb-4 text-sm text-muted-foreground">
      <ol className="flex flex-wrap items-center gap-1">
        {crumbs.map((c, i) => (
          <li key={i} className="flex items-center gap-1">
            {c.href ? <Link href={c.href} className="hover:underline">{c.label}</Link>
                    : <span className="text-foreground">{c.label}</span>}
            {i < crumbs.length - 1 && <span aria-hidden="true" className="select-none opacity-60">/</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** Concrete pathname → the contract key, which may be parameterised.
 *
 * At runtime the URL is `/products/8f3c-…`; the contract knows
 * `/products/[id]`. Match segment-by-segment, letting a param segment in
 * the contract absorb any single concrete segment. Exact matches win, so
 * a static `/products/new` never resolves to `/products/[id]`. */
function resolveRoute(
  pathname: string,
  routes: Record<string, RouteNode>,
): string | null {
  if (routes[pathname]) return pathname;
  const parts = pathname.split("/").filter(Boolean);
  for (const key of Object.keys(routes)) {
    const kp = key.split("/").filter(Boolean);
    if (kp.length !== parts.length) continue;
    const ok = kp.every(
      (seg, i) => seg === parts[i] || seg.startsWith("[") || seg.startsWith(":"),
    );
    if (ok) return key;
  }
  return null;
}

/** Walk `parent` up to the root. Only real routes are ever visited, and
 * the seen-set means a malformed contract can't spin forever. */
function ancestorsOf(
  route: string,
  routes: Record<string, RouteNode>,
): string[] {
  const out: string[] = [];
  const seen = new Set<string>([route]);
  let cur = routes[route]?.parent ?? null;
  while (cur && routes[cur] && !seen.has(cur)) {
    seen.add(cur);
    out.push(cur);
    cur = routes[cur].parent;
  }
  return out.reverse();
}

/** Concrete href for an ancestor: replace each param segment with the
 * real value from the current URL, so the link goes to THIS record's
 * parent rather than a literal "[id]". */
function hrefFor(ancestor: string, pathname: string): string {
  const ap = ancestor.split("/").filter(Boolean);
  const pp = pathname.split("/").filter(Boolean);
  return (
    "/" +
    ap
      .map((seg, i) =>
        (seg.startsWith("[") || seg.startsWith(":")) && pp[i] ? pp[i] : seg,
      )
      .join("/")
  );
}

export function RouteBreadcrumb({ routes, screens }: Props) {
  const pathname = usePathname() || "/";
  const key = resolveRoute(pathname, routes);
  if (!key) {
    // A screen's own trail. Suspense, because reading the search params on
    // the client opts the subtree into client rendering.
    return screens && screens[pathname]
      ? <React.Suspense fallback={null}><ScreenTrail screens={screens} /></React.Suspense>
      : null;
  }

  const node = routes[key];
  // The page schema already renders one — stay out of the way.
  if (node.owned_by_schema) return null;
  if (node.kind === "auth" || node.kind === "root") return null;

  const trail = ancestorsOf(key, routes);
  if (trail.length === 0) return null; // nothing real to go up to

  return (
    <nav aria-label="Breadcrumb" className="mb-4 text-sm text-muted-foreground">
      <ol className="flex flex-wrap items-center gap-1">
        {trail.map((a) => (
          <li key={a} className="flex items-center gap-1">
            <Link href={hrefFor(a, pathname)} className="hover:underline">
              {routes[a].label}
            </Link>
            <span aria-hidden="true" className="select-none opacity-60">
              /
            </span>
          </li>
        ))}
        <li aria-current="page" className="text-foreground">
          {node.label}
        </li>
      </ol>
    </nav>
  );
}
