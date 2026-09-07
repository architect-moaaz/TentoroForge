"use client";
import * as React from "react";

/**
 * NavigatorContext — the single navigation seam every schema-driven component
 * routes through (Button `navigate`, Table `rowHref`, Link, and the engine's
 * post-submit redirect).
 *
 * Why a context: by default these components hard-navigate via
 * `window.location.assign`, which triggers a full page load and BYPASSES
 * Next.js client routing — so parallel/intercepting routes (the routed-modal
 * pattern) never fire. A host app that wants soft navigation (SPA transitions,
 * `@modal` overlays that keep the parent page mounted) supplies a Navigator
 * backed by `useRouter()` from `next/navigation`; every component then pushes
 * through Next's router instead of the browser location.
 *
 * Lives in @tentoroforge/renderer — same home as DialogStateContext — so the
 * library (which imports renderer) can consume it without a library→engine
 * dependency edge.
 *
 * When no provider is present (editor canvas, unit tests, apps that opt out)
 * `useNavigator()` returns a `window.location`-backed default, so behaviour is
 * exactly what it was before this seam existed. Nothing regresses.
 */
export type Navigator = {
  /** Navigate to a URL. Soft (router.push) when a host provides one; otherwise a full load. */
  push: (url: string) => void;
  /** Replace the current history entry. */
  replace: (url: string) => void;
  /** Go back one history entry (closes a routed modal). */
  back: () => void;
  /** Re-fetch server data for the current route without a full reload. No-op by default. */
  refresh: () => void;
  /**
   * Translate an app-relative route into the URL THIS HOST SERVES IT AT, for
   * rendering into an `href` attribute.
   *
   * WHY THE SEAM NEEDS THIS AS WELL AS `push`
   * -----------------------------------------
   * `push` fixed the click. It did not fix the *attribute*, and an anchor is
   * more than its click handler: middle-click, ⌘-click, "copy link address",
   * a crawler, and the whole pre-hydration window all read the raw `href`.
   * Under the preview renderer's `/p/<project>` prefix that href still points
   * at the origin root, so every one of those paths 404s while a plain
   * left-click works — a bug that only shows up for the user who opens things
   * in a new tab.
   *
   * The components that could hijack the click (Link, NavLink) were papering
   * over it; the one that renders anchors and CANNOT hijack — Breadcrumb, whose
   * crumbs are plain `<a href>` — was simply broken. Both need the same
   * translation, so it belongs on the seam that already owns the base path
   * rather than in each component.
   *
   * Optional: a host that supplies its own Navigator and omits it keeps
   * identity behaviour, which is exactly what it has today.
   */
  resolveHref?: (url: string) => string;
};

const defaultNavigator: Navigator = {
  push: (url) => { if (typeof window !== "undefined") window.location.assign(url); },
  replace: (url) => { if (typeof window !== "undefined") window.location.replace(url); },
  back: () => { if (typeof window !== "undefined") window.history.back(); },
  // A full reload is the only framework-agnostic "refresh"; hosts that can do
  // better (router.refresh) override this via the provider.
  refresh: () => { if (typeof window !== "undefined") window.location.reload(); },
};

/**
 * Rewrite an app-relative route so it resolves under `basePath`.
 *
 * WHY THIS IS THE SEAM'S PROBLEM AND NOT EACH COMPONENT'S
 * ------------------------------------------------------
 * Schema-authored routes are written the way the shipped app serves them
 * ("/items"). A host that serves the same pages under a prefix — the preview
 * renderer at `/p/<project>/…`, an app mounted under a sub-path — therefore
 * has to translate every one of them. Nothing did, so `defaultNavigator` ran
 * `window.location.assign("/items")` against the ORIGIN root: clicking a Link
 * on `/p/gh0mlpbp/nav-lab-6` landed on `localhost:6503/items`, a 404. Measured,
 * not inferred. The same single line broke `Redirect`, `Link`, `NavLink`,
 * `Button navigate`, `Table rowHref` and the post-submit redirect, because all
 * six of them route through this one seam — which is also why the fix belongs
 * here rather than six times over.
 *
 * Left alone: absolute URLs, protocol-relative URLs, other schemes
 * (mailto:/tel:), bare fragments and queries, relative paths, and anything
 * already under `basePath`. Only an app-absolute route is prefixed.
 */
export function resolveWithBasePath(basePath: string, url: string): string {
  if (!basePath || basePath === "/" || typeof url !== "string" || url === "") return url;
  const base = basePath.endsWith("/") ? basePath.slice(0, -1) : basePath;
  if (!url.startsWith("/") || url.startsWith("//")) return url;
  if (url === base || url.startsWith(`${base}/`)) return url;
  return url === "/" ? base || "/" : `${base}${url}`;
}

/**
 * A Navigator that serves app-relative routes from under `basePath`.
 *
 * `inner` defaults to the window.location-backed navigator; hosts with a real
 * router pass their own so soft navigation is preserved and only the path
 * translation is added.
 */
export function createBasePathNavigator(
  basePath: string,
  inner: Navigator = defaultNavigator,
): Navigator {
  return {
    push: (url) => inner.push(resolveWithBasePath(basePath, url)),
    replace: (url) => inner.replace(resolveWithBasePath(basePath, url)),
    back: () => inner.back(),
    refresh: () => inner.refresh(),
    // Same translation, same rule set — so an href and the push it fronts can
    // never disagree about where a route lives.
    resolveHref: (url) =>
      resolveWithBasePath(basePath, inner.resolveHref ? inner.resolveHref(url) : url),
  };
}

export const NavigatorContext = React.createContext<Navigator | null>(null);

/** Returns the host-provided Navigator, or a window.location-backed default. */
export function useNavigator(): Navigator {
  return React.useContext(NavigatorContext) ?? defaultNavigator;
}

/**
 * The URL to put in an `href` for an app-relative route, under whatever prefix
 * the current host serves the app at. Identity when the host declares none,
 * which is every case that works today.
 *
 * Use this for the ATTRIBUTE; keep using `useNavigator().push` for the click.
 */
export function useHref(url: string): string {
  const nav = useNavigator();
  if (typeof url !== "string" || url === "") return url;
  return nav.resolveHref ? nav.resolveHref(url) : url;
}

export function NavigatorProvider({
  value,
  children,
}: {
  value: Navigator;
  children: React.ReactNode;
}) {
  return (
    <NavigatorContext.Provider value={value}>{children}</NavigatorContext.Provider>
  );
}
