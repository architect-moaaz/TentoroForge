/**
 * The geofencing engine — pure geometry and a state machine. No database, no network, no clock of its own, no imports.
 *
 *   evaluate(fence, state, fix, now)  ->  { state, events, ignored? }
 *
 * One fix for one entity against one fence. The caller keeps the state (outside / inside, since when, the last fix it
 * processed) wherever it likes — the database in a real app, a map in a test — and hands it back with the next fix.
 *
 * WHAT IT PROMISES
 *   - A crossing is a state change, never a coordinate. An entity that stays inside raises no second `entered`.
 *   - GPS error is uncertainty, not truth: a fix is "surely inside" only when it is inside by more than its own accuracy,
 *     and "surely outside" only when it is outside by more than the exit margin plus its accuracy. Between the two the
 *     state is kept, which is what stops a parked phone at the kerb from entering and leaving all afternoon (hysteresis).
 *   - A crossing needs `minFixes` agreeing fixes in a row.
 *   - A fix older than the last one processed (or the same one sent twice) changes nothing: out-of-order and duplicate
 *     updates are harmless, and every event has an id that is the same for the same crossing, so a business action keyed
 *     on it runs once.
 *   - A fix that is invalid, too inaccurate, too old (unless it is a replay after being offline) or from the future is
 *     ignored, and the engine says why.
 *   - Time offline is not time inside: after a long gap the dwell timer starts over.
 *
 * WHAT IT DOES NOT PROMISE
 *   - Presence. A phone that says it is inside a fence may be spoofed. These are PROXIMITY events: they must never, alone,
 *     complete an order, take a payment or mark attendance; the caller adds a check that is not GPS.
 *
 * Forge runtime — do not remove. Single file on purpose: a shipped app cannot import with `.ts` extensions and a test
 * runner needs them, so there is nothing to import.
 */

// ---------------------------------------------------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------------------------------------------------

export type LatLng = { lat: number; lng: number };

export type Shape =
  | { type: "circle"; center: LatLng; radiusM: number }
  | { type: "polygon"; ring: LatLng[] };

/** What a fence does with a crossing, and how forgiving it is. Every field has a default. */
export type FenceRules = {
  /** Raise `geofence.entered` / `geofence.exited` (both default true). */
  enter?: boolean;
  exit?: boolean;
  /** Raise `geofence.dwell` once per visit after this long inside. */
  dwellSec?: number | null;
  /** Raise `geofence.approaching` once when the entity comes this close (metres) from outside. */
  approachM?: number | null;
  /** How far outside the edge an entity must be to count as having left (default 10 m). */
  hysteresisM?: number;
  /** Agreeing fixes in a row needed to enter or leave (default 2). */
  minFixes?: number;
  /** A fix less accurate than this (metres) is ignored; a more accurate one is trusted up to this much (default 100). */
  maxAccuracyM?: number;
  /** A fix older than this (ms) when it arrives is stale and ignored, unless it is a replay (default 120 000). */
  staleMs?: number;
  /** A fix this far (ms) after the previous one means the entity was out of touch: dwell starts over (default 600 000). */
  maxGapMs?: number;
  /** A fix stamped this far (ms) ahead of the clock is from a wrong phone clock and ignored (default 300 000). */
  clockSkewMs?: number;
};

export type Fence = {
  id: string;
  shape: Shape;
  /** An inactive fence raises nothing and keeps no state. */
  active: boolean;
  rules?: FenceRules;
};

export type Fix = {
  entityId: string;
  entityType: string;
  lat: number;
  lng: number;
  /** When the device says it was there (ms since 1970). */
  at: number;
  /** Horizontal accuracy radius in metres, when the device says. */
  accuracy?: number;
};

export type Phase = "outside" | "inside";

