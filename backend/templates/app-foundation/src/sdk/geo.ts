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
