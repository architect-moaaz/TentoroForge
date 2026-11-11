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