export type State = {
  phase: Phase;
  /** When the current visit began (ms), or null. */
  since: number | null;
  /** The timestamp of the last fix this state has processed. Anything not newer is old. */
  lastAt: number;
  lastLat: number | null;
  lastLng: number | null;
  /** Agreeing fixes in a row. */
  inStreak: number;
  outStreak: number;
  /** Counts visits: the same visit number means the same crossing, so ids repeat for repeats. */
  visit: number;
  /** Dwell and approaching are raised once per visit / approach. */
  dwellDone: boolean;
  approachDone: boolean;
  /** Where the dwell timer counts from: `since`, or the last time the entity came back from being out of touch. */
  dwellFrom: number | null;
};

export type EventType = "geofence.entered" | "geofence.exited" | "geofence.dwell" | "geofence.approaching";

export type GeofenceEvent = {
  /** The same crossing always has the same id. */
  id: string;
  type: EventType;
  geofenceId: string;
  entityId: string;
  entityType: string;
  lat: number;
  lng: number;
  /** When the device was there. */
  occurredAt: number;
  /** When the engine noticed. */
  detectedAt: number;
  metadata: Record<string, unknown>;
};

export type Ignored = "invalid" | "inactive" | "inaccurate" | "stale" | "future" | "old" | "duplicate";

export type Result = { state: State; events: GeofenceEvent[]; ignored?: Ignored };

// ---------------------------------------------------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------------------------------------------------

const EARTH_M = 6_371_008.8;
const RAD = Math.PI / 180;

export function validPosition(lat: unknown, lng: unknown): lat is number {
  return (
    typeof lat === "number" && typeof lng === "number" && Number.isFinite(lat) && Number.isFinite(lng) &&
    lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180
  );
}

/** Great-circle distance in metres. */
export function distanceM(a: LatLng, b: LatLng): number {
  const dLat = (b.lat - a.lat) * RAD;
  const dLng = (b.lng - a.lng) * RAD;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * RAD) * Math.cos(b.lat * RAD) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** A point in metres east and north of `origin`, flat-earth: good to a fraction of a percent over a few hundred km. */
function toLocal(origin: LatLng, p: LatLng): { x: number; y: number } {
  let dLng = p.lng - origin.lng;
  if (dLng > 180) dLng -= 360;
  if (dLng < -180) dLng += 360;
  return { x: dLng * RAD * EARTH_M * Math.cos(origin.lat * RAD), y: (p.lat - origin.lat) * RAD * EARTH_M };
}

function distanceToSegment(a: { x: number; y: number }, b: { x: number; y: number }): number {
  // distance from the origin to the segment a-b
  const dx = b.x - a.x, dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, -(a.x * dx + a.y * dy) / len2));
  return Math.hypot(a.x + t * dx, a.y + t * dy);
}

/** Signed distance from the edge in metres: negative inside, positive outside, about 0 on the boundary. */
export function signedDistanceM(shape: Shape, p: LatLng): number {
  if (shape.type === "circle") return distanceM(shape.center, p) - shape.radiusM;
  const pts = shape.ring.map((v) => toLocal(p, v));
  let inside = false;
  let nearest = Infinity;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const a = pts[j], b = pts[i];
    nearest = Math.min(nearest, distanceToSegment(a, b));
    // ray cast along +x from the origin
    if ((a.y > 0) !== (b.y > 0) && 0 < ((b.x - a.x) * (0 - a.y)) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside ? -nearest : nearest;
}

export function contains(shape: Shape, p: LatLng): boolean {
  return signedDistanceM(shape, p) <= 0;
}

/** Why a shape cannot be a fence, or null. Radii are 5 m to 100 km; a polygon has 3 to 500 corners and some area. */
export function invalidShape(shape: Shape): string | null {
  if (!shape || typeof shape !== "object") return "A fence needs a shape.";
  if (shape.type === "circle") {
    if (!shape.center || !validPosition(shape.center.lat, shape.center.lng)) return "The centre is not a place on Earth.";
    if (typeof shape.radiusM !== "number" || !Number.isFinite(shape.radiusM)) return "The radius must be a number of metres.";
    if (shape.radiusM < 5) return "The radius must be at least 5 metres.";
    if (shape.radiusM > 100_000) return "The radius must be at most 100 km.";
    return null;
  }
  if (shape.type === "polygon") {
    const ring = Array.isArray(shape.ring) ? shape.ring : [];
    const open = ring.length > 1 && ring[0].lat === ring[ring.length - 1].lat && ring[0].lng === ring[ring.length - 1].lng ? ring.slice(0, -1) : ring;
    if (open.length < 3) return "A polygon needs at least 3 corners.";
    if (open.length > 500) return "A polygon can have at most 500 corners.";
    if (open.some((v) => !v || !validPosition(v.lat, v.lng))) return "A corner is not a place on Earth.";
    const pts = open.map((v) => toLocal(open[0], v));
    let area2 = 0;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) area2 += pts[j].x * pts[i].y - pts[i].x * pts[j].y;
    if (Math.abs(area2) / 2 < 25) return "The polygon has no area (its corners are in a line or too close together).";
    return null;
  }
  return "A fence is a circle or a polygon.";
}

