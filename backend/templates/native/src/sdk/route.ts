// The app SDK (native) — the road from one place to another, kept up to date while someone travels it.
//
//   const nav = useRoute(driver.position, destination);
//   <MapView route={nav.route?.path} … />   {minutesText(nav.etaMin)}
//
// It asks the app's `/api/maps/route` (Google's Routes API when the app has a server key, a free routing service
// otherwise, a straight line at the least), and asks again only when it must (`route-core`: the destination moved,
// the traveller left the line by more than 150 m, or the route is a minute old and they have moved).

import * as React from "react";
import { apiJson } from "./api";
import type { GeoPoint } from "./geo";
import { progress, routeFromAnswer, shouldAsk, type Asked, type RouteInfo } from "./route-core";

export { minutesText, routeSource, type RouteInfo } from "./route-core";

export type Navigation = {
  route: RouteInfo | null;
  state: "idle" | "loading" | "ready" | "error";
  remainingKm: number | null;
  etaMin: number | null;
  /** The clock time of arrival, in the phone's own time zone; null until a route is known. */
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
  const asked = React.useRef<Asked | null>(null);
  const inflight = React.useRef(false);
  const mode = opts.mode ?? "DRIVE";

  const here = from ? `${from.lat.toFixed(5)},${from.lng.toFixed(5)}` : "";
  const there = to ? `${to.lat.toFixed(5)},${to.lng.toFixed(5)}` : "";

  React.useEffect(() => {
    if (!from || !to) { setRoute(null); setState("idle"); asked.current = null; return; }
    const prev = asked.current;
    const moved = !prev || (Math.abs(prev.to.lat - to.lat) + Math.abs(prev.to.lng - to.lng)) > 0.0002;
    if (moved) setRoute(null);
    if (!shouldAsk(prev, moved ? null : route, from, to, Date.now(), inflight.current)) return;

    inflight.current = true;
    asked.current = { at: Date.now(), from, to };
    if (!route || moved) setState("loading");
    apiJson("/api/maps/route", { method: "POST", body: { origin: from, destination: to, mode } })
      .then((res) => {
        const info = res.ok ? routeFromAnswer(res.body) : null;
        if (info) { setRoute(info); setState("ready"); } else setState((s) => (s === "ready" ? s : "error"));
      })
      .finally(() => { inflight.current = false; });
    // `here` and `there` stand for the two places so the effect runs when either moves
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [here, there, mode]);

  return React.useMemo<Navigation>(() => {
    if (!route || !from) return { route, state, remainingKm: null, etaMin: null, arriveAt: null, offRoute: false };
    const p = progress(route, from, Date.now());
    return { route, state, remainingKm: p.remainingKm, etaMin: p.etaMin, arriveAt: p.arriveAt, offRoute: p.offRoute };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route, state, here]);
}
