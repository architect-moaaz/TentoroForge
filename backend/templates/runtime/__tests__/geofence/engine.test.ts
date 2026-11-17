import { test } from "node:test";
import assert from "node:assert/strict";
import { evaluate, initialState, signedDistanceM, invalidShape, FenceIndex, distanceM, type Fence, type State, type Fix, type GeofenceEvent } from "../../geofence/engine.ts";
import { walk, stay, oscillate, offset, scramble, rng, type SimFix } from "../../geofence/simulate.ts";

const CENTER = { lat: 12.9784, lng: 77.6408 };
const circle = (over: Partial<Fence> = {}): Fence => ({ id: "f1", active: true, shape: { type: "circle", center: CENTER, radiusM: 200 }, rules: {}, ...over });

/** Runs fixes through the engine as a server would: one state per entity, clock = the fix's own time + 1 s. */
function run(fence: Fence, fixes: SimFix[], opts: { replay?: boolean; nowAt?: (f: SimFix) => number } = {}) {
  let state: State = initialState();
  const events: GeofenceEvent[] = [];
  const ignored: string[] = [];
  for (const f of fixes) {
    const r = evaluate(fence, state, f as Fix, opts.nowAt ? opts.nowAt(f) : f.at + 1000, { replay: opts.replay });
    state = r.state;
    events.push(...r.events);
    if (r.ignored) ignored.push(r.ignored);
  }
  return { state, events, ignored };
}
const types = (e: GeofenceEvent[]) => e.map((x) => x.type.replace("geofence.", ""));

test("distance is right: 1 degree of latitude is about 111 km", () => {
  const d = distanceM({ lat: 0, lng: 0 }, { lat: 1, lng: 0 });
  assert.ok(Math.abs(d - 111_195) < 300, String(d));
});

test("a circle: inside is negative, outside is positive, the edge is about zero", () => {
  const s = circle().shape;
  assert.ok(signedDistanceM(s, CENTER) < -190);
  assert.ok(Math.abs(signedDistanceM(s, offset(CENTER, 200, 0))) < 1.5);
  assert.ok(signedDistanceM(s, offset(CENTER, 500, 0)) > 290);
});

test("a polygon: inside, outside, and the notch of a concave shape", () => {
  // an L shape, 200 m wide arms
  const o = CENTER;
  const ring = [offset(o, 0, 0), offset(o, 400, 0), offset(o, 400, 200), offset(o, 200, 200), offset(o, 200, 400), offset(o, 0, 400)];
  const shape = { type: "polygon" as const, ring };
  assert.ok(signedDistanceM(shape, offset(o, 100, 100)) < 0);
  assert.ok(signedDistanceM(shape, offset(o, 300, 100)) < 0);
  assert.ok(signedDistanceM(shape, offset(o, 100, 300)) < 0);
  assert.ok(signedDistanceM(shape, offset(o, 300, 300)) > 0, "the notch is outside");
  assert.ok(Math.abs(signedDistanceM(shape, offset(o, 300, 300)) - 100) < 3, "and 100 m from the nearest edge");
  assert.ok(signedDistanceM(shape, offset(o, -50, 100)) > 40);
});

test("shapes that are not fences are refused with a reason", () => {
  assert.match(invalidShape({ type: "circle", center: CENTER, radiusM: 2 })!, /at least 5/);
  assert.match(invalidShape({ type: "circle", center: CENTER, radiusM: 200_000 })!, /at most 100 km/);
  assert.match(invalidShape({ type: "circle", center: { lat: 99, lng: 0 }, radiusM: 50 })!, /not a place/);
  assert.match(invalidShape({ type: "polygon", ring: [CENTER, offset(CENTER, 10, 0)] })!, /3 corners/);
  assert.match(invalidShape({ type: "polygon", ring: [CENTER, offset(CENTER, 100, 0), offset(CENTER, 200, 0)] })!, /no area/);
  assert.equal(invalidShape(circle().shape), null);
});

test("a drive through raises one entered and one exited, in that order", () => {
  const path = [offset(CENTER, -600, 0), offset(CENTER, 600, 0)];
  const { events } = run(circle(), walk(path, { jitterM: 3, accuracy: 10 }));
  assert.deepEqual(types(events), ["entered", "exited"]);
});

