/**
 * The geofence service: one fix in, the crossings out — recorded once, and announced once.
 *
 * It owns no database and no bus. A `GeofenceStore` (Postgres in an app, memory in a test) keeps zones, states and events;
 * an `announce` function tells the rest of the app. That keeps the rules of the thing — which zones to check, in what
 * order, what is saved before what is announced — testable without either.
 *
 * ORDER MATTERS. State is saved, then events are recorded (the engine's event id is the key, so a second try records
 * nothing), then only the NEWLY recorded events are announced. A crash between the steps is repaired by the next fix or a
 * retry: nothing is announced twice and nothing recorded is lost.
 *
 * LIMITS, said plainly: one process keeps one fix at a time per entity (a queue per entity); two servers handling the same
 * entity at once can each read the same state. The event id still stops a crossing being recorded twice, so the worst case
 * is a crossing seen a fix late. These are proximity events: they must never alone complete a job or move money.
 *
 * Forge runtime — do not remove.
 */
import { evaluate, FenceIndex, initialState, type Fence, type Fix, type GeofenceEvent, type Ignored, type State } from "./engine";

export type Subject = { entityType: string; entityId: string };

export interface GeofenceStore {
  /** Every active zone. */
  loadFences(): Promise<Fence[]>;
  /** zone id → "Type:id" or "Type:*" the zone is limited to. A zone not in the map watches everyone. */
  loadAssignments(): Promise<Map<string, string[]>>;
  /** The zones this entity is inside, by id. */
  insideFenceIds(who: Subject): Promise<string[]>;
  loadStates(who: Subject, fenceIds: string[]): Promise<Map<string, State>>;
  saveStates(who: Subject, states: Map<string, State>): Promise<void>;
  /** Records the events; returns only those that were new. */
  recordEvents(events: GeofenceEvent[]): Promise<GeofenceEvent[]>;
}

export interface ServiceDeps {
  store: GeofenceStore;
  /** Tell the rest of the app about a crossing. Failures are logged, never thrown: a bus outage must not lose a position. */
  announce?: (event: GeofenceEvent) => Promise<void>;
  now?: () => number;
  /** How long the loaded zones are trusted (ms). `invalidate()` forgets them at once. Default 30 s. */
  fenceTtlMs?: number;
}

export type IngestResult = { events: GeofenceEvent[]; checked: number; ignored: Ignored[] };

/** Does a zone watch this entity? Unassigned zones watch everyone. */
export function watches(assign: string[] | undefined, who: Subject): boolean {
  if (!assign || assign.length === 0) return true;
  return assign.includes(`${who.entityType}:${who.entityId}`) || assign.includes(`${who.entityType}:*`) || assign.includes("*:*");
}

export function makeGeofenceService(deps: ServiceDeps) {
  const now = deps.now ?? Date.now;
  const ttl = deps.fenceTtlMs ?? 30_000;
  let cache: { at: number; index: FenceIndex; assign: Map<string, string[]> } | null = null;
  const queues = new Map<string, Promise<unknown>>();

  async function zones() {
    if (cache && now() - cache.at < ttl) return cache;
    const [fences, assign] = await Promise.all([deps.store.loadFences(), deps.store.loadAssignments()]);
    cache = { at: now(), index: new FenceIndex(fences), assign };
    return cache;
  }

  /** One at a time per entity, so two quick fixes cannot read the same state. */
  function serial<T>(key: string, fn: () => Promise<T>): Promise<T> {
    const run = (queues.get(key) ?? Promise.resolve()).catch(() => undefined).then(fn);
    queues.set(key, run);
    void run.finally(() => { if (queues.get(key) === run) queues.delete(key); }).catch(() => undefined);
    return run;
  }

  async function ingestNow(who: Subject, fix: Omit<Fix, "entityId" | "entityType">, opts: { replay?: boolean }): Promise<IngestResult> {
    const full: Fix = { ...fix, entityId: who.entityId, entityType: who.entityType };
    const { index, assign } = await zones();
    if (index.size === 0) return { events: [], checked: 0, ignored: [] }; // no zones: no further queries
    const insideIds = await deps.store.insideFenceIds(who);
    const candidates = index.candidates(fix.lat, fix.lng, insideIds).filter((f) => watches(assign.get(f.id), who));
    if (candidates.length === 0) return { events: [], checked: 0, ignored: [] };

    const states = await deps.store.loadStates(who, candidates.map((f) => f.id));
    const changed = new Map<string, State>();
    const events: GeofenceEvent[] = [];
    const ignored: Ignored[] = [];
    const t = now();
    for (const fence of candidates) {
      const r = evaluate(fence, states.get(fence.id) ?? initialState(), full, t, { replay: opts.replay });
      if (r.ignored) { ignored.push(r.ignored); continue; }
      changed.set(fence.id, r.state);
      events.push(...r.events);
    }
    if (changed.size) await deps.store.saveStates(who, changed);
    const fresh = events.length ? await deps.store.recordEvents(events) : [];
    for (const e of fresh) {
      try { await deps.announce?.(e); } catch (err) { console.warn("[geofence] announce failed (non-fatal):", err); }
    }
    return { events: fresh, checked: candidates.length, ignored };
  }

  return {
    /** A position from someone on the move. `replay` for a batch sent after being offline. */
    ingest(who: Subject, fix: Omit<Fix, "entityId" | "entityType">, opts: { replay?: boolean } = {}): Promise<IngestResult> {
      return serial(`${who.entityType}:${who.entityId}`, () => ingestNow(who, fix, opts));
    },
    /** Forget the loaded zones (a zone was added, moved or switched off). */
    invalidate(): void { cache = null; },
  };
}
