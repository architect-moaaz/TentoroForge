import { test } from "node:test";
import assert from "node:assert/strict";
import type { GeofenceEvent } from "../../geofence/engine.ts";
// run with: node --experimental-strip-types --import ./_register.mjs (rules.ts imports ../feel-lite without an extension, as it ships)
const { runRules, matching, isSensitive, invalidRule, fill, isManagerRole, cleanFenceRules } = await import("../../geofence/rules.ts");
import type { Rule, RuleDeps } from "../../geofence/rules.ts";

const event = (over: Partial<GeofenceEvent> = {}): GeofenceEvent => ({
  id: "z1:o1:geofence.entered:1", type: "geofence.entered", geofenceId: "z1", entityId: "o1", entityType: "Order",
  lat: 1, lng: 2, occurredAt: 1000, detectedAt: 1100, metadata: { visit: 1, dwellMs: 90_000 }, ...over,
});
const rule = (over: Partial<Rule> = {}): Rule => ({ id: "r1", geofenceId: null, onEvent: "geofence.entered", action: { kind: "emit_event", event: "order.driver_arrived" }, ...over });

function deps(rules: Rule[], evidence: string[] = [], over: Partial<RuleDeps> = {}) {
  const emitted: { type: string; payload: Record<string, unknown>; dedupeKey: string }[] = [];
  const told: { to: unknown; m: any }[] = [];
  const claimed = new Set<string>();
  const asked: { type: string; since: number | null }[] = [];
  const d: RuleDeps = {
    rules,
    claim: async (k) => (claimed.has(k) ? false : (claimed.add(k), true)),
    emit: async (type, o) => { emitted.push({ type, payload: o.payload, dedupeKey: o.dedupeKey }); },
    notify: async (to, m) => { told.push({ to, m }); },
    hasEvidence: async (_t, _i, type, since) => { asked.push({ type, since }); return evidence.includes(type); },
    now: () => 10_000_000,
    ...over,
  };
  return { d, emitted, told, asked };
}

test("a crossing runs the rule that names it, and says where it came from", async () => {
  const { d, emitted } = deps([rule()]);
  const r = await runRules(event(), d);
  assert.deepEqual(r.map((x) => x.outcome), ["done"]);
  assert.equal(emitted[0].type, "order.driver_arrived");
  assert.equal(emitted[0].payload.entityId, "o1");
  assert.equal(emitted[0].payload.geofenceEvent, "z1:o1:geofence.entered:1");
});

test("a rule for another event, or another zone, does not run", async () => {
  const { d, emitted } = deps([rule({ onEvent: "geofence.exited" }), rule({ id: "r2", geofenceId: "other" }), rule({ id: "r3", active: false })]);
  assert.deepEqual(await runRules(event(), d), []);
  assert.equal(emitted.length, 0);
});

test("a rule for one zone runs there; a rule for no zone runs everywhere", () => {
  assert.equal(matching(event(), [rule({ geofenceId: "z1" })]).length, 1);
  assert.equal(matching(event({ geofenceId: "z9" }), [rule({ geofenceId: null })]).length, 1);
});

test("a condition decides: true runs, false does not, a broken one does not", () => {
  assert.equal(matching(event(), [rule({ condition: "metadata.dwellMs >= 60000" })]).length, 1);
  assert.equal(matching(event(), [rule({ condition: "metadata.dwellMs >= 600000" })]).length, 0);
  assert.equal(matching(event(), [rule({ condition: "entityType = \"Order\"" })]).length, 1);
  assert.equal(matching(event(), [rule({ condition: "this is ((( not valid" })]).length, 0);
});

test("a notification is filled from the crossing", async () => {
  const { d, told } = deps([rule({ action: { kind: "notify", role: "admin", title: "{{entityType}} {{entityId}} at {{zone}}", body: "stayed {{metadata.dwellMs}} ms" } })]);
  await runRules(event(), d);
  assert.equal(told[0].m.title, "Order o1 at z1");
  assert.equal(told[0].m.body, "stayed 90000 ms");
  assert.deepEqual(told[0].to, { role: "admin", userIds: undefined });
});

test("fill: paths, missing names", () => {
  assert.equal(fill("{{event.entityId}}/{{metadata.visit}}/{{nope.deeper}}/{{zone}}/{{nope}}", event()), "o1/1//z1/");
});

// ------------------------------------------------------------------------------------------ the guard

