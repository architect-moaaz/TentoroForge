/**
 * Who is nearest — the on-duty people closest to a place, from the live fleet.
 *
 * "A ride is waiting at this pickup: tell the five drivers nearest to it." The fleet (hub.ts) holds each on-duty person's
 * latest position and the sign-in id of the phone that sent it (`who`): that id is who an alert goes to. Someone who has
 * said nothing for a while is not nearby, whatever their last position was, so a note older than `maxAgeMs` is ignored.
 *
 * Pure: positions in, a short list out.
 *
 * Forge runtime — do not remove.
 */

export interface Place { lat: number; lng: number }
export interface OnDuty extends Place { id: string; who: string; at: number }
export interface Nearby { userId: string; id: string; km: number }

const EARTH_KM = 6371.0088;

export function validPlace(p: unknown): p is Place {
  const q = p as Place | null | undefined;
  return !!q && typeof q.lat === "number" && typeof q.lng === "number" && Number.isFinite(q.lat) && Number.isFinite(q.lng)
    && q.lat >= -90 && q.lat <= 90 && q.lng >= -180 && q.lng <= 180;
}

/** A place from whatever a record holds: `{lat, lng}`, `{latitude, longitude}`, `[lng, lat]`, or those as JSON text. Null if it is none. */
export function placeOf(value: unknown): Place | null {
  let v: any = value;
  if (typeof v === "string") { try { v = JSON.parse(v); } catch { return null; } }
  if (Array.isArray(v) && v.length >= 2) v = { lat: Number(v[1]), lng: Number(v[0]) };
  if (!v || typeof v !== "object") return null;
  const lat = Number(v.lat ?? v.latitude);
  const lng = Number(v.lng ?? v.lon ?? v.longitude);
  const p = { lat, lng };
  return validPlace(p) ? p : null;
}

/** The great-circle distance between two places, in kilometres. */
export function distanceKm(a: Place, b: Place): number {
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/**
 * The `limit` people nearest `from`, closest first, each person once (one phone sending for two records is one person).
 * `maxKm` leaves out anyone farther than that; `maxAgeMs` anyone whose last note is older than that.
 */
export function nearest(
  members: OnDuty[], from: Place,
  opts: { limit?: number; maxKm?: number; maxAgeMs?: number; now?: number; exclude?: string[] } = {},
): Nearby[] {
  if (!validPlace(from)) return [];
  const now = opts.now ?? Date.now();
  const limit = Math.max(1, Math.min(100, Math.floor(opts.limit ?? 5)));
  const skip = new Set((opts.exclude ?? []).map(String));
  const best = new Map<string, Nearby>();
  for (const m of members) {
    if (!m.who || !validPlace(m) || skip.has(String(m.who))) continue;
    if (opts.maxAgeMs !== undefined && now - m.at > opts.maxAgeMs) continue;
    const km = distanceKm(from, m);
    if (opts.maxKm !== undefined && km > opts.maxKm) continue;
    const cur = best.get(m.who);
    if (!cur || km < cur.km) best.set(m.who, { userId: m.who, id: m.id, km });
  }
  return [...best.values()].sort((a, b) => a.km - b.km).slice(0, limit);
}

export interface NearestConfig { entity?: unknown; from?: unknown; limit?: unknown; maxKm?: unknown; maxAgeSeconds?: unknown }

/**
 * What a `send_notification` step's `nearest` setting means, given the place it resolved to and who is on duty: the user ids
 * to alert (closest first) and, when there are none, the reason in words. `fromValue` is whatever the step's `from` template
 * produced (a location object, its JSON text, …).
 */
export function whoIsNear(config: NearestConfig, fromValue: unknown, onDuty: OnDuty[], now: number = Date.now()): { userIds: string[]; notice?: string } {
  const kind = String(config.entity ?? "").trim();
  const from = placeOf(fromValue);
  if (!from) return { userIds: [], notice: "the place to look near is not a place" };
  if (!kind) return { userIds: [], notice: "`nearest` names no entity to look for" };
  const num = (v: unknown) => (Number(v) > 0 ? Number(v) : undefined);
  const found = nearest(onDuty, from, {
    limit: num(config.limit) ?? 5, maxKm: num(config.maxKm), maxAgeMs: (num(config.maxAgeSeconds) ?? 120) * 1000, now,
  });
  if (found.length === 0) return { userIds: [], notice: `no ${kind.toLowerCase()} on duty is near` };
  return { userIds: found.map((f) => f.userId) };
}
