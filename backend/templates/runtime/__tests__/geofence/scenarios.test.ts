import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { walk, stay, offset, oscillate, scramble, rng } from "../../geofence/simulate.ts";
import type { Fence, GeofenceEvent, State } from "../../geofence/engine.ts";
import type { GeofenceStore, Subject } from "../../geofence/service.ts";
import type { Rule, RuleDeps, Held } from "../../geofence/rules.ts";

// Whole scenarios: a brief became a plan (Python, services/blueprint/geofence_plan.py); the plan is applied as an app's seed
// applies it; simulated phones drive through the zones; the rules act. GEOFENCE_PLANS = the folder of plans the Python side wrote.
// run with: node --experimental-transform-types --import ./_register.mjs
const { makeGeofenceService } = await import("../../geofence/service.ts");
const { runRules, releaseHeld } = await import("../../geofence/rules.ts");
const { applyPlan } = await import("../../geofence/plan.ts");

const DIR = process.env.GEOFENCE_PLANS;
const load = (name: string) => JSON.parse(fs.readFileSync(path.join(DIR!, `${name}.json`), "utf8"));
const skip = DIR ? false : "GEOFENCE_PLANS is not set (the Python wrapper sets it)";

function memoryStore(fences: Fence[]) {
  const states = new Map<string, State>();
  const recorded = new Map<string, GeofenceEvent>();
  const key = (w: Subject, f: string) => `${f}|${w.entityType}|${w.entityId}`;
  const store: GeofenceStore = {
    async loadFences() { return fences; },
    async loadAssignments() { return new Map(); },
    async insideFenceIds(w) { return [...states].filter(([k, s]) => k.endsWith(`|${w.entityType}|${w.entityId}`) && s.phase === "inside").map(([k]) => k.split("|")[0]); },
    async loadStates(w, ids) { const m = new Map<string, State>(); for (const i of ids) { const s = states.get(key(w, i)); if (s) m.set(i, structuredClone(s)); } return m; },
    async saveStates(w, m) { for (const [i, s] of m) states.set(key(w, i), structuredClone(s)); },
    async recordEvents(es) { const fresh: GeofenceEvent[] = []; for (const e of es) if (!recorded.has(e.id)) { recorded.set(e.id, e); fresh.push(e); } return fresh; },
  };
  return { store, recorded };
}

/** An app as its seed would make it from the plan, with a bus that only remembers. */
async function app(planName: string, extraRules: Omit<Rule, "id">[] = []) {
  const plan = load(planName);
  const zones = new Map<string, { id: string; fence: Fence; lat: number; lng: number }>();
  const rules: Rule[] = [];
  let n = 0;
  const applied = await applyPlan(plan, {
    zoneId: async (name) => zones.get(name.toLowerCase())?.id ?? null,
    addZone: async (z) => {
      const id = `zone${++n}`;
      zones.set(z.name.toLowerCase(), { id, lat: z.lat, lng: z.lng, fence: { id, active: true, shape: { type: "circle", center: { lat: z.lat, lng: z.lng }, radiusM: z.radiusM }, rules: z.rules as never } });
      return id;
    },
    hasRule: async () => false,
    addRule: async (r) => { rules.push({ id: `rule${++n}`, geofenceId: r.geofenceId, onEvent: r.onEvent, action: r.action as never, sensitive: r.sensitive }); },
  });
  for (const r of extraRules) rules.push({ ...r, id: `rule${++n}` });

  const emitted: { type: string; entityId: string }[] = [];
  const notified: { to: any; title: string }[] = [];
  const held: Held[] = [];
  const evidence = new Set<string>();
  const claimed = new Set<string>();
  const deps: Omit<RuleDeps, "rules"> = {
    claim: async (k) => (claimed.has(k) ? false : (claimed.add(k), true)),
    emit: async (type, o) => { emitted.push({ type, entityId: o.entityId }); },
    notify: async (to, m) => { notified.push({ to, title: m.title }); },
    hasEvidence: async (_t, id, type) => evidence.has(`${id}|${type}`),
  };
  const mem = memoryStore([...zones.values()].map((z) => z.fence));
  let clock = 0;
  const svc = makeGeofenceService({
    store: mem.store,
    now: () => clock,
    announce: async (e) => {
      for (const r of await runRules(e, { rules, ...deps })) {
        if (r.outcome === "held") { const rule = rules.find((x) => x.id === r.ruleId)!; held.push({ rule, event: e, heldAt: clock }); }
      }
    },
  });
  const at = (name: string) => zones.get(name.toLowerCase())!;
  async function drive(entityType: string, entityId: string, fixes: ReturnType<typeof walk>) {
    for (const f of fixes) { clock = f.at + 500; await svc.ingest({ entityType, entityId }, { lat: f.lat, lng: f.lng, at: f.at, accuracy: f.accuracy }); }
  }
  return { applied, zones, rules, emitted, notified, held, evidence, deps, at, drive, mem, now: () => clock };
}

