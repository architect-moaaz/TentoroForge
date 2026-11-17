import { test } from "node:test";
import assert from "node:assert/strict";
import { walk, offset } from "../../geofence/simulate.ts";
import type { Fence, GeofenceEvent, State } from "../../geofence/engine.ts";
import type { GeofenceStore, Subject } from "../../geofence/service.ts";

// run with: node --experimental-strip-types --import ./_register.mjs (service.ts imports ./engine without an extension, as it ships)
const { makeGeofenceService } = await import("../../geofence/service.ts");

const C = { lat: 12.9784, lng: 77.6408 };
const fence = (id = "f1", over: Partial<Fence> = {}): Fence => ({ id, active: true, shape: { type: "circle", center: C, radiusM: 200 }, rules: {}, ...over });
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** A store in memory that counts what it is asked, and can be slowed down. */
function memory(fences: Fence[], assignments: Record<string, string[]> = {}, latencyMs = 0) {
  const states = new Map<string, State>();
  const recorded = new Map<string, GeofenceEvent>();
  const calls = { loadFences: 0, insideFenceIds: 0, loadStates: 0, saveStates: 0, recordEvents: 0 };
  const key = (w: Subject, f: string) => `${f}|${w.entityType}|${w.entityId}`;
  const store: GeofenceStore = {
    async loadFences() { calls.loadFences++; return fences; },
    async loadAssignments() { return new Map(Object.entries(assignments)); },
    async insideFenceIds(w) { calls.insideFenceIds++; await sleep(latencyMs); return [...states].filter(([k, s]) => k.endsWith(`|${w.entityType}|${w.entityId}`) && s.phase === "inside").map(([k]) => k.split("|")[0]); },
    async loadStates(w, ids) { calls.loadStates++; await sleep(latencyMs); const m = new Map<string, State>(); for (const i of ids) { const s = states.get(key(w, i)); if (s) m.set(i, structuredClone(s)); } return m; },
    async saveStates(w, m) { calls.saveStates++; await sleep(latencyMs); for (const [i, s] of m) states.set(key(w, i), structuredClone(s)); },
    async recordEvents(es) { calls.recordEvents++; const fresh: GeofenceEvent[] = []; for (const e of es) if (!recorded.has(e.id)) { recorded.set(e.id, e); fresh.push(e); } return fresh; },
  };
  return { store, states, recorded, calls };
}

const who: Subject = { entityType: "Order", entityId: "o1" };
const drive = (entityId = "o1") => walk([offset(C, -600, 0), offset(C, 600, 0)], { entityId, jitterM: 2, accuracy: 8 });

async function feed(svc: ReturnType<typeof makeGeofenceService>, w: Subject, fixes: ReturnType<typeof drive>) {
  const out: GeofenceEvent[] = [];
  for (const f of fixes) out.push(...(await svc.ingest(w, { lat: f.lat, lng: f.lng, at: f.at, accuracy: f.accuracy })).events);
  return out;
}

test("a drive through a zone is recorded once and announced once, in order", async () => {
  const m = memory([fence()]);
  const told: string[] = [];
  let clock = 0;
  const svc = makeGeofenceService({ store: m.store, announce: async (e) => { told.push(e.type); }, now: () => clock });
  const fixes = drive();
  const events: GeofenceEvent[] = [];
  for (const f of fixes) { clock = f.at + 500; events.push(...(await svc.ingest(who, { lat: f.lat, lng: f.lng, at: f.at, accuracy: f.accuracy })).events); }
  assert.deepEqual(events.map((e) => e.type), ["geofence.entered", "geofence.exited"]);
  assert.deepEqual(told, ["geofence.entered", "geofence.exited"]);
  assert.equal(m.recorded.size, 2);
});

test("the exit is seen even though the last fixes are far outside the zone's neighbourhood", async () => {
  const m = memory([fence()]);
  let clock = 0;
  const svc = makeGeofenceService({ store: m.store, now: () => clock });
  const fast = walk([offset(C, -600, 0), offset(C, 5000, 0)], { speedMps: 24, everySec: 5, accuracy: 8 }); // 120 m between fixes, so the last fixes are far past the padded box
  const events: GeofenceEvent[] = [];
  for (const f of fast) { clock = f.at + 500; events.push(...(await svc.ingest(who, { lat: f.lat, lng: f.lng, at: f.at, accuracy: 8 })).events); }
  assert.deepEqual(events.map((e) => e.type), ["geofence.entered", "geofence.exited"]);
});

test("the same fix sent again, or a retry that records the same event, announces nothing new", async () => {
  const m = memory([fence()]);
  const told: string[] = [];
  let clock = 0;
  const svc = makeGeofenceService({ store: m.store, announce: async (e) => { told.push(e.id); }, now: () => clock });
  const fixes = drive();
  for (const f of fixes) { clock = f.at + 500; await svc.ingest(who, { lat: f.lat, lng: f.lng, at: f.at, accuracy: f.accuracy }); await svc.ingest(who, { lat: f.lat, lng: f.lng, at: f.at, accuracy: f.accuracy }); }
  assert.equal(told.length, 2);
  assert.equal(new Set(told).size, 2);
  // the state is lost (a crashed save) and the whole drive is sent again: the events are the same events, not new ones
  m.states.clear();
  const again = makeGeofenceService({ store: m.store, announce: async (e) => { told.push(e.id); }, now: () => clock });
  for (const f of fixes) { clock = f.at + 500; await again.ingest(who, { lat: f.lat, lng: f.lng, at: f.at, accuracy: f.accuracy }); }
  assert.equal(told.length, 2, "recording is keyed by the event id, so nothing is announced twice");
});