test("what counts as sensitive: money, finishing, attendance — by name, or by the rule saying so", () => {
  for (const name of ["order.delivered", "payment.captured", "invoice.paid", "refund.issued", "shift.checked_in", "attendance.marked", "job.completed", "payout.sent", "order.closed", "leave.approved"]) {
    assert.equal(isSensitive(rule({ action: { kind: "emit_event", event: name } })), true, name);
  }
  for (const name of ["order.driver_arrived", "driver.nearby", "restaurant.driver_waiting", "zone.left"]) {
    assert.equal(isSensitive(rule({ action: { kind: "emit_event", event: name } })), false, name);
  }
  assert.equal(isSensitive(rule({ sensitive: true, action: { kind: "notify", title: "x", role: "admin" } })), true);
});

test("a sensitive rule with no confirmation never runs on a crossing alone", async () => {
  const { d, emitted } = deps([rule({ action: { kind: "emit_event", event: "order.delivered" } })]);
  const r = await runRules(event(), d);
  assert.equal(r[0].outcome, "held");
  assert.match(r[0].reason!, /not GPS/);
  assert.equal(emitted.length, 0);
});

test("a sensitive rule with a confirmation waits until that event exists", async () => {
  const sensitive = rule({ action: { kind: "emit_event", event: "order.delivered" }, confirm: { event: "order.code_verified" } });
  const waiting = deps([sensitive]);
  const r1 = await runRules(event(), waiting.d);
  assert.equal(r1[0].outcome, "held");
  assert.match(r1[0].reason!, /order\.code_verified/);
  assert.equal(waiting.emitted.length, 0);

  const confirmed = deps([sensitive], ["order.code_verified"]);
  const r2 = await runRules(event(), confirmed.d);
  assert.equal(r2[0].outcome, "done");
  assert.equal(confirmed.emitted[0].type, "order.delivered");
});

test("a confirmation is asked for the same entity, and only as recent as the rule allows", async () => {
  const { d, asked } = deps([rule({ action: { kind: "emit_event", event: "attendance.marked" }, confirm: { event: "manager.confirmed", withinSec: 300 } })]);
  await runRules(event(), d);
  assert.equal(asked[0].type, "manager.confirmed");
  assert.equal(asked[0].since, 10_000_000 - 300_000);
});

test("a held rule claims nothing, so the crossing can still act once the confirmation is there", async () => {
  const sensitive = rule({ action: { kind: "emit_event", event: "order.delivered" }, confirm: { event: "order.code_verified" } });
  const evidence: string[] = [];
  const { d, emitted } = deps([sensitive], evidence);
  await runRules(event(), d);
  assert.equal(emitted.length, 0);
  evidence.push("order.code_verified");
  const again = await runRules(event(), d);
  assert.equal(again[0].outcome, "done");
  assert.equal(emitted.length, 1);
});

test("a sensitive notify is held the same way", async () => {
  const { d, told } = deps([rule({ sensitive: true, action: { kind: "notify", title: "Paid out", role: "admin" } })]);
  assert.equal((await runRules(event(), d))[0].outcome, "held");
  assert.equal(told.length, 0);
});

// ------------------------------------------------------------------------------------------ safety of running

test("the same crossing acts once even if it is announced twice", async () => {
  const { d, emitted } = deps([rule()]);
  const a = await runRules(event(), d);
  const b = await runRules(event(), d);
  assert.deepEqual([a[0].outcome, b[0].outcome], ["done", "duplicate"]);
  assert.equal(emitted.length, 1);
});

test("a second visit is a new crossing and acts again", async () => {
  const { d, emitted } = deps([rule()]);
  await runRules(event(), d);
  await runRules(event({ id: "z1:o1:geofence.entered:2" }), d);
  assert.equal(emitted.length, 2);
});

test("one rule failing does not stop the next", async () => {
  const { d, emitted } = deps([rule({ id: "bad", action: { kind: "emit_event", event: "a.b" } }), rule({ id: "good", action: { kind: "emit_event", event: "c.d" } })], [], {
    emit: async (type, o) => { if (type === "a.b") throw new Error("bus down"); emitted2.push(type); },
  });
  const emitted2: string[] = [];
  const r = await runRules(event(), d);
  assert.deepEqual(r.map((x) => `${x.ruleId}:${x.outcome}`), ["bad:failed", "good:done"]);
  assert.deepEqual(emitted2, ["c.d"]);
  assert.equal(emitted.length, 0);
});

test("an action it does not know is skipped, not run", async () => {
  const { d } = deps([rule({ action: { kind: "launch_missiles" } as any })]);
  assert.equal((await runRules(event(), d))[0].outcome, "skipped");
});

