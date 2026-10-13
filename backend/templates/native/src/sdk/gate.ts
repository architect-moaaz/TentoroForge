// The app SDK (native) — which screen a person belongs on, decided from the
// session alone. The root layout asks `gateDecision` after every change of
// session or route and goes where it says; keeping the rule here, free of
// react-native, is what lets it be tested instead of discovered on a phone.
//
//   signed out, route not public        -> /login
//   signed in, on /login                -> home (or the organisation picker)
//   signed in, an organisation to pick  -> /organisation
//   signed in, on /organisation, none to pick -> home
//
// A route is PUBLIC when `config.generated.ts`'s `PUBLIC_ROUTES` lists it or a
// parent of it: a storefront a visitor browses before signing in. "/" listed
// alone makes only the home screen public, not every route under it.

import type { SessionStatus } from "./auth";

const LOGIN = "/login";
const ORGANISATION = "/organisation";

function isPublicRoute(pathname: string, publicRoutes: readonly string[]): boolean {
  const path = pathname.replace(/\/+$/, "") || "/";
  return publicRoutes.some((p) => {
    const route = p.replace(/\/+$/, "") || "/";
    return route === "/" ? path === "/" : path === route || path.startsWith(`${route}/`);
  });
}

export interface GateInput {
  status: SessionStatus;
  needsOrganisation: boolean;
  pathname: string;
  publicRoutes: readonly string[];
  home: string;
}

/** Where to go, or null to stay. Nothing is decided until the session is known. */
export function gateDecision({ status, needsOrganisation, pathname, publicRoutes, home }: GateInput): string | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (status === "loading" || status === "offline") return null;
  if (status === "signedOut") {
    return path === LOGIN || isPublicRoute(path, publicRoutes) ? null : LOGIN;
  }
  if (needsOrganisation) return path === ORGANISATION ? null : ORGANISATION;
  if (path === LOGIN || path === ORGANISATION) return home;
  return null;
}
