/**
 * /api/maps/route — the road between two places, how far it is and how long it takes.
 *
 *   POST { origin: {lat,lng}, destination: {lat,lng}, mode?: "DRIVE" | "TWO_WHEELER" | "WALK" | "BICYCLE" }
 *     -> { provider, path: [{lat,lng}...], distanceMeters, durationSeconds, approximate, notice? }
 *   GET -> { map: "google" | "openfreemap", routing: "google" | "osrm" | "straight-line" | "off" }
 *
 * WHO ANSWERS, in order:
 *   1. Google Routes API, when GOOGLE_MAPS_SERVER_KEY is set (live traffic). The key stays on the
 *      server: it is never sent to a browser, never written into a response or a log. It needs the
 *      Routes API enabled for its project; a key with an application restriction must allow this
 *      server (an IP restriction), not a web referrer.
 *   2. A free OSRM server (OSRM_URL, default the public demo server — fine to try it, not for
 *      production, and it receives the two places). Off with MAP_ROUTING=off.
 *   3. A straight line, marked `approximate`, so a screen can say so.
 * When Google is configured but refuses, the answer still comes from the next in line and carries a
 * `notice` that says what to enable. Nothing else of what a service replied is passed on.
 *
 * Only a signed-in person may ask; a person may ask about once a second; the same question within
 * twenty seconds is answered from memory, so a driver's moving dot does not turn into a paid request
 * per movement. Forge runtime — do not remove.
 */
import { NextRequest } from "next/server";
import { whoIs } from "@/lib/tracking/access";
import { validPosition } from "@/lib/tracking/hub";
import { decodePolyline, distanceKm, thinPath, type GeoPoint } from "@/sdk/geo";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MODES = ["DRIVE", "TWO_WHEELER", "WALK", "BICYCLE"] as const;
type Mode = (typeof MODES)[number];
type Answer = { provider: "google" | "osrm" | "straight-line"; path: GeoPoint[]; distanceMeters: number; durationSeconds: number; approximate: boolean; notice?: string };

const g = globalThis as unknown as { __forgeRouteCache?: Map<string, { at: number; answer: Answer }>; __forgeRouteLast?: Map<string, number> };
const cache = (g.__forgeRouteCache ??= new Map());
const last = (g.__forgeRouteLast ??= new Map());
const CACHE_MS = 20_000;
const MIN_GAP_MS = 900;
const no = (status: number, error: string) => Response.json({ ok: false, error }, { status });
const round = (p: GeoPoint) => `${p.lat.toFixed(4)},${p.lng.toFixed(4)}`;

function status() {
  const googleMap = !!process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY && (process.env.NEXT_PUBLIC_MAP_PROVIDER ?? "google") !== "openfreemap";
  const routing = process.env.GOOGLE_MAPS_SERVER_KEY ? "google" : process.env.MAP_ROUTING === "off" ? "off" : "osrm";
  return { map: googleMap ? "google" : "openfreemap", routing };
}

export async function GET(): Promise<Response> {
  if (!(await whoIs())) return no(401, "Sign in first.");
  return Response.json(status());
}

class Refused extends Error {
  constructor(readonly why: "not-enabled" | "failed") { super(why); }
}

async function viaGoogle(o: GeoPoint, d: GeoPoint, mode: Mode): Promise<Answer> {
  const res = await fetch("https://routes.googleapis.com/directions/v2:computeRoutes", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Goog-Api-Key": process.env.GOOGLE_MAPS_SERVER_KEY as string,
      "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline",
    },
    body: JSON.stringify({
      origin: { location: { latLng: { latitude: o.lat, longitude: o.lng } } },
      destination: { location: { latLng: { latitude: d.lat, longitude: d.lng } } },
      travelMode: mode,
      ...(mode === "DRIVE" || mode === "TWO_WHEELER" ? { routingPreference: "TRAFFIC_AWARE" } : {}),
    }),
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) {
    console.error("[maps/route] Google Routes answered", res.status); // the status only, never the key or the body
    throw new Refused(res.status === 400 || res.status === 403 ? "not-enabled" : "failed");
  }
  const body = (await res.json()) as { routes?: { duration?: string; distanceMeters?: number; polyline?: { encodedPolyline?: string } }[] };
  const r = body.routes?.[0];
  const encoded = r?.polyline?.encodedPolyline;
  if (!r || !encoded) throw new Refused("failed");
  return {
    provider: "google", approximate: false,
    path: thinPath(decodePolyline(encoded)),
    distanceMeters: Math.round(r.distanceMeters ?? 0),
    durationSeconds: Math.round(parseFloat(String(r.duration ?? "0").replace("s", "")) || 0),
  };
}