test("staying inside raises no second entered", () => {
  const { events } = run(circle(), [...walk([offset(CENTER, -300, 0), CENTER]), ...stay(CENTER, 300, { startAt: 1_700_000_300_000 })]);
  assert.deepEqual(types(events), ["entered"]);
});

test("a phone parked on the edge does not flap", () => {
  const edge = offset(CENTER, 200, 0);
  const fixes = oscillate(edge, { eastM: -1, northM: 0 }, 60, { amplitudeM: 6, accuracy: 8 });
  const { events } = run(circle(), fixes);
  assert.ok(events.length <= 1, `got ${types(events)}`);
});

test("a bad fix of a long way off does not leave the fence when the accuracy is large", () => {
  const f = circle();
  const inside = walk([CENTER, offset(CENTER, 5, 0)], { everySec: 5 });
  const r = run(f, inside);
  assert.equal(r.state.phase, "inside");
  // a 90 m accurate fix 220 m out is outside by 20 m: not outside by more than margin + accuracy, so it keeps the state
  const next = { entityId: "e1", entityType: "driver", ...offset(CENTER, 220, 0), at: inside[inside.length - 1].at + 5000, accuracy: 90 };
  const r2 = evaluate(f, r.state, next, next.at + 500);
  assert.equal(r2.state.phase, "inside");
  assert.equal(r2.events.length, 0);
});

test("a fix less accurate than allowed is ignored", () => {
  const r = evaluate(circle(), initialState(), { entityId: "e1", entityType: "driver", ...CENTER, at: 1000, accuracy: 500 }, 2000);
  assert.equal(r.ignored, "inaccurate");
  assert.equal(r.state.lastAt, 0);
});

test("invalid coordinates are ignored and never raise a crossing", () => {
  const f = circle();
  for (const bad of [{ lat: NaN, lng: 0 }, { lat: 91, lng: 0 }, { lat: 0, lng: 181 }, { lat: Infinity, lng: 0 }, { lat: null as any, lng: 0 }]) {
    const r = evaluate(f, initialState(), { entityId: "e1", entityType: "driver", ...bad, at: 1000 }, 2000);
    assert.equal(r.ignored, "invalid");
    assert.equal(r.events.length, 0);
  }
});

test("a fix from the future, and a stale one, are ignored — but a stale one counts after being offline", () => {
  const f = circle();
  const fix = { entityId: "e1", entityType: "driver", ...CENTER, at: 1_000_000 };
  assert.equal(evaluate(f, initialState(), fix, 1_000_000 - 400_000).ignored, "future");
  assert.equal(evaluate(f, initialState(), fix, 1_000_000 + 400_000).ignored, "stale");
  assert.equal(evaluate(f, initialState(), fix, 1_000_000 + 400_000, { replay: true }).ignored, undefined);
});

test("an inactive fence raises nothing and keeps no state", () => {
  const f = circle({ active: false });
  const r = run(f, walk([offset(CENTER, -300, 0), CENTER]));
  assert.equal(r.events.length, 0);
  assert.equal(r.state.lastAt, 0);
});

test("the same fix twice, and an older one after a newer one, change nothing", () => {
  const f = circle();
  const fixes = walk([offset(CENTER, -300, 0), offset(CENTER, 300, 0)], { jitterM: 2 });
  const clean = run(f, fixes);
  const twice = run(f, scramble(fixes, rng(9), 0.5, 0), { replay: true });
  assert.deepEqual(types(twice.events), types(clean.events), "repeats change nothing");
  assert.ok(twice.ignored.includes("duplicate"));
  // late arrivals are dropped as old, so a crossing may be seen later, but never twice and never out of order
  const late = run(f, scramble(fixes, rng(9), 0.3, 0.3), { replay: true });
  assert.ok(late.ignored.includes("old"));
  late.events.forEach((e, i) => assert.equal(e.type, i % 2 === 0 ? "geofence.entered" : "geofence.exited"));
});

