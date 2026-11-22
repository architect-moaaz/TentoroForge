/**
 * The tracking hub — a mailbox for live positions, one per trip.
 *
 * It lives in memory, inside ONE running server (the same posture as the
 * presence roster). That proves the live dot; a Redis-backed hub is the
 * production step. It is kept on `globalThis` because Next compiles each route
 * separately — a plain module variable would be a different mailbox in the
 * update route and in the stream route.
 *
 *   publish(trip, who, note)  the driver's note arrives
 *   listen(trip, fn)          the stream asks to hear every new note
 *   latest(trip)              the newest note, for someone who opens late
 *   finish(trip)              the trip is over: tell listeners, forget the spot
 *
 * Forge runtime — do not remove.
 */
export type Position = {
  lat: number;
  lng: number;
  /** When the phone says it was there (ms since 1970). Older notes are dropped. */
  at: number;
  heading?: number;
  speed?: number;
  accuracy?: number;
  /** Where the trip is: "to_pickup" | "to_dropoff" | anything the app names. */
  stage?: string;
};

export type Frame = Position | { done: true };
type Listener = (f: Frame) => void;

type Trip = { driver: string; newest?: Position; listeners: Set<Listener> };
const g = globalThis as unknown as { __forgeTracking?: Map<string, Trip> };
const trips: Map<string, Trip> = (g.__forgeTracking ??= new Map());

/** A note older than this is "stale": the map greys the dot. */
export const STALE_MS = 30_000;

/** True when it is a real place on Earth. */
export function validPosition(lat: unknown, lng: unknown): boolean {
  return (
    typeof lat === "number" && typeof lng === "number" &&
    Number.isFinite(lat) && Number.isFinite(lng) &&
    lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180
  );
}

export type Published = "ok" | "old" | "not-your-trip";

/**
 * Keep the note and tell every listener. The first person to send for a trip is
 * its driver; anyone else sending for it is refused. A note older than the
 * newest is ignored, so a slow one can't pull the dot backwards.
 */
export function publish(trip: string, who: string, p: Position): Published {
  let t = trips.get(trip);
  if (!t) trips.set(trip, (t = { driver: who, listeners: new Set() }));
  if (!t.driver) t.driver = who; // someone was already listening: the first sender is the driver
  if (t.driver !== who) return "not-your-trip";
  if (t.newest && p.at <= t.newest.at) return "old";
  t.newest = p;
  t.listeners.forEach((fn) => fn(p));
  return "ok";
}

export function latest(trip: string): Position | undefined {
  return trips.get(trip)?.newest;
}

/** Returns the function that stops listening. */
export function listen(trip: string, fn: Listener): () => void {
  let t = trips.get(trip);
  if (!t) trips.set(trip, (t = { driver: "", listeners: new Set() }));
  t.listeners.add(fn);
  return () => {
    t!.listeners.delete(fn);
    // Nobody is sending and nobody is left listening: forget the empty trip.
    if (!t!.driver && !t!.listeners.size && trips.get(trip) === t) trips.delete(trip);
  };
}

/** Only the driver may end the trip. */
export function finish(trip: string, who: string): boolean {
  const t = trips.get(trip);
  if (!t || (t.driver && t.driver !== who)) return false;
  t.listeners.forEach((fn) => fn({ done: true }));
  trips.delete(trip);
  return true;
}

/* ---------------------------------------------------------------------------
 * THE FLEET — many people on the move, each under their own record id.
 *
 *   fleetPublish(fleet, id, who, note, meta)  one person says "I am here"
 *   fleetSnapshot(fleet)                      everyone on duty right now
 *   fleetListen(fleet, fn)                    hear every change
 *   fleetLeave(fleet, id, who)                one person goes off duty
 *
 * Someone who has said nothing for FLEET_TTL_MS is taken off the map: a phone
 * that died must not look like a driver who is still waiting for work.
 * ------------------------------------------------------------------------- */