/** A polygon ring without its repeated closing corner. */
export function openRing(ring: LatLng[]): LatLng[] {
  return ring.length > 1 && ring[0].lat === ring[ring.length - 1].lat && ring[0].lng === ring[ring.length - 1].lng ? ring.slice(0, -1) : ring;
}

/** The box around a shape, padded by `padM`, as { minLat, maxLat, minLng, maxLng }. */
export function boundsOf(shape: Shape, padM = 0): { minLat: number; maxLat: number; minLng: number; maxLng: number } {
  const dLat = (v: number) => v / (EARTH_M * RAD);
  if (shape.type === "circle") {
    const r = shape.radiusM + padM;
    const dLng = r / (EARTH_M * RAD * Math.max(0.01, Math.cos(shape.center.lat * RAD)));
    return { minLat: shape.center.lat - dLat(r), maxLat: shape.center.lat + dLat(r), minLng: shape.center.lng - dLng, maxLng: shape.center.lng + dLng };
  }
  const ring = openRing(shape.ring);
  const lats = ring.map((v) => v.lat), lngs = ring.map((v) => v.lng);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const dLng = padM / (EARTH_M * RAD * Math.max(0.01, Math.cos(midLat * RAD)));
  return { minLat: Math.min(...lats) - dLat(padM), maxLat: Math.max(...lats) + dLat(padM), minLng: Math.min(...lngs) - dLng, maxLng: Math.max(...lngs) + dLng };
}

// ---------------------------------------------------------------------------------------------------------------------
// The state machine
// ---------------------------------------------------------------------------------------------------------------------

export const DEFAULTS = {
  hysteresisM: 10,
  minFixes: 2,
  maxAccuracyM: 100,
  staleMs: 120_000,
  maxGapMs: 600_000,
  clockSkewMs: 300_000,
} as const;

export function initialState(): State {
  return { phase: "outside", since: null, lastAt: 0, lastLat: null, lastLng: null, inStreak: 0, outStreak: 0, visit: 0, dwellDone: false, approachDone: false, dwellFrom: null };
}

export type EvaluateOptions = {
  /** A batch of fixes sent after being offline: not stale for being old, only for being out of order. */
  replay?: boolean;
};