test("the same crossing always has the same id; a second visit has a different one", () => {
  const f = circle();
  const trip = (startAt: number) => walk([offset(CENTER, -400, 0), offset(CENTER, 400, 0)], { startAt });
  const a = run(f, trip(1_700_000_000_000));
  const b = run(f, trip(1_700_000_000_000));
  assert.deepEqual(a.events.map((e) => e.id), b.events.map((e) => e.id));
  // there and back again: two visits, four distinct ids
  const there = trip(1_700_000_000_000);
  const back = walk([offset(CENTER, 400, 0), offset(CENTER, -400, 0)], { startAt: there[there.length - 1].at + 5000 });
  const both = run(f, [...there, ...back]);
  assert.equal(both.events.length, 4);
  assert.equal(new Set(both.events.map((e) => e.id)).size, 4);
});

test("dwell is raised once per visit, after the time has passed", () => {
  const f = circle({ rules: { dwellSec: 120 } });
  const { events } = run(f, [...walk([offset(CENTER, -300, 0), CENTER]), ...stay(CENTER, 600, { startAt: 1_700_000_100_000 })]);
  assert.deepEqual(types(events), ["entered", "dwell"]);
  const dwell = events[1];
  assert.ok((dwell.metadata.dwellMs as number) >= 120_000);
});

test("no dwell if they leave first", () => {
  const f = circle({ rules: { dwellSec: 600 } });
  const { events } = run(f, walk([offset(CENTER, -400, 0), offset(CENTER, 400, 0)], { speedMps: 10 }));
  assert.deepEqual(types(events), ["entered", "exited"]);
});

test("time out of touch is not time inside: a long gap restarts the dwell timer", () => {
  const f = circle({ rules: { dwellSec: 120, maxGapMs: 300_000 } });
  const t0 = 1_700_000_000_000;
  const at = (s: number) => ({ entityId: "e1", entityType: "driver", ...CENTER, at: t0 + s * 1000, accuracy: 5 });
  // inside at 0 and 5, silent for an hour, back at 3605: 3 s after the gap
  const fixes = [at(0), at(5), at(3605), at(3610)];
  const { events } = run(f, fixes, { replay: true });
  assert.deepEqual(types(events), ["entered"], "an hour of silence must not count as dwell");
});

test("approaching is raised once from outside, and again only after going away and returning", () => {
  const f = circle({ rules: { approachM: 500 } });
  const out1 = walk([offset(CENTER, -1500, 0), offset(CENTER, -400, 0)], { everySec: 5 });
  const r1 = run(f, out1);
  assert.deepEqual(types(r1.events), ["approaching"]);
  const away = walk([offset(CENTER, -400, 0), offset(CENTER, -1500, 0), offset(CENTER, -400, 0)], { startAt: out1[out1.length - 1].at + 5000 });
  const r2 = run(f, [...out1, ...away]);
  assert.deepEqual(types(r2.events), ["approaching", "approaching"]);
});

test("coming in raises approaching then entered; leaving raises exited", () => {
  const f = circle({ rules: { approachM: 500 } });
  const { events } = run(f, walk([offset(CENTER, -1500, 0), offset(CENTER, 600, 0)]));
  assert.deepEqual(types(events), ["approaching", "entered", "exited"]);
});

test("enter and exit can be switched off one by one", () => {
  const f = circle({ rules: { exit: false } });
  const { events } = run(f, walk([offset(CENTER, -400, 0), offset(CENTER, 400, 0)]));
  assert.deepEqual(types(events), ["entered"]);
});

test("a polygon fence raises the same events", () => {
  const ring = [offset(CENTER, -150, -150), offset(CENTER, 150, -150), offset(CENTER, 150, 150), offset(CENTER, -150, 150)];
  const f: Fence = { id: "poly", active: true, shape: { type: "polygon", ring }, rules: {} };
  const { events } = run(f, walk([offset(CENTER, -500, 0), offset(CENTER, 500, 0)], { jitterM: 2, accuracy: 6 }));
  assert.deepEqual(types(events), ["entered", "exited"]);
});

test("events carry what a business rule needs", () => {
  const { events } = run(circle(), walk([offset(CENTER, -400, 0), CENTER], { entityId: "driver-7", entityType: "driver" }));
  const e = events[0];
  assert.equal(e.type, "geofence.entered");
  assert.equal(e.geofenceId, "f1");
  assert.equal(e.entityId, "driver-7");
  assert.equal(e.entityType, "driver");
  assert.ok(e.occurredAt > 0 && e.detectedAt >= e.occurredAt);
  assert.ok(typeof e.lat === "number" && typeof e.lng === "number");
});

