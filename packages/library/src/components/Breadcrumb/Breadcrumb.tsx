import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { useNavigator } from "@tentoroforge/renderer";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity } from "../../theme/tokens-context";
import { humanizeLabel } from "../../utils/humanizeLabel";
import { currentBrowserPath, normalisePath, pathMatchesRoute } from "../../util/routeMatch";
import type { BreadcrumbItem } from "./Breadcrumb.schema";

type Props = {
  items: BreadcrumbItem[];
  separator?: string;
  /**
   * Append a final, non-linked crumb for the page the breadcrumb is ON.
   *
   * Without it a breadcrumb has to be hand-authored per page — the last crumb
   * is always "where I am", so the same trail had to be copied onto every page
   * with one word changed, and it silently goes stale when a route is renamed.
   * The label is derived from the route's last segment
   * (`/items/new` -> "New"), which is the same derivation the rest of the
   * library uses for a field key.
   *
   * Off by default: a trail that already ends in its own page must not grow a
   * duplicate, and adding a crumb to every existing Breadcrumb in every shipped
   * app would be a default read as a command.
   */
  currentPageAuto?: boolean;
  style?: StyleSlotT;
};

/**
 * The crumb for "the page you are on", derived from the browser path.
 *
 * Returns null on the server and during the first client paint (so the two
 * agree), when the path has no addressable last segment, and — importantly —
 * when the authored trail ALREADY ends at this page, so turning the option on
 * for a trail that was hand-finished does not duplicate its final crumb.
 */
function useCurrentPageCrumb(
  enabled: boolean,
  items: BreadcrumbItem[],
): BreadcrumbItem | null {
  const [path, setPath] = React.useState<string | undefined>(undefined);
  React.useEffect(() => {
    if (enabled) setPath(currentBrowserPath());
  }, [enabled]);
  if (!enabled || !path) return null;
  const here = normalisePath(path);
  const last = items[items.length - 1];
  if (last && !last.href) return null;                 // trail already ends in a page
  if (last?.href && pathMatchesRoute(last.href, here)) return null;
  const segment = here.split("/").filter(Boolean).pop();
  if (!segment) return null;
  const label = humanizeLabel(decodeURIComponent(segment));
  return label ? { label } : null;
}

// gap-x values in rem: compact=0.25, comfortable=0.25 (today's default), spacious=0.5
const BREADCRUMB_GAP: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "0.125rem",
  comfortable: "0.25rem",
  spacious:    "0.5rem",
};

export function Breadcrumb({ items, separator = "/", currentPageAuto = false, style }: Props) {
  const density = useDensity();
  const gap = BREADCRUMB_GAP[density];
  // A CRUMB IS A PLAIN ANCHOR, AND PLAIN ANCHORS IGNORED THE BASE PATH.
  //
  // Every other schema-driven navigation was routed through the Navigator seam
  // when the "/items resolves against the origin root" bug was fixed, but a
  // crumb has no click handler to hijack — it is `<a href>` and nothing else —
  // so it kept 404ing under the preview renderer's `/p/<project>` prefix.
  // `resolveHref` is the same translation `push` applies, exposed for the
  // attribute; a host that declares no prefix gets identity, so nothing that
  // works today changes.
  const nav = useNavigator();
  const href = (u: string) => (nav.resolveHref ? nav.resolveHref(u) : u);
  const autoCrumb = useCurrentPageCrumb(currentPageAuto, items);
  const trail = autoCrumb ? [...items, autoCrumb] : items;
  return (
    <nav aria-label="Breadcrumb" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <ol style={{ display: "flex", flexWrap: "wrap", listStyle: "none", margin: 0, padding: 0, gap, alignItems: "center" }}>
        {trail.map((item, index) => {
          const isLast = index === trail.length - 1;
          return (
            <li key={`${item.label}-${index}`} style={{ display: "flex", alignItems: "center", gap }}>
              {index > 0 && (
                <span aria-hidden="true" style={{ color: "#888", userSelect: "none" }}>
                  {separator}
                </span>
              )}
              {item.href && !isLast ? (
                <a href={href(item.href)} style={{ textDecoration: "underline" }}>
                  {item.label}
                </a>
              ) : (
                <span aria-current={isLast ? "page" : undefined}>
                  {item.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
