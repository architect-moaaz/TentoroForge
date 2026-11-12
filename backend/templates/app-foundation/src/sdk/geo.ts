// The app SDK — places and distances. Pure: safe on the server and the client.
//
// A `location` field holds `{ lat, lng }`, rounded to three decimals (about
// 100 m) when it is captured, so a record says which neighbourhood, never
// which door. A page shows a DISTANCE ("0.4 mi"), never the coordinates.

export type GeoPoint = { lat: number; lng: number };

/** Rounded to three decimals — about 100 m, the precision a location is kept at. */
export function roundPoint(p: GeoPoint): GeoPoint {
  return { lat: Math.round(p.lat * 1000) / 1000, lng: Math.round(p.lng * 1000) / 1000 };
}

export function isPoint(v: unknown): v is GeoPoint {
  const p = v as GeoPoint | null;
  return !!p && typeof p === "object" && Number.isFinite(p.lat) && Number.isFinite(p.lng);
}

/** Great-circle distance in kilometres, or null when either end is unknown. */
export function distanceKm(a: unknown, b: unknown): number | null {
  if (!isPoint(a) || !isPoint(b)) return null;
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat), dLng = rad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Miles where people count in miles (en-GB, en-US), kilometres elsewhere. */
function usesMiles(locale?: string): boolean {
  const l = (locale ?? (typeof navigator !== "undefined" ? navigator.language : "en-GB")).toLowerCase();
  return l === "en-gb" || l === "en-us" || l.startsWith("en-gb") || l.startsWith("en-us") || l === "en";
}

/** "0.4 mi", "650 m", "12 km" — or "" when the distance is unknown. */
export function formatDistance(km: number | null | undefined, locale?: string): string {
  if (km === null || km === undefined || !Number.isFinite(km)) return "";
  if (usesMiles(locale)) {
    const mi = km * 0.621371;
    return mi < 0.1 ? "< 0.1 mi" : mi < 10 ? `${mi.toFixed(1)} mi` : `${Math.round(mi)} mi`;
  }
  return km < 1 ? `${Math.max(100, Math.round(km * 10) * 100)} m` : km < 10 ? `${km.toFixed(1)} km` : `${Math.round(km)} km`;
}

/** `?near=51.507,-0.128` → a point, or null. */
export function parseNear(value: string | null | undefined): GeoPoint | null {
  const m = String(value ?? "").match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (!m) return null;
  const p = { lat: Number(m[1]), lng: Number(m[2]) };
  return Math.abs(p.lat) <= 90 && Math.abs(p.lng) <= 180 ? p : null;
}

/* ------------------------------ ROUTES ------------------------------ */

/**
 * A routing service's encoded path (Google's and OSRM's "polyline" format) as
 * places. `precision` is 5 for both of them.
 */
export function decodePolyline(encoded: string, precision = 5): GeoPoint[] {
  const factor = 10 ** precision;
  const out: GeoPoint[] = [];
  let index = 0, lat = 0, lng = 0;
  while (index < encoded.length) {
    for (const axis of [0, 1]) {
      let shift = 0, result = 0, byte: number;
      do {
        byte = encoded.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20 && index < encoded.length + 1);
      const delta = result & 1 ? ~(result >> 1) : result >> 1;
      if (axis === 0) lat += delta; else lng += delta;
    }
    out.push({ lat: lat / factor, lng: lng / factor });
  }
  return out;
}

/** At most `max` points of a path, keeping its ends and its shape. */
export function thinPath(path: GeoPoint[], max = 300): GeoPoint[] {
  if (path.length <= max) return path;
  const step = (path.length - 1) / (max - 1);
  const out: GeoPoint[] = [];
  for (let i = 0; i < max - 1; i++) out.push(path[Math.round(i * step)]);
  out.push(path[path.length - 1]);
  return out;
}

/** Length of a path in kilometres. */
export function pathKm(path: GeoPoint[]): number {
  let km = 0;
  for (let i = 1; i < path.length; i++) km += distanceKm(path[i - 1], path[i]) ?? 0;
  return km;
}

/**
 * Where `here` is against a route: how far is left to go, and how far off the
 * line the traveller is. The nearest point of the path stands for "here", so a
 * driver who drifts more than a short way from the line is off the route and the
 * page asks for a new one.
 */
export function alongPath(path: GeoPoint[], here: GeoPoint): { remainingKm: number; offRouteKm: number } {
  if (path.length === 0) return { remainingKm: 0, offRouteKm: 0 };
  let best = 0, bestKm = Infinity;
  for (let i = 0; i < path.length; i++) {
    const d = distanceKm(here, path[i]) ?? Infinity;
    if (d < bestKm) { bestKm = d; best = i; }
  }
  return { remainingKm: bestKm + pathKm(path.slice(best)), offRouteKm: bestKm };
}
