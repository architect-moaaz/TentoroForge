"use client";

/**
 * The road from one place to another, kept up to date while someone travels it.
 *
 *   const nav = useRoute(driver.position, destination);
 *   <MapView route={nav.route?.path} … />   {nav.summary}
 *
 * It asks /api/maps/route (Google's Routes API when the app has a server key, a
 * free routing service otherwise, a straight line at the very least) and then
 * keeps asking only when it must: when the destination changes, when the traveller
 * has left the line by more than 150 m (they took another road: a new route), or when
 * the route is a minute old and they have moved. The distance left and the arrival
 * time are worked out from where they are on the line, so they count down smoothly
 * between answers.
 */
import * as React from "react";
import { alongPath, distanceKm, type GeoPoint } from "./geo";

const BASE = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");
const OFF_ROUTE_KM = 0.15;
const REFRESH_MS = 60_000;
const MIN_GAP_MS = 8_000;

export type RouteInfo = {
  provider: "google" | "osrm" | "straight-line";
  path: GeoPoint[];
  distanceKm: number;
  durationMin: number;
  /** True when no routing service was reached: a straight line, not a road. */
  approximate: boolean;
  /** What to enable or fix, in words, when the best service was not used. */
  notice?: string;
};

export type Navigation = {
  route: RouteInfo | null;
  state: "idle" | "loading" | "ready" | "error";
  remainingKm: number | null;
  etaMin: number | null;
  /** The clock time of arrival, in the viewer's own time zone; null until a route is known. */
  arriveAt: Date | null;
  /** The traveller is off the line: a new route is on its way. */
  offRoute: boolean;
};

export function useRoute(
  from: GeoPoint | null | undefined,
  to: GeoPoint | null | undefined,
  opts: { mode?: "DRIVE" | "TWO_WHEELER" | "WALK" | "BICYCLE" } = {},
): Navigation {
  const [route, setRoute] = React.useState<RouteInfo | null>(null);
  const [state, setState] = React.useState<Navigation["state"]>("idle");
  const asked = React.useRef<{ at: number; from: GeoPoint; to: GeoPoint } | null>(null);
  const inflight = React.useRef(false);
  const mode = opts.mode ?? "DRIVE";

  const here = from ? `${from.lat.toFixed(5)},${from.lng.toFixed(5)}` : "";
  const there = to ? `${to.lat.toFixed(5)},${to.lng.toFixed(5)}` : "";

  React.useEffect(() => {
    if (!from || !to) { setRoute(null); setState("idle"); asked.current = null; return; }
    const prev = asked.current;
    const destinationChanged = !prev || (distanceKm(prev.to, to) ?? 99) > 0.02;
    if (destinationChanged) setRoute(null);
    const drifted = !destinationChanged && route ? alongPath(route.path, from).offRouteKm > OFF_ROUTE_KM : false;
    const stale = !!prev && Date.now() - prev.at > REFRESH_MS && (distanceKm(prev.from, from) ?? 0) > 0.05;
    if (!(destinationChanged || drifted || stale)) return;
    if (inflight.current || (prev && Date.now() - prev.at < MIN_GAP_MS && !destinationChanged)) return;

    inflight.current = true;
    asked.current = { at: Date.now(), from, to };
    if (!route || destinationChanged) setState("loading");
    fetch(`${BASE}/api/maps/route`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ origin: from, destination: to, mode }),
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(String(res.status));
        const j = await res.json();
        setRoute({
          provider: j.provider, path: j.path ?? [], distanceKm: (j.distanceMeters ?? 0) / 1000,
          durationMin: (j.durationSeconds ?? 0) / 60, approximate: !!j.approximate, notice: j.notice,
        });
        setState("ready");
      })
      .catch(() => setState((s) => (s === "ready" ? s : "error")))
      .finally(() => { inflight.current = false; });
    // `here` and `there` stand for the two places so the effect runs when either moves
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [here, there, mode]);

  return React.useMemo<Navigation>(() => {
    if (!route || !from) return { route, state, remainingKm: null, etaMin: null, arriveAt: null, offRoute: false };
    const where = alongPath(route.path, from);
    // the line may be a thinned copy of the road: scale the service's own distance and time by the share left
    // (a straight line is the crow's flight: roads are about 30% longer, as the server counted)
    const left = route.approximate ? where.remainingKm * 1.3 : where.remainingKm;
    const share = route.distanceKm > 0 ? Math.min(1, left / route.distanceKm) : 1;
    const remainingKm = route.approximate ? left : route.distanceKm * share;
    const etaMin = Math.max(0, route.durationMin * share);
    return { route, state, remainingKm, etaMin, arriveAt: new Date(Date.now() + etaMin * 60_000), offRoute: where.offRouteKm > OFF_ROUTE_KM };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route, state, here]);
}

/** "12 min", "1 h 5 min", "< 1 min". */
export function minutesText(min: number | null | undefined): string {
  if (min === null || min === undefined || !Number.isFinite(min)) return "";
  const m = Math.round(min);
  return m < 1 ? "< 1 min" : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** "Route: Google, live traffic" and the like: where the line and the time came from. */
export function routeSource(route: RouteInfo | null): string {
  if (!route) return "";
  if (route.provider === "google") return "Route by Google, live traffic";
  if (route.provider === "osrm") return "Route from a free routing service (no live traffic)";
  return "Approximate: a straight line, not a road";
}