export const FLEET_TTL_MS = 120_000;

export type Member = Position & { id: string; label?: string; kind?: string };
export type FleetFrame = Member | { gone: string };
type FleetListener = (f: FleetFrame) => void;
type Fleet = { members: Map<string, { who: string; at: number; m: Member }>; listeners: Set<FleetListener> };
const fg = globalThis as unknown as { __forgeFleet?: Map<string, Fleet> };
const fleets: Map<string, Fleet> = (fg.__forgeFleet ??= new Map());

function fleetOf(key: string): Fleet {
  let f = fleets.get(key);
  if (!f) fleets.set(key, (f = { members: new Map(), listeners: new Set() }));
  return f;
}

/** Drop everyone who has gone quiet, telling the listeners. */
function sweep(key: string, f: Fleet, now: number) {
  for (const [id, e] of f.members) {
    if (now - e.at > FLEET_TTL_MS) {
      f.members.delete(id);
      f.listeners.forEach((fn) => fn({ gone: id }));
    }
  }
  if (!f.members.size && !f.listeners.size && fleets.get(key) === f) fleets.delete(key);
}

/** The first sender for an id owns it; a note older than the newest is ignored. */
export function fleetPublish(
  key: string, id: string, who: string, p: Position, meta: { label?: string; kind?: string } = {},
  now: number = Date.now(),
): Published {
  const f = fleetOf(key);
  sweep(key, f, now);
  // `sweep` forgets a fleet that is empty and has no listener, which is exactly what a first report finds. Put it back before
  // the person is added, or they are added to a fleet nothing can find (positions were lost unless someone was watching).
  if (fleets.get(key) !== f) fleets.set(key, f);
  const cur = f.members.get(id);
  if (cur && cur.who !== who) return "not-your-trip";
  if (cur && p.at <= cur.m.at) return "old";
  const m: Member = { ...p, id, label: meta.label, kind: meta.kind };
  f.members.set(id, { who, at: now, m });
  f.listeners.forEach((fn) => fn(m));
  return "ok";
}

export function fleetSnapshot(key: string, now: number = Date.now()): Member[] {
  const f = fleets.get(key);
  if (!f) return [];
  sweep(key, f, now);
  return [...f.members.values()].map((e) => e.m);
}

/**
 * Everyone on duty with the sign-in id of the phone that said so (`who`): what an alert needs, to reach the nearest people.
 * `heardAt` is when the SERVER last heard from them (not what their phone claims), so a phone with a wrong clock cannot
 * look fresher than it is.
 */
export function fleetOnDuty(key: string, now: number = Date.now()): Array<Member & { who: string; heardAt: number }> {
  const f = fleets.get(key);
  if (!f) return [];
  sweep(key, f, now);
  return [...f.members.values()].map((e) => ({ ...e.m, who: e.who, heardAt: e.at }));
}

/** Returns the function that stops listening. */
export function fleetListen(key: string, fn: FleetListener): () => void {
  const f = fleetOf(key);
  f.listeners.add(fn);
  return () => {
    f.listeners.delete(fn);
    if (!f.members.size && !f.listeners.size && fleets.get(key) === f) fleets.delete(key);
  };
}

/**
 * The SERVER takes someone off the map because their record says they are no
 * longer on duty (they pressed "Go offline", or were suspended), whoever's
 * line noticed. Not for a person to call on another: only the fleet line does.
 */
export function fleetDrop(key: string, id: string): boolean {
  const f = fleets.get(key);
  if (!f || !f.members.delete(id)) return false;
  f.listeners.forEach((fn) => fn({ gone: id }));
  return true;
}

/** Only the person who owns the id may take it off the map. */
export function fleetLeave(key: string, id: string, who: string): boolean {
  const f = fleets.get(key);
  const cur = f?.members.get(id);
  if (!f || !cur || cur.who !== who) return false;
  f.members.delete(id);
  f.listeners.forEach((fn) => fn({ gone: id }));
  return true;
}