/** One fix against one fence. Returns the next state and the events it raised; never mutates its arguments. */
export function evaluate(fence: Fence, prior: State, fix: Fix, now: number, opts: EvaluateOptions = {}): Result {
  const rules = fence.rules ?? {};
  const hyst = rules.hysteresisM ?? DEFAULTS.hysteresisM;
  const minFixes = Math.max(1, rules.minFixes ?? DEFAULTS.minFixes);
  const maxAcc = rules.maxAccuracyM ?? DEFAULTS.maxAccuracyM;
  const stale = rules.staleMs ?? DEFAULTS.staleMs;
  const maxGap = rules.maxGapMs ?? DEFAULTS.maxGapMs;
  const skew = rules.clockSkewMs ?? DEFAULTS.clockSkewMs;
  const keep = (why: Ignored): Result => ({ state: prior, events: [], ignored: why });

  if (!validPosition(fix.lat, fix.lng) || typeof fix.at !== "number" || !Number.isFinite(fix.at) || !fix.entityId) return keep("invalid");
  if (!fence.active) return keep("inactive");
  if (fix.at > now + skew) return keep("future");
  if (!opts.replay && now - fix.at > stale) return keep("stale");
  if (prior.lastAt > 0 && fix.at === prior.lastAt && fix.lat === prior.lastLat && fix.lng === prior.lastLng) return keep("duplicate");
  if (fix.at <= prior.lastAt) return keep("old");
  if (typeof fix.accuracy === "number" && fix.accuracy > maxAcc) return keep("inaccurate");

  const here = { lat: fix.lat, lng: fix.lng };
  const d = signedDistanceM(fence.shape, here);
  const err = Math.min(typeof fix.accuracy === "number" && fix.accuracy >= 0 ? fix.accuracy : 0, maxAcc);
  const surelyInside = d <= -err;
  const surelyOutside = d >= hyst + err;

  const s: State = { ...prior, lastAt: fix.at, lastLat: fix.lat, lastLng: fix.lng };
  const events: GeofenceEvent[] = [];
  const emit = (type: EventType, metadata: Record<string, unknown> = {}, suffix = "") => {
    events.push({
      id: `${fence.id}:${fix.entityId}:${type}:${s.visit}${suffix}`,
      type, geofenceId: fence.id, entityId: fix.entityId, entityType: fix.entityType,
      lat: fix.lat, lng: fix.lng, occurredAt: fix.at, detectedAt: now,
      metadata: { visit: s.visit, distanceM: Math.round(d * 10) / 10, accuracyM: fix.accuracy ?? null, ...metadata },
    });
  };

  // out of touch for too long: we cannot say they were inside or out in between
  const gapMs = prior.lastAt > 0 ? fix.at - prior.lastAt : 0;
  const afterGap = gapMs > maxGap;
  if (afterGap) {
    s.inStreak = 0;
    s.outStreak = 0;
    if (s.phase === "inside") s.dwellFrom = fix.at;
  }

  if (surelyInside) { s.inStreak = s.inStreak + 1; s.outStreak = 0; }
  else if (surelyOutside) { s.outStreak = s.outStreak + 1; s.inStreak = 0; }
  // between the two: the state and the streaks stay as they were

  const firstEver = prior.lastAt === 0;

  if (s.phase === "outside" && s.inStreak >= minFixes) {
    s.phase = "inside";
    s.visit = prior.visit + 1;
    s.since = fix.at;
    s.dwellFrom = fix.at;
    s.dwellDone = false;
    s.approachDone = true;
    s.outStreak = 0;
    if (rules.enter !== false) emit("geofence.entered", { firstFix: firstEver, afterGapMs: afterGap ? gapMs : undefined });
  } else if (s.phase === "inside" && s.outStreak >= minFixes) {
    const dwellMs = s.since != null ? fix.at - s.since : null;
    if (rules.exit !== false) emit("geofence.exited", { dwellMs, afterGapMs: afterGap ? gapMs : undefined });
    s.phase = "outside";
    s.since = null;
    s.dwellFrom = null;
    s.approachDone = true; // just left: not "approaching" again until they have gone well away and come back
    s.inStreak = 0;
  }

  // dwell: once per visit, after enough time spent inside, counting only time we have actually heard from them
  if (s.phase === "inside" && rules.dwellSec && !s.dwellDone && surelyInside && s.dwellFrom != null && fix.at - s.dwellFrom >= rules.dwellSec * 1000) {
    s.dwellDone = true;
    emit("geofence.dwell", { dwellMs: fix.at - (s.since ?? fix.at) });
  }

  // approaching: once per approach, from outside, when they come within the distance; rearmed when they are well away again
  if (s.phase === "outside" && rules.approachM && rules.approachM > 0) {
    if (!s.approachDone && d > 0 && d <= rules.approachM) {
      s.approachDone = true;
      emit("geofence.approaching", { withinM: rules.approachM }, `:${prior.visit}`);
    } else if (s.approachDone && d > rules.approachM + hyst) {
      s.approachDone = false;
    }
  }

  return { state: s, events };
}

