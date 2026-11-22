// The app SDK (native) — the road between two places, the part with no screen in it. PURE, and the same rules as
// the web's `useRoute`: ask the server (`/api/maps/route`) when the destination changes, when the traveller is more
// than 150 m off the line, or when the route is a minute old and they have moved; work out the distance left and the
// arrival time from where they are on the line.

import { alongPath, distanceKm, type GeoPoint } from "./geo";

export const OFF_ROUTE_KM = 0.15;
export const REFRESH_MS = 60_000;
export const MIN_GAP_MS = 8_000;

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

export type Asked = { at: number; from: GeoPoint; to: GeoPoint };

/** The server's answer as a RouteInfo, or null when it is not one. */
export function routeFromAnswer(j: unknown): RouteInfo | null {
  const a = j as { provider?: string; path?: GeoPoint[]; distanceMeters?: number; durationSeconds?: number; approximate?: boolean; notice?: string } | null;
  if (!a || !Array.isArray(a.path) || !a.provider) return null;
  return {
    provider: a.provider as RouteInfo["provider"], path: a.path, distanceKm: (a.distanceMeters ?? 0) / 1000,
    durationMin: (a.durationSeconds ?? 0) / 60, approximate: !!a.approximate, notice: a.notice,
  };
}

/** Is it time to ask for a route? */
export function shouldAsk(prev: Asked | null, route: RouteInfo | null, from: GeoPoint, to: GeoPoint, now: number, inflight: boolean): boolean {
  const destinationChanged = !prev || (distanceKm(prev.to, to) ?? 99) > 0.02;
  const drifted = !destinationChanged && route ? alongPath(route.path, from).offRouteKm > OFF_ROUTE_KM : false;
  const stale = !!prev && now - prev.at > REFRESH_MS && (distanceKm(prev.from, from) ?? 0) > 0.05;
  if (!(destinationChanged || drifted || stale)) return false;
  if (inflight || (prev && now - prev.at < MIN_GAP_MS && !destinationChanged)) return false;
  return true;
}

export type Progress = { remainingKm: number; etaMin: number; arriveAt: Date; offRoute: boolean };

/** How far is left and when they arrive, from where they are on the line. A straight line is the crow's flight:
 *  roads are about 30% longer, as the server counted. */
export function progress(route: RouteInfo, from: GeoPoint, now: number): Progress {
  const where = alongPath(route.path, from);
  const left = route.approximate ? where.remainingKm * 1.3 : where.remainingKm;
  const share = route.distanceKm > 0 ? Math.min(1, left / route.distanceKm) : 1;
  const remainingKm = route.approximate ? left : route.distanceKm * share;
  const etaMin = Math.max(0, route.durationMin * share);
  return { remainingKm, etaMin, arriveAt: new Date(now + etaMin * 60_000), offRoute: where.offRouteKm > OFF_ROUTE_KM };
}

/** "12 min", "1 h 5 min", "< 1 min". */
export function minutesText(min: number | null | undefined): string {
  if (min === null || min === undefined || !Number.isFinite(min)) return "";
  const m = Math.round(min);
  return m < 1 ? "< 1 min" : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** Where the line and the time came from, in words. */
export function routeSource(route: RouteInfo | null): string {
  if (!route) return "";
  if (route.provider === "google") return "Route by Google, live traffic";
  if (route.provider === "osrm") return "Route from a free routing service (no live traffic)";
  return "Approximate: a straight line, not a road";
}