async function viaOsrm(o: GeoPoint, d: GeoPoint, mode: Mode): Promise<Answer> {
  const base = (process.env.OSRM_URL || "https://router.project-osrm.org").replace(/\/+$/, "");
  const profile = mode === "WALK" ? "foot" : mode === "BICYCLE" ? "bike" : "driving";
  const url = `${base}/route/v1/${profile}/${o.lng},${o.lat};${d.lng},${d.lat}?overview=full&geometries=polyline`;
  const res = await fetch(url, { signal: AbortSignal.timeout(8000), headers: { "user-agent": "forge-app-route/1" } });
  if (!res.ok) throw new Refused("failed");
  const body = (await res.json()) as { routes?: { geometry?: string; distance?: number; duration?: number }[] };
  const r = body.routes?.[0];
  if (!r?.geometry) throw new Refused("failed");
  return { provider: "osrm", approximate: false, path: thinPath(decodePolyline(r.geometry)), distanceMeters: Math.round(r.distance ?? 0), durationSeconds: Math.round(r.duration ?? 0) };
}

function straight(o: GeoPoint, d: GeoPoint, mode: Mode): Answer {
  const km = (distanceKm(o, d) ?? 0) * 1.3; // roads are longer than the crow flies
  const kmh = mode === "WALK" ? 5 : mode === "BICYCLE" ? 15 : 25;
  return { provider: "straight-line", approximate: true, path: [o, d], distanceMeters: Math.round(km * 1000), durationSeconds: Math.round((km / kmh) * 3600) };
}

export async function POST(req: NextRequest): Promise<Response> {
  const me = await whoIs();
  if (!me) return no(401, "Sign in first.");
  const body = (await req.json().catch(() => ({}))) as { origin?: GeoPoint; destination?: GeoPoint; mode?: string };
  const o = body.origin, d = body.destination;
  if (!o || !d || !validPosition(o.lat, o.lng) || !validPosition(d.lat, d.lng)) return no(400, "origin and destination must be places on Earth.");
  const mode = (MODES as readonly string[]).includes(String(body.mode)) ? (body.mode as Mode) : "DRIVE";
  if ((distanceKm(o, d) ?? 0) > 2500) return no(400, "Those places are too far apart to route.");

  const key = `${mode}:${round(o)}>${round(d)}`;
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < CACHE_MS) return Response.json({ ok: true, ...hit.answer, cached: true });

  const now = Date.now();
  if (now - (last.get(me.userId) ?? 0) < MIN_GAP_MS) return no(429, "Too many route requests. Try again in a second.");
  last.set(me.userId, now);

  let answer: Answer | null = null;
  let notice: string | undefined;
  if (process.env.GOOGLE_MAPS_SERVER_KEY) {
    try {
      answer = await viaGoogle(o, d, mode);
    } catch (e) {
      notice = e instanceof Refused && e.why === "not-enabled"
        ? "Google refused the route request. Enable the Routes API for this key's project and check the key's restrictions."
        : "Google could not give a route just now.";
    }
  }
  if (!answer && process.env.MAP_ROUTING !== "off") {
    try { answer = await viaOsrm(o, d, mode); } catch { /* fall through to the straight line */ }
  }
  if (!answer) answer = straight(o, d, mode);
  if (notice) answer.notice = notice;
  else if (answer.provider !== "google") answer.notice = answer.provider === "osrm"
    ? "Route from a free demo routing service. Set GOOGLE_MAPS_SERVER_KEY (Routes API enabled) for traffic-aware routes and ETA."
    : "Approximate: no routing service reached. Set GOOGLE_MAPS_SERVER_KEY (Routes API enabled) for real routes and ETA.";
  if (cache.size > 500) cache.clear();
  cache.set(key, { at: now, answer });
  return Response.json({ ok: true, ...answer });
}