test("the engine never changes the state or fix it was given", () => {
  const f = circle();
  const s = initialState();
  const before = JSON.stringify(s);
  const fix = { entityId: "e1", entityType: "driver", ...CENTER, at: 5000 };
  const fixBefore = JSON.stringify(fix);
  evaluate(f, s, fix, 6000);
  assert.equal(JSON.stringify(s), before);
  assert.equal(JSON.stringify(fix), fixBefore);
});

test("the index finds the few fences near a point out of thousands, and agrees with checking them all", () => {
  const fences: Fence[] = [];
  const r = rng(3);
  for (let i = 0; i < 5000; i++) {
    const c = { lat: 12.8 + r() * 0.4, lng: 77.4 + r() * 0.4 };
    fences.push({ id: `z${i}`, active: true, shape: { type: "circle", center: c, radiusM: 100 + r() * 400 }, rules: { approachM: 200 } });
  }
  fences.push({ id: "huge", active: true, shape: { type: "circle", center: CENTER, radiusM: 90_000 }, rules: {} });
  const idx = new FenceIndex(fences);
  assert.equal(idx.size, 5001);
  for (let k = 0; k < 200; k++) {
    const p = { lat: 12.8 + r() * 0.4, lng: 77.4 + r() * 0.4 };
    const viaIndex = new Set(idx.near(p.lat, p.lng).filter((f) => signedDistanceM(f.shape, p) <= 0).map((f) => f.id));
    const all = new Set(fences.filter((f) => signedDistanceM(f.shape, p) <= 0).map((f) => f.id));
    assert.deepEqual([...viaIndex].sort(), [...all].sort());
    assert.ok(idx.near(p.lat, p.lng).length < 60, "a lookup should not return a large part of the 5000");
  }
  idx.remove("huge");
  assert.equal(idx.size, 5000);
});

test("a fix is checked against thousands of fences quickly", () => {
  const fences: Fence[] = [];
  const r = rng(5);
  for (let i = 0; i < 10_000; i++) fences.push({ id: `z${i}`, active: true, shape: { type: "circle", center: { lat: 12.8 + r() * 0.4, lng: 77.4 + r() * 0.4 }, radiusM: 300 }, rules: {} });
  const idx = new FenceIndex(fences);
  const t = Date.now();
  let n = 0;
  for (let i = 0; i < 20_000; i++) n += idx.near(12.8 + r() * 0.4, 77.4 + r() * 0.4).length;
  const ms = Date.now() - t;
  assert.ok(ms < 1500, `20 000 lookups took ${ms} ms (${n} candidates)`);
});

test("a hundred drivers through twenty fences end with the right counts", () => {
  const fences: Fence[] = Array.from({ length: 20 }, (_, i) => ({ id: `z${i}`, active: true, shape: { type: "circle" as const, center: offset(CENTER, i * 1500, 0), radiusM: 250 }, rules: {} }));
  const idx = new FenceIndex(fences);
  const states = new Map<string, State>();
  let entered = 0, exited = 0;
  for (let d = 0; d < 100; d++) {
    const fixes = walk([offset(CENTER, -500, d), offset(CENTER, 20 * 1500, d)], { entityId: `d${d}`, jitterM: 4, accuracy: 10, speedMps: 20, seed: d + 1 });
    const inside = new Set<string>();
    for (const f of fixes) {
      for (const fence of idx.candidates(f.lat, f.lng, inside)) {
        const key = `${fence.id}|${f.entityId}`;
        const r = evaluate(fence, states.get(key) ?? initialState(), f, f.at + 1000);
        states.set(key, r.state);
        if (r.state.phase === "inside") inside.add(fence.id); else inside.delete(fence.id);
        for (const e of r.events) e.type === "geofence.entered" ? entered++ : e.type === "geofence.exited" && exited++;
      }
    }
  }
  assert.equal(entered, 100 * 20);
  assert.equal(exited, 100 * 20);
});
