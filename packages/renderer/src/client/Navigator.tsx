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
};

const defaultNavigator: Navigator = {
  push: (url) => { if (typeof window !== "undefined") window.location.assign(url); },
  replace: (url) => { if (typeof window !== "undefined") window.location.replace(url); },
  back: () => { if (typeof window !== "undefined") window.history.back(); },
  // A full reload is the only framework-agnostic "refresh"; hosts that can do
  // better (router.refresh) override this via the provider.
  refresh: () => { if (typeof window !== "undefined") window.location.reload(); },
};

export const NavigatorContext = React.createContext<Navigator | null>(null);

/** Returns the host-provided Navigator, or a window.location-backed default. */
export function useNavigator(): Navigator {
  return React.useContext(NavigatorContext) ?? defaultNavigator;
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