// ---------------------------------------------------------------------------------------------------------------------
// Finding the fences worth checking
// ---------------------------------------------------------------------------------------------------------------------

/**
 * A grid over the fences, so a fix is checked against the few fences near it and not against all of them.
 * A fence goes into every grid cell its padded box touches; a fence too big for that goes in a short list that is always
 * looked at. Antimeridian-crossing fences are not supported (a fence is split in two there instead).
 */
export class FenceIndex {
  private cells = new Map<string, Fence[]>();
  private wide: Fence[] = [];
  private boxes = new Map<string, ReturnType<typeof boundsOf>>();
  private byId = new Map<string, Fence>();
  private readonly cell: number;

  constructor(fences: Fence[] = [], cellDegrees = 0.02) {
    this.cell = cellDegrees;
    for (const f of fences) this.add(f);
  }

  private pad(f: Fence): number {
    const r = f.rules ?? {};
    return (r.approachM ?? 0) + (r.hysteresisM ?? DEFAULTS.hysteresisM) + (r.maxAccuracyM ?? DEFAULTS.maxAccuracyM);
  }

  add(f: Fence): void {
    this.remove(f.id);
    if (!f.active) return;
    const box = boundsOf(f.shape, this.pad(f));
    this.boxes.set(f.id, box);
    this.byId.set(f.id, f);
    const x0 = Math.floor(box.minLng / this.cell), x1 = Math.floor(box.maxLng / this.cell);
    const y0 = Math.floor(box.minLat / this.cell), y1 = Math.floor(box.maxLat / this.cell);
    if ((x1 - x0 + 1) * (y1 - y0 + 1) > 2500) { this.wide.push(f); return; }
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) {
      const k = `${x}:${y}`;
      const list = this.cells.get(k);
      if (list) list.push(f); else this.cells.set(k, [f]);
    }
  }

  remove(id: string): void {
    if (!this.boxes.has(id)) return;
    this.boxes.delete(id);
    this.byId.delete(id);
    this.wide = this.wide.filter((f) => f.id !== id);
    for (const [k, list] of this.cells) {
      const next = list.filter((f) => f.id !== id);
      if (next.length) this.cells.set(k, next); else this.cells.delete(k);
    }
  }

  /** Active fences whose padded box holds the point. */
  near(lat: number, lng: number): Fence[] {
    const list = this.cells.get(`${Math.floor(lng / this.cell)}:${Math.floor(lat / this.cell)}`) ?? [];
    const out: Fence[] = [];
    for (const f of [...list, ...this.wide]) {
      const b = this.boxes.get(f.id);
      if (b && lat >= b.minLat && lat <= b.maxLat && lng >= b.minLng && lng <= b.maxLng && !out.includes(f)) out.push(f);
    }
    return out;
  }

  /**
   * The fences to check for one fix: those near it, PLUS every fence the entity is currently inside (`insideIds`).
   * The second part matters: leaving needs a few fixes that are clearly outside, and those can fall beyond the padded box,
   * so a fence the entity is in must be checked wherever it goes or it would never be seen to leave.
   */
  candidates(lat: number, lng: number, insideIds: Iterable<string> = []): Fence[] {
    const out = this.near(lat, lng);
    for (const id of insideIds) {
      const f = this.byId.get(id);
      if (f && !out.includes(f)) out.push(f);
    }
    return out;
  }

  get size(): number { return this.boxes.size; }
}