const opts = { speedMps: 10, everySec: 5, jitterM: 2, accuracy: 8, seed: 7 } as const;
const types = (a: { type: string; entityId?: string }[], id?: string) => a.filter((x) => !id || x.entityId === id).map((x) => x.type);

test("delivery: the plan made both zones and every rule, and a drive tells the order's workflow, in order, once each", { skip }, async () => {
  const a = await app("delivery");
  assert.equal(a.applied.zonesToDraw.length, 0, "the brief located both zones");
  assert.equal(a.applied.rulesWaiting.length, 0);
  const R = a.at("Restaurant pickup"), D = a.at("Customer drop-off");
  const path = [offset(R, -1500, 0), R, D, offset(D, 700, 0)];
  const pts = [path[0], path[1]];
  await a.drive("Order", "o1", [...walk(pts, { ...opts, entityId: "o1", startAt: 1_000_000 }), ...walk([R, D], { ...opts, entityId: "o1", startAt: 1_300_000 })]);
  assert.deepEqual(types(a.emitted, "o1"), ["order.driver_at_restaurant", "order.driver_near_customer", "order.driver_at_customer"]);
});

test("delivery: a phone that repeats and reorders its fixes changes nothing, and two orders do not mix", { skip }, async () => {
  const a = await app("delivery");
  const R = a.at("Restaurant pickup"), D = a.at("Customer drop-off");
  const trip = (id: string, t0: number) => scramble(walk([offset(R, -1200, 0), R, D], { ...opts, entityId: id, startAt: t0 }), rng(3), 0.3, 0.1);
  await a.drive("Order", "o1", trip("o1", 1_000_000));
  await a.drive("Order", "o2", trip("o2", 2_000_000));
  for (const id of ["o1", "o2"]) assert.deepEqual(types(a.emitted, id), ["order.driver_at_restaurant", "order.driver_near_customer", "order.driver_at_customer"], id);
});

test("delivery: nothing the plan made delivers, completes or pays an order from an arrival", { skip }, async () => {
  const a = await app("delivery");
  assert.ok(a.rules.length > 0);
  for (const r of a.rules) {
    assert.equal(r.sensitive, false, JSON.stringify(r.action));
    assert.doesNotMatch(JSON.stringify(r.action), /deliver|complet|paid|payment|settle|close/i);
  }
});

test("delivery: a rule the owner adds to finish the order waits for the customer's code, then runs once", { skip }, async () => {
  const a0 = await app("delivery");
  const D = a0.at("Customer drop-off");
  const a = await app("delivery", [{ geofenceId: D.id, onEvent: "geofence.entered", action: { kind: "emit_event", event: "order.delivered" }, confirm: { event: "order.code_verified" } }]);
  const R = a.at("Restaurant pickup"), D2 = a.at("Customer drop-off");
  const rule = a.rules.find((r) => (r.action as any).event === "order.delivered")!;
  rule.geofenceId = D2.id;
  await a.drive("Order", "o1", walk([offset(R, -800, 0), R, D2], { ...opts, entityId: "o1", startAt: 1_000_000 }));
  assert.ok(!types(a.emitted).includes("order.delivered"), "arriving is not delivering");
  assert.equal(a.held.length, 1);
  a.evidence.add("o1|order.code_verified");
  const rel = { ...a.deps, heldFor: async (_t: string, id: string, ev: string) => a.held.filter((h) => h.event.entityId === id && h.rule.confirm?.event === ev), now: a.now, rules: undefined as never };
  const once = await releaseHeld("order.code_verified", "Order", "o1", rel as never);
  assert.equal(once.filter((r) => r.outcome === "done").length, 1);
  assert.equal(types(a.emitted).filter((t) => t === "order.delivered").length, 1);
  await releaseHeld("order.code_verified", "Order", "o1", rel as never);
  assert.equal(types(a.emitted).filter((t) => t === "order.delivered").length, 1, "the same crossing never acts twice");
});