test("a zone limited to some entities ignores the others", async () => {
  const m = memory([fence("only-o1")], { "only-o1": ["Order:o1"] });
  let clock = 0;
  const svc = makeGeofenceService({ store: m.store, now: () => clock });
  const mine = await feed(svc, who, drive().map((f) => (clock = f.at + 500, f)));
  const theirs = await feed(svc, { entityType: "Order", entityId: "o2" }, drive("o2").map((f) => (clock = f.at + 500, f)));
  assert.equal(mine.length, 2);
  assert.equal(theirs.length, 0);
});

test("a zone for every order of a type, and a zone for everyone, are both honoured", async () => {
  const m = memory([fence("all-orders"), fence("everyone")], { "all-orders": ["Order:*"] });
  let clock = 0;
  const svc = makeGeofenceService({ store: m.store, now: () => clock });
  const orders = await feed(svc, who, drive().map((f) => (clock = f.at + 500, f)));
  assert.equal(orders.length, 4); // two zones, in and out
  const drivers = await feed(svc, { entityType: "Driver", entityId: "d1" }, drive("d1").map((f) => (clock = f.at + 500, f)));
  assert.equal(drivers.length, 2); // only "everyone"
});

test("with no zones nothing is asked of the database after the first look", async () => {
  const m = memory([]);
  const svc = makeGeofenceService({ store: m.store });
  for (const f of drive()) await svc.ingest(who, { lat: f.lat, lng: f.lng, at: f.at });
  assert.equal(m.calls.loadFences, 1);
  assert.equal(m.calls.insideFenceIds + m.calls.loadStates + m.calls.saveStates + m.calls.recordEvents, 0);
});

test("a zone added later is seen once the service is told", async () => {
  const fences: Fence[] = [];
  const m = memory(fences);
  let clock = 0;
  const svc = makeGeofenceService({ store: m.store, now: () => clock });
  const fixes = drive();
  clock = fixes[0].at + 500;
  await svc.ingest(who, { lat: fixes[0].lat, lng: fixes[0].lng, at: fixes[0].at });
  fences.push(fence());
  svc.invalidate();
  const events: GeofenceEvent[] = [];
  for (const f of fixes.slice(1)) { clock = f.at + 500; events.push(...(await svc.ingest(who, { lat: f.lat, lng: f.lng, at: f.at, accuracy: 8 })).events); }
  assert.equal(events.length, 2);
});

test("an announce that fails does not lose the position or the record", async () => {
  const m = memory([fence()]);
  let clock = 0;
  const svc = makeGeofenceService({ store: m.store, announce: async () => { throw new Error("bus down"); }, now: () => clock });
  const origWarn = console.warn; console.warn = () => {};
  try { const events = await feed(svc, who, drive().map((f) => (clock = f.at + 500, f))); assert.equal(events.length, 2); } finally { console.warn = origWarn; }
  assert.equal(m.recorded.size, 2);
});

test("quick fixes for one entity are handled one at a time, so one crossing is not found twice", async () => {
  const m = memory([fence()], {}, 3);
  let clock = 0;
  const told: string[] = [];
  const svc = makeGeofenceService({ store: m.store, announce: async (e) => { told.push(e.type); }, now: () => clock });
  const fixes = drive();
  clock = fixes[fixes.length - 1].at + 500;
  const all = await Promise.all(fixes.map((f) => svc.ingest(who, { lat: f.lat, lng: f.lng, at: f.at, accuracy: f.accuracy }, { replay: true })));
  const events = all.flatMap((r) => r.events);
  assert.deepEqual(events.map((e) => e.type), ["geofence.entered", "geofence.exited"]);
  assert.deepEqual(told, ["geofence.entered", "geofence.exited"]);
});

test("different entities do not wait for one another", async () => {
  const m = memory([fence()], {}, 20);
  let clock = 0;
  const svc = makeGeofenceService({ store: m.store, now: () => clock });
  clock = 1_700_000_000_000 + 1000;
  const f = drive()[0];
  const t = Date.now();
  await Promise.all(Array.from({ length: 10 }, (_, i) => svc.ingest({ entityType: "Order", entityId: `x${i}` }, { lat: C.lat, lng: C.lng, at: f.at, accuracy: 5 })));
  assert.ok(Date.now() - t < 120, `ten entities took ${Date.now() - t} ms; one after another would be about 600`);
});

test("a store that is down makes ingest fail loudly (the caller decides to swallow it)", async () => {
  const m = memory([fence()]);
  m.store.loadFences = async () => { throw new Error("relation forge_geofences does not exist"); };
  const svc = makeGeofenceService({ store: m.store });
  await assert.rejects(() => svc.ingest(who, { lat: C.lat, lng: C.lng, at: 1 }), /does not exist/);
});
