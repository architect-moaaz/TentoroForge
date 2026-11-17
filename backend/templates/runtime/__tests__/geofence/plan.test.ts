import { test } from "node:test";
import assert from "node:assert/strict";
// run with: node --experimental-transform-types --import ./_register.mjs (plan.ts imports ./rules, which imports ../feel-lite)
const { applyPlan } = await import("../../geofence/plan.ts");
import type { PlanIO, GeofencePlan } from "../../geofence/plan.ts";

function io(seed: { zones?: Record<string, string>; rules?: string[] } = {}) {
  const zones = new Map(Object.entries(seed.zones ?? {}).map(([k, v]) => [k.toLowerCase(), v]));
  const rules: { geofenceId: string | null; onEvent: string; action: any; sensitive: boolean }[] = [];
  const key = (z: string | null, e: string, a: unknown) => `${z}|${e}|${JSON.stringify(a)}`;
  const kept = new Set(seed.rules ?? []);
  let n = 0;
  const made: string[] = [];
  const i: PlanIO = {
    zoneId: async (name) => zones.get(name.toLowerCase()) ?? null,
    addZone: async (z) => { const id = `z${++n}`; zones.set(z.name.toLowerCase(), id); made.push(z.name); return id; },
    hasRule: async (z, e, a) => kept.has(key(z, e, a)) || rules.some((r) => key(r.geofenceId, r.onEvent, r.action) === key(z, e, a)),
    addRule: async (r) => { rules.push(r); },
  };
  return { i, rules, made, key };
}

const plan = (over: Partial<GeofencePlan> = {}): GeofencePlan => ({
  zones: [
    { name: "Depot", radiusM: 250, lat: 12.97, lng: 77.59, needsDrawing: false },
    { name: "Customer drop-off", radiusM: 150, needsDrawing: true },
  ],
  rules: [
    { zone: "Depot", onEvent: "geofence.entered", action: { kind: "emit_event", event: "vehicle.arrived_at_depot" } },
    { zone: "Customer drop-off", onEvent: "geofence.entered", action: { kind: "emit_event", event: "order.driver_at_customer" } },
  ],
  ...over,
});

test("a zone with coordinates is made; one without is left for the owner to draw", async () => {
  const t = io();
  const r = await applyPlan(plan(), t.i);
  assert.deepEqual(r.zonesAdded, ["Depot"]);
  assert.deepEqual(r.zonesToDraw, ["Customer drop-off"]);
});

test("a rule is made only beside its own zone, never left loose", async () => {
  const t = io();
  const r = await applyPlan(plan(), t.i);
  assert.equal(r.rulesAdded, 1);
  assert.equal(t.rules[0].geofenceId, "z1");
  assert.deepEqual(r.rulesWaiting, [{ zone: "Customer drop-off", onEvent: "geofence.entered" }]);
});

test("running it twice adds nothing twice", async () => {
  const t = io();
  await applyPlan(plan(), t.i);
  const again = await applyPlan(plan(), t.i);
  assert.equal(again.zonesAdded.length, 0);
  assert.deepEqual(again.zonesKept, ["Depot"]);
  assert.equal(again.rulesAdded, 0);
  assert.equal(again.rulesKept, 1);
  assert.equal(t.rules.length, 1);
  assert.equal(t.made.length, 1);
});

test("a zone that is already there is left as it is, and its rules are made", async () => {
  const t = io({ zones: { "customer drop-off": "zx" } });
  const r = await applyPlan(plan(), t.i);
  assert.ok(r.zonesKept.includes("Customer drop-off"));
  assert.equal(r.zonesToDraw.length, 0);
  assert.equal(r.rulesAdded, 2);
  assert.ok(t.rules.some((x) => x.geofenceId === "zx"));
});

test("a rule that would fail on the rules screen is refused, not stored", async () => {
  const t = io();
  const r = await applyPlan(plan({ rules: [
    { zone: "Depot", onEvent: "geofence.sneezed", action: { kind: "emit_event", event: "x.y" } },
    { zone: "Depot", onEvent: "geofence.entered", action: { kind: "notify", title: "" , role: "Admin" } },
    { zone: "Depot", onEvent: "geofence.entered", action: { kind: "launch_missiles" } },
  ] }), t.i);
  assert.equal(r.rulesAdded, 0);
  assert.equal(r.rulesRefused.length, 3);
  assert.equal(t.rules.length, 0);
});

test("a rule that finishes a job is stored as sensitive, so it waits for a confirmation", async () => {
  const t = io();
  await applyPlan(plan({ rules: [{ zone: "Depot", onEvent: "geofence.entered", action: { kind: "emit_event", event: "order.delivered" } }] }), t.i);
  assert.equal(t.rules[0].sensitive, true);
});

test("coordinates that cannot be real, or a zone far too small or large, are not made", async () => {
  const t = io();
  const r = await applyPlan({ zones: [
    { name: "Moon", radiusM: 100, lat: 120, lng: 10, needsDrawing: false },
    { name: "Dot", radiusM: 1, lat: 10, lng: 10, needsDrawing: false },
    { name: "World", radiusM: 900000, lat: 10, lng: 10, needsDrawing: false },
  ], rules: [] }, t.i);
  assert.equal(r.zonesAdded.length, 0);
  assert.equal(r.zonesToDraw.length, 3);
});

test("no plan, an empty plan or a damaged one does nothing and does not throw", async () => {
  const t = io();
  for (const p of [null, undefined, {}, { zones: [null, 5, { radiusM: 3 }], rules: [null, { zone: "x" }] }] as any[]) {
    const r = await applyPlan(p, t.i);
    assert.equal(r.zonesAdded.length + r.rulesAdded, 0);
  }
});