test("ride: the passenger's workflow hears the driver at the pickup, and the trip is never ended by arriving", { skip }, async () => {
  const a = await app("ride");
  const P = a.at("Pickup point"), X = a.at("Drop-off point");
  await a.drive("Trip", "t1", [...walk([offset(P, -1000, 0), P], { ...opts, entityId: "t1", startAt: 1_000_000 }), ...walk([P, X], { ...opts, entityId: "t1", startAt: 1_200_000 })]);
  assert.deepEqual(types(a.emitted, "t1"), ["trip.driver_at_pickup", "trip.vehicle_at_destination"]);
  assert.ok(!types(a.emitted).some((t) => /end|complet|charge|fare|paid/i.test(t)));
});

test("fleet: a vehicle's arrival, long stay and departure are each reported once", { skip }, async () => {
  const a = await app("fleet");
  const dep = a.at("Depot");
  await a.drive("Vehicle", "v1", [
    ...walk([offset(dep, -1500, 0), dep], { ...opts, entityId: "v1", startAt: 1_000_000 }),
    ...stay(dep, 40 * 60, { entityId: "v1", everySec: 10, jitterM: 2, accuracy: 8, startAt: 1_200_000, seed: 2 }),
    ...walk([dep, offset(dep, 1500, 0)], { ...opts, entityId: "v1", startAt: 1_200_000 + 40 * 60 * 1000 + 10_000 }),
  ]);
  assert.deepEqual(types(a.emitted, "v1"), ["vehicle.arrived_at_depot", "vehicle.left_depot"]);
  // the admin is told twice for the visit, each once: the vehicle stayed a long time, and then it left the depot
  assert.equal(a.notified.length, 2, "one stay alert and one departure alert for the visit");
  assert.deepEqual(a.notified.map((n) => n.title).sort(), ["Vehicle idle at depot", "Vehicle left the depot"]);
  assert.ok(a.notified.every((n) => n.to.role === "Admin"));
});

test("attendance: reaching the site is reported, and being near it never checks anyone in", { skip }, async () => {
  const a = await app("attendance");
  const S = a.at("Work site");
  await a.drive("Staff", "p1", [...walk([offset(S, -900, 0), S], { ...opts, entityId: "p1", startAt: 1_000_000 }), ...walk([S, offset(S, 900, 0)], { ...opts, entityId: "p1", startAt: 1_300_000 })]);
  assert.deepEqual(types(a.emitted, "p1"), ["person.entered_site", "person.left_site"]);
  assert.ok(!types(a.emitted).some((t) => /check|clock|attend|present/i.test(t)));
});

test("attendance: a phone wobbling on the edge of the site does not flood the log with arrivals and departures", { skip }, async () => {
  const a = await app("attendance");
  const S = a.at("Work site");
  const edge = offset(S, 200, 0);
  await a.drive("Staff", "p2", [...walk([offset(S, -900, 0), S], { ...opts, entityId: "p2", startAt: 1_000_000 }), ...oscillate(edge, { eastM: -1, northM: 0 }, 40, { entityId: "p2", everySec: 5, accuracy: 8, startAt: 1_300_000, seed: 5, amplitudeM: 4 })]);
  assert.ok(types(a.emitted, "p2").filter((t) => t === "person.entered_site").length === 1);
  assert.ok(types(a.emitted, "p2").filter((t) => t === "person.left_site").length <= 1, "a wobble inside the leave margin is not leaving");
});

test("a plan whose zones have no coordinates makes nothing, and its rules wait for the zones to be drawn", { skip }, async () => {
  const a = await app("delivery_unlocated");
  assert.equal(a.zones.size, 0);
  assert.equal(a.rules.length, 0);
  assert.ok(a.applied.zonesToDraw.length >= 2);
  assert.ok(a.applied.rulesWaiting.length >= 1);
  await a.drive("Order", "o1", walk([{ lat: 12.9, lng: 77.6 }, { lat: 12.91, lng: 77.61 }], { ...opts, entityId: "o1" }));
  assert.equal(a.emitted.length, 0, "no zones, so no crossings and no cost");
});
