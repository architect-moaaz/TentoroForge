/**
 * POST /api/tracking/update — the person on the move says "I am here".
 *
 *   { entity: "Order", trip: "<order id>", lat, lng, at?, heading?, speed?, accuracy?, stage? }
 *   { entity: "Order", trip: "<order id>", done: true }     ends the trip
 *   { fleet: true, entity: "Driver", trip: "<own driver id>", lat, lng }   on duty, waiting for work
 *
 * The trip is a record in the app's own data. Who may send is the person that
 * record names as being on the move (driverId, courierId, …) — nobody else, and
 * not a customer who can merely open it. Refused:
 *   401 not signed in · 404 no such trip, or not one you may see ·
 *   403 you are not the person on the move · 409 the job is over ·
 *   400 a place that does not exist.
 * A late note is answered ok but ignored. Notes are rate-limited per trip.
 * Forge runtime — do not remove.
 */
import { NextRequest } from "next/server";
import { jobFor, whoIs } from "@/lib/tracking/access";
import { finished, fleetKey, fleetKind, fleetLabel, isSelf, mayShare, tripKey, whyNotOnDuty } from "@/lib/tracking/rules";
import { finish, fleetLeave, fleetPublish, publish, validPosition } from "@/lib/tracking/hub";
import { checkPosition } from "@/lib/geofence";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MIN_GAP_MS = 500;
const g = globalThis as unknown as { __forgeTrackingLast?: Map<string, number> };
const last: Map<string, number> = (g.__forgeTrackingLast ??= new Map());

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const no = (status: number, error: string) => Response.json({ ok: false, error }, { status });

export async function POST(req: NextRequest): Promise<Response> {
  const body = (await req.json().catch(() => ({}))) as Record<string, unknown>;
  const entity = typeof body.entity === "string" ? body.entity.trim() : "";
  const trip = typeof body.trip === "string" ? body.trip.trim() : "";

  // Who is asking comes first: a signed-out caller learns nothing else.
  if (!(await whoIs())) return no(401, "Sign in to share a trip.");
  if (!entity || !trip) return no(400, "entity and trip are required");
  const found = await jobFor(entity, trip);
  if (!found.ok) return no(found.status, found.error);
  if (body.fleet === true) {
    // FLEET MODE: `trip` is the person's OWN record (a Driver), not a job. They
    // may be on the map only if it is theirs and they are cleared and on duty.
    if (!isSelf(found.job, found.userId)) return no(403, "That is not your record.");
    const fkey = fleetKey(entity);
    if (body.done === true) {
      fleetLeave(fkey, trip, found.userId);
      return Response.json({ ok: true });
    }
    const why = whyNotOnDuty(found.job);
    if (why) {
      fleetLeave(fkey, trip, found.userId); // gone from the map the moment they are not on duty
      return no(409, why);
    }
    if (!validPosition(body.lat, body.lng)) return no(400, "That is not a place on Earth.");
    const t = Date.now();
    if (t - (last.get(fkey + ":" + trip) ?? 0) < MIN_GAP_MS) return Response.json({ ok: true, ignored: "too-fast" });
    last.set(fkey + ":" + trip, t);
    const when = Math.min(num(body.at) ?? t, t);
    const out = fleetPublish(fkey, trip, found.userId, {
      lat: body.lat as number, lng: body.lng as number, at: when,
      heading: num(body.heading), speed: num(body.speed), accuracy: num(body.accuracy),
    }, { label: fleetLabel(found.job), kind: fleetKind(found.job) });
    if (out === "not-your-trip") return no(403, "That is not your record.");
    // Zones: a position that was believed is a position the zones may see. Never waits on, or fails because of, them.
    if (out !== "old") await checkPosition({ entityType: entity, entityId: trip }, { lat: body.lat as number, lng: body.lng as number, at: when, accuracy: num(body.accuracy) });
    return Response.json({ ok: true, ignored: out === "old" ? "old" : undefined });
  }
  if (!mayShare(found.job, found.userId)) return no(403, "Only the person on the move may share their position.");

  const key = tripKey(entity, trip);

  if (body.done === true) {
    finish(key, found.userId);
    return Response.json({ ok: true });
  }

  if (finished(found.job)) {
    finish(key, found.userId); // followers are told, and the spot is forgotten
    return no(409, "This job is over.");
  }
  if (!validPosition(body.lat, body.lng)) return no(400, "That is not a place on Earth.");

  const now = Date.now();
  if (now - (last.get(key) ?? 0) < MIN_GAP_MS) return Response.json({ ok: true, ignored: "too-fast" });
  last.set(key, now);

  // A phone's clock can be wrong: a note from the future is stamped now.
  const at = Math.min(num(body.at) ?? now, now);
  const result = publish(key, found.userId, {
    lat: body.lat as number, lng: body.lng as number, at,
    heading: num(body.heading), speed: num(body.speed), accuracy: num(body.accuracy),
    stage: typeof body.stage === "string" ? body.stage : undefined,
  });
  if (result === "not-your-trip") return no(403, "Only the person on the move may share their position.");
  if (result !== "old") await checkPosition({ entityType: entity, entityId: trip }, { lat: body.lat as number, lng: body.lng as number, at, accuracy: num(body.accuracy) });
  return Response.json({ ok: true, ignored: result === "old" ? "old" : undefined });
}