test("rules are checked when saved", () => {
  assert.equal(invalidRule(rule()), null);
  assert.match(invalidRule({ onEvent: "order.created", action: { kind: "emit_event", event: "x.y" } })!, /entered, exited/);
  assert.match(invalidRule({ onEvent: "geofence.entered" })!, /needs an action/);
  assert.match(invalidRule({ onEvent: "geofence.entered", action: { kind: "emit_event", event: " " } })!, /name/);
  assert.match(invalidRule({ onEvent: "geofence.entered", action: { kind: "notify", title: "Hi" } })!, /role or people/);
  assert.match(invalidRule({ onEvent: "geofence.entered", action: { kind: "emit_event", event: "a.b" }, condition: "((( nope" })!, /condition/);
});

// ------------------------------------------------------------------------------------------ releasing what was held

const { releaseHeld } = await import("../../geofence/rules.ts");
import type { Held } from "../../geofence/rules.ts";

const delivered = (): Rule => rule({ id: "deliver", action: { kind: "emit_event", event: "order.delivered" }, confirm: { event: "order.code_verified" } });

function releasing(held: Held[], evidence: string[], nowMs = 10_000_000) {
  const base = deps([], evidence, { now: () => nowMs });
  return { ...base, rd: { ...base.d, heldFor: async () => held } };
}

test("when the confirmation arrives, what was held runs, once", async () => {
  const t = releasing([{ rule: delivered(), event: event(), heldAt: 9_900_000 }], ["order.code_verified"]);
  const first = await releaseHeld("order.code_verified", "Order", "o1", t.rd);
  assert.deepEqual(first.map((r) => r.outcome), ["done"]);
  assert.equal(t.emitted[0].type, "order.delivered");
  const again = await releaseHeld("order.code_verified", "Order", "o1", t.rd);
  assert.deepEqual(again.map((r) => r.outcome), ["duplicate"]);
  assert.equal(t.emitted.length, 1);
});

test("the guard is checked again at release: no evidence, still held, nothing runs", async () => {
  const t = releasing([{ rule: delivered(), event: event(), heldAt: 9_900_000 }], []);
  const r = await releaseHeld("order.code_verified", "Order", "o1", t.rd);
  assert.equal(r[0].outcome, "held");
  assert.equal(t.emitted.length, 0);
});

test("a hold that is too old is let go, not run", async () => {
  const t = releasing([{ rule: delivered(), event: event(), heldAt: 10_000_000 - 7 * 3600 * 1000 }], ["order.code_verified"]);
  const r = await releaseHeld("order.code_verified", "Order", "o1", t.rd);
  assert.equal(r[0].outcome, "skipped");
  assert.equal(t.emitted.length, 0);
});

test("the same hold listed twice runs once", async () => {
  const h: Held = { rule: delivered(), event: event(), heldAt: 9_900_000 };
  const t = releasing([h, h], ["order.code_verified"]);
  const r = await releaseHeld("order.code_verified", "Order", "o1", t.rd);
  assert.equal(r.length, 1);
  assert.equal(t.emitted.length, 1);
});

test("two crossings held for the same confirmation both run", async () => {
  const t = releasing([
    { rule: delivered(), event: event(), heldAt: 9_900_000 },
    { rule: delivered(), event: event({ id: "z1:o1:geofence.entered:2" }), heldAt: 9_950_000 },
  ], ["order.code_verified"]);
  const r = await releaseHeld("order.code_verified", "Order", "o1", t.rd);
  assert.deepEqual(r.map((x) => x.outcome), ["done", "done"]);
});

// ------------------------------------------------------------------------------------------ who may change zones, what may be set

test("a role is matched without regard to case: the app's \"Admin\" is the setting's \"admin\"", () => {
  assert.equal(isManagerRole("Admin", ["admin"]), true);
  assert.equal(isManagerRole("ADMIN", ["admin"]), true);
  assert.equal(isManagerRole("Restaurant Manager", ["admin", " restaurant manager "]), true);
  assert.equal(isManagerRole("Customer", ["admin"]), false);
  assert.equal(isManagerRole("", ["admin"]), false);
  assert.equal(isManagerRole(undefined, [""]), false);
});

test("zone settings are kept within sane ranges, and unknown ones are dropped", () => {
  assert.deepEqual(cleanFenceRules({ dwellSec: 120, minFixes: 3, bogus: 1, exit: false }), { rules: { dwellSec: 120, minFixes: 3, exit: false } });
  assert.deepEqual(cleanFenceRules({ dwellSec: "", approachM: null }), { rules: {} });
  assert.match(cleanFenceRules({ minFixes: 0 }).problem!, /minFixes/);
  assert.match(cleanFenceRules({ minFixes: 50 }).problem!, /minFixes/);
  assert.match(cleanFenceRules({ hysteresisM: -5 }).problem!, /hysteresisM/);
  assert.match(cleanFenceRules({ maxAccuracyM: "wide" }).problem!, /maxAccuracyM/);
  assert.match(cleanFenceRules({ staleMs: 5 }).problem!, /staleMs/);
});
