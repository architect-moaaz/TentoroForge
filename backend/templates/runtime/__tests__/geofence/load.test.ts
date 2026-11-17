import { test } from "node:test";
import assert from "node:assert/strict";
import { walk, offset } from "../../geofence/simulate.ts";
import type { Fence, GeofenceEvent, State } from "../../geofence/engine.ts";
import type { GeofenceStore, Subject } from "../../geofence/service.ts";

// run with: node --experimental-transform-types --import ./_register.mjs
const { makeGeofenceService } = await import("../../geofence/service.ts");

const ORIGIN = { lat: 12.9, lng: 77.5 };

test("a busy city: 600 phones drive through 1500 zones, each crossing is found once, and it is fast", async () => {
  const fences: Fence[] = [];
  for (let i = 0; i < 1500; i++) {
    const c = offset(ORIGIN, (i % 50) * 800, Math.floor(i / 50) * 800);
    fences.push({ id: `z${i}`, active: true, shape: { type: "circle", center: c, radiusM: 120 }, rules: {} });
  }
  const states = new Map<string, State>();
  const recorded = new Map<string, GeofenceEvent>();
  let stateReads = 0;
  const key = (w: Subject, f: string) => `${f}|${w.entityType}|${w.entityId}`;
  const store: GeofenceStore = {
    async loadFences() { return fences; },
    async loadAssignments() { return new Map(); },
    async insideFenceIds(w) { stateReads++; return [...states].filter(([k, s]) => k.endsWith(`|${w.entityType}|${w.entityId}`) && s.phase === "inside").map(([k]) => k.split("|")[0]); },
    async loadStates(w, ids) { stateReads++; const m = new Map<string, State>(); for (const i of ids) { const s = states.get(key(w, i)); if (s) m.set(i, structuredClone(s)); } return m; },
    async saveStates(w, m) { for (const [i, s] of m) states.set(key(w, i), structuredClone(s)); },
    async recordEvents(es) { const fresh: GeofenceEvent[] = []; for (const e of es) if (!recorded.has(e.id)) { recorded.set(e.id, e); fresh.push(e); } return fresh; },
  };
  let clock = 0;
  const svc = makeGeofenceService({ store, now: () => clock, fenceTtlMs: 3_600_000 });

  const PHONES = 600;
  const trips = Array.from({ length: PHONES }, (_, p) => {
    const zone = fences[(p * 2) % fences.length].shape as { center: { lat: number; lng: number } };
    return walk([offset(zone.center, -700, 0), offset(zone.center, 700, 0)], { entityType: "Driver", entityId: `d${p}`, speedMps: 12, everySec: 5, jitterM: 2, accuracy: 8, startAt: 1_000_000 + p });
  });
  const fixes = trips.flat().sort((a, b) => a.at - b.at);
  const t0 = performance.now();
  for (const f of fixes) { clock = f.at + 300; await svc.ingest({ entityType: f.entityType, entityId: f.entityId }, { lat: f.lat, lng: f.lng, at: f.at, accuracy: f.accuracy }); }
  const ms = performance.now() - t0;

  const entered = [...recorded.values()].filter((e) => e.type === "geofence.entered");
  const exited = [...recorded.values()].filter((e) => e.type === "geofence.exited");
  assert.equal(entered.length, PHONES, "every phone entered its zone exactly once");
  assert.equal(exited.length, PHONES, "and left it exactly once");
  assert.equal(new Set(entered.map((e) => e.entityId)).size, PHONES);
  const perFix = ms / fixes.length;
  console.log(`# ${fixes.length} fixes against ${fences.length} zones in ${ms.toFixed(0)} ms (${perFix.toFixed(3)} ms a fix)`);
  assert.ok(perFix < 2, `a fix took ${perFix.toFixed(2)} ms on average (limit 2 ms, memory store)`);
});
