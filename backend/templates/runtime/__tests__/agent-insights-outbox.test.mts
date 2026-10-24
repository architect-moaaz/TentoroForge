/**
 * The outbox: forge_agent_turns as the place every turn waits until the platform has it. The SHIPPED turns-store.ts,
 * insights-outbox.ts and handoff-store.ts, run against an in-memory stand-in for the database (__tests__/_fake-db.mts)
 * and a fake network.
 *
 * What is pinned: a recorded turn is written first and then sent, and its row is marked sent only on a 202; a turn that
 * could not be sent is found and sent by the cron tick, OLDEST FIRST, in batches of 500, at most N batches a tick,
 * again with the same event id (so a repeat is harmless); a platform that is down stops the tick without losing or
 * closing anything; rows sent more than a week ago are deleted in small batches, and nothing is deleted or sent when
 * the app is not connected; a rating puts its row back in the outbox and is sent as a rating for the same turn; a
 * hand-off's status changes are sent, and offered again by the tick until the platform has them; an app whose database
 * lacks the newest columns still records its turns and still rates them.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { createFakeDb, fakeDbStubs } from "./_fake-db.mts";
import { validateBatch } from "./_insights-contract.mts";

const fake = createFakeDb();
(globalThis as any).__fake = fake;
installHarness({ stubs: fakeDbStubs() });

const { turnStore, rateTurn } = await import("../agents/turns-store.ts");
const Outbox = await import("../agents/insights-outbox.ts");
const { handoffStore, changeHandoff } = await import("../agents/handoff-store.ts");

const ENV = { FORGE_INSIGHTS_URL: "https://platform.test/ingest", FORGE_INSIGHTS_KEY: "fik_" + "z".repeat(40), FORGE_INSIGHTS_USER_SALT: "outbox-salt-0123456789" };
// Each scenario gets its own key. A shipper left over from an earlier scenario may still fire a retry timer; the fake
// network turns it away (its key is not the current one), so it cannot leak into a later scenario's numbers.
let epoch = 0;
let currentKey = "";
const DAY = 86_400_000;

// ── the fake network and a fresh shipper for each scenario ──────────────────

const calls: Array<{ body: any; bytes: number }> = [];
let platform: (n: number, body: any) => { status: number; headers?: Record<string, string> } = () => ({ status: 202 });
(globalThis as any).fetch = async (_url: string, init: any) => {
  if (init.headers.authorization !== `Bearer ${currentKey}`) return { status: 500, headers: { get: () => null }, text: async () => "" };
  const text = new TextDecoder().decode(init.headers["content-encoding"] === "gzip" ? (await import("node:zlib")).gunzipSync(init.body) : init.body);
  const body = JSON.parse(text);
  calls.push({ body, bytes: text.length });
  const r = platform(calls.length, body);
  return { status: r.status, headers: { get: (k: string) => r.headers?.[k.toLowerCase()] ?? null }, text: async () => "{}" };
};

function fresh(env: Record<string, string> | null = ENV) {
  for (const k of Object.keys(ENV)) delete process.env[k];
  delete process.env.FORGE_INSIGHTS_INCLUDE_TEXT;
  if (env) Object.assign(process.env, env);
  if (env?.FORGE_INSIGHTS_KEY) process.env.FORGE_INSIGHTS_KEY = currentKey = `fik_${String(++epoch).padStart(40, "0")}`;
  process.env.NODE_ENV = "production";
  (globalThis as any).__forgeInsightsShipper = undefined;
  fake.rows.turns.length = 0;
  fake.rows.handoffs.length = 0;
  fake.log.length = 0;
  fake.faults.insertThrows = fake.faults.updateThrows = fake.faults.selectThrows = null;
  calls.length = 0;
  platform = () => ({ status: 202 });
  return Outbox.insightsShipper();
}

const record = (over: Record<string, unknown> = {}) => ({
  conversationId: "conv-aaaa-0001", agentId: "support", userId: "person-7", userRole: "Customer", model: "claude-answered", inputTokens: 20, outputTokens: 10,
  ms: 1200, status: "ok" as const, error: null, toolCalls: 1, toolErrors: 0, toolStats: [{ name: "get_order", ok: true, ms: 100 }], handedOff: false,
  assistantMessageId: "msg-0001", turnNumber: 1, userMessage: null, ...over,
});
const allEvents = () => calls.flatMap((c) => c.body.events);
const ago = (ms: number) => new Date(Date.now() - ms);

/** A row already in the table, as an earlier process would have left it. */
function seedTurn(i: number, over: Record<string, unknown> = {}) {
  const row = {
    id: `aaaaaaaa-0000-4000-8000-${String(i).padStart(12, "0")}`, conversationId: `conv-${i}`, agentId: "support", userId: `p-${i % 50}`, userRole: null,
    model: "m", inputTokens: 1, outputTokens: 1, ms: 10, status: "ok", error: null, toolCalls: 0, toolErrors: 0, toolStats: [], handedOff: false,
    assistantMessageId: `msg-${i}`, turnNumber: 1, rating: null, ratingNote: null, ratingAt: null, problemMessage: null,
    createdAt: new Date(Date.now() - 3_000_000 + i * 1000), shippedAt: null, shipAttempts: 0, shipError: null, ...over,
  };
  fake.rows.turns.push(row);
  return row;
}

// ── a turn is written, then sent ──────────────────────────────────────────

console.log("a recorded turn is written first, then sent, and marked sent on a 202");
{
  const shipper = fresh();
  await turnStore.record(record());
  const row = fake.rows.turns[0];
  ok(/^[0-9a-f-]{36}$/.test(row.id) && row.createdAt instanceof Date, "the row has its own id and time");
  eqJson([row.userRole, row.turnNumber, row.conversationId, row.shippedAt], ["Customer", 1, "conv-aaaa-0001", null], "with the role, the turn number and no 'sent' mark yet");
  eqJson(calls.length, 0, "nothing was sent in the same breath: the send waits for its batch");
  await shipper.settle();
  eqJson(calls.length, 1, "settle sends it");
  const e = allEvents()[0];
  eqJson([e.type, e.id === row.id, e.role, e.env, e.conversationId], ["turn", true, "Customer", "production", "conv-aaaa-0001"], "the event's id is the row's id: what the platform dedupes by");
  eqJson(validateBatch(calls[0].body, calls[0].bytes), [], "valid");
  ok(row.shippedAt instanceof Date && row.shipError === null, "and the row is marked sent");
  const shippedAt = row.shippedAt;
  await Outbox.runInsightsTick();
  eqJson(calls.length, 1, "a tick afterwards has nothing to send");
  ok(row.shippedAt === shippedAt, "and does not touch it");
}

console.log("a turn that cannot be sent is kept, unmarked");
{
  const shipper = fresh();
  platform = () => ({ status: 503 });
  await turnStore.record(record());
  await shipper.settle();
  const row = fake.rows.turns[0];
  eqJson([row.shippedAt, row.shipAttempts], [null, 1], "still waiting, and the failed try is counted");
  ok(/503/.test(row.shipError), "with the reason");
}

console.log("who is it: signed in, or a visitor");
{
  const shipper = fresh();
  await turnStore.record(record({ userId: "anonymous", userRole: null, conversationId: "conv-v1" }));
  await turnStore.record(record({ userId: "anonymous", userRole: null, conversationId: "conv-v2" }));
  await turnStore.record(record({ userId: "anonymous", userRole: null, conversationId: "conv-v1", turnNumber: 2 }));
  await shipper.settle();
  const keys = allEvents().map((e) => e.userKey);
  ok(keys[0] !== keys[1] && keys[0] === keys[2], "a visitor is one person per conversation");
  ok(allEvents().every((e) => e.role === null), "with no role");
}

console.log("which message of its conversation: the runtime's count, or the table's");
{
  const shipper = fresh();
  await turnStore.record(record({ turnNumber: 5 }));
  eqJson(fake.rows.turns[0].turnNumber, 5, "the runtime's own count is kept");
  await turnStore.record(record({ conversationId: "conv-x", turnNumber: null }));
  await turnStore.record(record({ conversationId: "conv-x", turnNumber: null }));
  await turnStore.record(record({ conversationId: "conv-x", turnNumber: null }));
  eqJson(fake.rows.turns.filter((r: any) => r.conversationId === "conv-x").map((r: any) => r.turnNumber), [1, 2, 3], "without one it is one more than the turns already recorded");
  await turnStore.record(record({ conversationId: "", turnNumber: null }));
  eqJson(fake.rows.turns.at(-1).turnNumber, 1, "a turn refused before any conversation is the first");
  await shipper.settle();
}

console.log("the person's words stay out unless the builder allowed them");
{
  let shipper = fresh();
  await turnStore.record(record({ status: "error", error: "boom", userMessage: "my words" }));
  eqJson(fake.rows.turns[0].problemMessage, null, "the runtime hands over no words by default, and none are stored");
  shipper = fresh();
  process.env.FORGE_INSIGHTS_INCLUDE_TEXT = "1";
  (globalThis as any).__forgeInsightsShipper = undefined;
  shipper = Outbox.insightsShipper();
  await turnStore.record(record({ status: "error", error: "boom", userMessage: "  my   words\nhere " }));
  await turnStore.record(record({ userMessage: "a fine turn" }));
  await turnStore.record(record({ status: "blocked", error: "no", assistantMessageId: null, userMessage: "refused before it was saved" }));
  await turnStore.record(record({ status: "blocked", error: "no", assistantMessageId: "m-9", userMessage: "x".repeat(500) }));
  eqJson(fake.rows.turns.map((r: any) => r.problemMessage?.length ?? null), [13, null, null, 200], "kept only for turns that went wrong, tidied, cut to 200, and not for a message refused before it was saved");
  await shipper.settle();
  ok(allEvents()[0].problem.message === "my words here" && allEvents()[1].problem === null, "and sent in problem.message only");
  delete process.env.FORGE_INSIGHTS_INCLUDE_TEXT;
}

// ── not connected ─────────────────────────────────────────────────────────

console.log("an app that is not connected keeps every row and sends and deletes nothing");
{
  for (const [label, env] of [["no address", null], ["no salt", { FORGE_INSIGHTS_URL: ENV.FORGE_INSIGHTS_URL, FORGE_INSIGHTS_KEY: ENV.FORGE_INSIGHTS_KEY }]] as const) {
    const shipper = fresh(env as any);
    seedTurn(1, { shippedAt: ago(30 * DAY) });
    await turnStore.record(record());
    await shipper.settle();
    const report = await Outbox.runInsightsTick();
    eqJson([calls.length, report.configured, report.pruned, fake.rows.turns.length], [0, false, 0, 2], `${label}: nothing sent, the week-old sent row is NOT deleted, both rows kept`);
    eqJson(fake.rows.turns.every((r: any) => r.shipAttempts === 0), true, `${label}: and no attempt is counted`);
  }
}

// ── the tick ──────────────────────────────────────────────────────────────

console.log("the tick sends the OLDEST waiting rows first, 500 to a request, a few requests a tick");
{
  fresh();
  const total = 1300;
  // Stored out of order on purpose: the order is the row's time, not the order they were written.
  const order = Array.from({ length: total }, (_, i) => i);
  for (let k = order.length - 1; k > 0; k--) { const j = (k * 7919) % (k + 1); [order[k], order[j]] = [order[j], order[k]]; }
  for (const i of order) seedTurn(i);
  const r1 = await Outbox.runInsightsTick({ maxBatches: 2 });
  eqJson(calls.map((c) => c.body.events.length), [500, 500], "two requests of 500 (the limit of this tick)");
  eqJson([r1.sent, r1.waiting], [1000, true], "1000 sent, and it says some still wait");
  const sentIds = allEvents().map((e) => e.id);
  const expected = [...fake.rows.turns].sort((a: any, b: any) => a.createdAt - b.createdAt).slice(0, 1000).map((r: any) => r.id);
  eqJson(sentIds, expected, "they are the 1000 oldest, oldest first");
  eqJson(fake.rows.turns.filter((r: any) => r.shippedAt).length, 1000, "exactly those are marked sent");
  const r2 = await Outbox.runInsightsTick({ maxBatches: 10 });
  eqJson([r2.sent, r2.waiting, fake.rows.turns.every((r: any) => r.shippedAt)], [300, false, true], "the next tick sends the last 300");
  eqJson(new Set(allEvents().map((e) => e.id)).size, total, "all 1300, each once");
  eqJson(calls.flatMap((c) => validateBatch(c.body, c.bytes)), [], "every request meets the contract");
  const before = calls.length;
  const r3 = await Outbox.runInsightsTick();
  eqJson([calls.length - before, r3.sent], [0, 0], "a tick with nothing waiting sends nothing");
}

console.log("a crashed process loses nothing, and sending again is harmless");
{
  fresh();
  for (let i = 0; i < 5; i++) seedTurn(i);
  const first = await Outbox.runInsightsTick();
  eqJson(first.sent, 5, "rows left by an earlier process are sent by a later one");
  const ids1 = allEvents().map((e) => e.id);
  // The platform said 202 but the app died before it could mark the rows: they are still unmarked.
  for (const r of fake.rows.turns) r.shippedAt = null;
  calls.length = 0;
  await Outbox.runInsightsTick();
  eqJson(allEvents().map((e) => e.id), ids1, "sent again with the very same event ids, which is what the platform dedupes by");
}

console.log("a platform that is down stops the tick and costs nothing");
{
  fresh();
  for (let i = 0; i < 1200; i++) seedTurn(i);
  platform = () => ({ status: 503 });
  const r = await Outbox.runInsightsTick({ maxBatches: 10 });
  eqJson(calls.length, 1, "one try, not ten");
  eqJson([r.sent, r.waiting, fake.rows.turns.some((t: any) => t.shippedAt)], [0, true, false], "nothing marked sent, the report says rows wait");
  ok(/could not take/.test(r.note ?? ""), "in plain words");
  const r2 = await Outbox.runInsightsTick();
  eqJson(calls.length, 1, "and the next tick, in the middle of the back-off, does not hammer it");
  ok(r2.waiting, "still waiting");
  eqJson(fake.rows.turns.filter((t: any) => t.shipAttempts === 1).length, 500, "the 500 rows of the request that failed each had that try counted once");

  const s = fresh();
  for (let i = 0; i < 3; i++) seedTurn(i);
  platform = () => ({ status: 429, headers: { "retry-after": "5" } });
  await Outbox.runInsightsTick();
  eqJson(s.stats().backoffUntil > Date.now() + 3000, true, "a 429's Retry-After is remembered");
}

console.log("a row the platform will never take is closed, and the rest go on");
{
  fresh();
  for (let i = 0; i < 8; i++) seedTurn(i);
  const badId = fake.rows.turns[3].id;
  platform = (_n, body) => ({ status: body.events.some((e: any) => e.id === badId) ? 400 : 202 });
  const r = await Outbox.runInsightsTick();
  eqJson(r.waiting, false, "the tick is not left waiting");
  eqJson(fake.rows.turns.filter((t: any) => t.shippedAt).length, 8, "every row is closed: seven sent, one refused");
  const bad = fake.rows.turns[3];
  ok(bad.shippedAt && /refused/.test(bad.shipError), "the refused one carries the reason");
  ok(fake.rows.turns.filter((t: any) => t.shipError).length === 1, "and only that one");
}

console.log("rows too old for the platform are not sent");
{
  fresh();
  seedTurn(1, { createdAt: ago(120 * DAY) });
  seedTurn(2);
  seedTurn(3, { createdAt: null });
  const r = await Outbox.runInsightsTick();
  eqJson([r.sent, r.skipped, calls.length, allEvents().length], [1, 2, 1, 1], "only the fresh one goes; the 120-day-old row and the one with no time are closed here");
  ok(fake.rows.turns[0].shippedAt && /older/.test(fake.rows.turns[0].shipError), "with the reason");
}

// ── retention ─────────────────────────────────────────────────────────────

console.log("rows sent more than a week ago are deleted, in small batches");
{
  fresh();
  for (let i = 0; i < 1200; i++) seedTurn(i, { shippedAt: ago(8 * DAY + i) });
  seedTurn(2000, { shippedAt: ago(6 * DAY) });
  seedTurn(2001, { shippedAt: ago(30 * DAY), shipError: "refused: bad" });
  seedTurn(2002, { shippedAt: null, createdAt: ago(40 * DAY) });
  const r = await Outbox.runInsightsTick();
  eqJson(r.pruned, 1201, "1200 old sent rows and the old refused one go");
  eqJson(fake.rows.turns.map((t: any) => t.id.slice(-4)).sort(), ["2000", "2002"].sort(), "a row sent 6 days ago stays, and so does an old row that was never sent");
  eqJson(fake.log.filter((l) => l === "delete turns 500").length >= 2, true, "deleted 500 at a time");
  const re = fresh();
  seedTurn(1, { shippedAt: ago(3 * DAY) });
  process.env.FORGE_INSIGHTS_RETENTION_DAYS = "2";
  await Outbox.runInsightsTick();
  delete process.env.FORGE_INSIGHTS_RETENTION_DAYS;
  eqJson(fake.rows.turns.length, 0, "the number of days can be changed (FORGE_INSIGHTS_RETENTION_DAYS)");
  void re;
}

// ── ratings ───────────────────────────────────────────────────────────────

console.log("a rating puts the row back in the outbox and is sent for the same turn");
{
  const shipper = fresh();
  await turnStore.record(record());
  await shipper.settle();
  const row = fake.rows.turns[0];
  const shippedBefore = row.shippedAt;
  ok(shippedBefore, "the turn was sent");
  calls.length = 0;
  eqJson(await rateTurn({ conversationId: "conv-aaaa-0001", messageId: "msg-0001", rating: 1, note: null }), 1, "one turn rated");
  eqJson([row.rating, row.shippedAt, row.shipError], [1, null, null], "the row is waiting again");
  ok(row.ratingAt instanceof Date, "with the moment of the rating");
  await shipper.settle();
  eqJson(allEvents().map((e) => [e.type, e.turnId, e.rating]), [["rating", row.id, 1]], "a rating event for that very turn");
  ok(row.shippedAt, "and the row is marked sent again");
  const firstRatingId = allEvents()[0].id;

  calls.length = 0;
  await new Promise((r) => setTimeout(r, 5));
  await rateTurn({ conversationId: "conv-aaaa-0001", messageId: "msg-0001", rating: -1, note: "wrong date" });
  await shipper.settle();
  const second = allEvents()[0];
  eqJson([second.turnId, second.rating, second.id !== firstRatingId, second.note], [row.id, -1, true, null], "changing one's mind is a NEW event for the same turn (replacing the first; no note without text allowed)");
  eqJson(validateBatch(calls[0].body), [], "valid");

  eqJson(await rateTurn({ conversationId: "conv-aaaa-0001", messageId: "nope", rating: 1, note: null }), 0, "a rating for a turn that was never recorded rates nothing and sends nothing");
  eqJson(calls.length, 1, "(no further request)");
}

console.log("a rating that arrives while the first send is in flight is not lost");
{
  const shipper = fresh();
  await turnStore.record(record());
  const row = fake.rows.turns[0];
  const item = (await import("../agents/insights-shipper.ts")).itemForTurnRow(row, shipper.config!)!;
  await rateTurn({ conversationId: "conv-aaaa-0001", messageId: "msg-0001", rating: -1, note: null });
  await Outbox.outbox.markShipped([item]);
  eqJson(row.shippedAt, null, "the older send finishing does not take the row out of the outbox, because it was rated meanwhile");
  await Outbox.runInsightsTick();
  eqJson([row.shippedAt instanceof Date, allEvents().map((e) => e.type)], [true, ["turn", "rating"]], "the tick then sends the turn and its rating together");
}

console.log("the tick sends a rated turn with its rating");
{
  fresh();
  seedTurn(1, { rating: -1, ratingAt: ago(1000), ratingNote: "bad" });
  seedTurn(2, { rating: 1, ratingAt: null });
  await Outbox.runInsightsTick();
  eqJson(allEvents().map((e) => e.type), ["turn", "rating", "turn", "rating"], "each rated row sends turn and rating");
  eqJson(fake.rows.turns.every((t: any) => t.shippedAt), true, "and both rows are marked (the one with no rating time too)");
}

// ── hand-offs ─────────────────────────────────────────────────────────────

console.log("a hand-off's status changes are sent");
{
  const shipper = fresh();
  const h = await handoffStore.create({ conversationId: "conv-h1", agentId: "support", requestedById: "person-7", requestedByName: "P", reason: "r", urgency: "normal", contact: null, summary: null, assignedToId: null, assignedToName: null, resolutionNote: null } as any);
  await shipper.settle();
  const out = await changeHandoff(h.id, { action: "claim", by: { id: "staff-1", name: "S" } });
  await shipper.settle();
  const done2 = await changeHandoff(h.id, { action: "resolve", note: "done" });
  await shipper.settle();
  ok(out && done2, "the hand-offs changed as before");
  eqJson(allEvents().map((e) => [e.type, e.status, e.conversationId, e.agentId]), [["handoff", "open", "conv-h1", "support"], ["handoff", "claimed", "conv-h1", "support"], ["handoff", "resolved", "conv-h1", "support"]], "opened, claimed, resolved");
  ok(typeof allEvents()[2].resolveMinutes === "number", "the resolved one says how long it took");
  eqJson(calls.flatMap((c) => validateBatch(c.body, c.bytes)), [], "valid");
  ok(!JSON.stringify(allEvents()).includes("person-7") && !JSON.stringify(allEvents()).includes("staff-1"), "no person, requester or handler, is named");
}

console.log("a hand-off change that could not be sent is offered again by the tick, then not again");
{
  const shipper = fresh();
  platform = () => ({ status: 503 });
  const h = await handoffStore.create({ conversationId: "conv-h2", agentId: "support", requestedById: "p", requestedByName: "P", reason: "r", urgency: "normal", contact: null, summary: null, assignedToId: null, assignedToName: null, resolutionNote: null } as any);
  await shipper.settle();
  eqJson(allEvents().length, 1, "tried once while the platform was down");
  // a new process, the platform back
  const next = fresh();
  fake.rows.handoffs.length = 0;
  const kept = await handoffStore.create({ conversationId: "conv-h3", agentId: "support", requestedById: "p", requestedByName: "P", reason: "r", urgency: "normal", contact: null, summary: null, assignedToId: null, assignedToName: null, resolutionNote: null } as any);
  void kept; void h;
  (globalThis as any).__forgeInsightsShipper = undefined;
  calls.length = 0;
  platform = () => ({ status: 202 });
  const r = await Outbox.runInsightsTick();
  eqJson(allEvents().filter((e) => e.type === "handoff").map((e) => e.conversationId), ["conv-h3"], "the tick sends the change a crashed process never did");
  calls.length = 0;
  await Outbox.runInsightsTick();
  eqJson(calls.length, 0, "and, once the platform has it, not again");
  void next; void r;
}

// ── an app whose database has not been updated ────────────────────────────

console.log("an app updated but not yet migrated still records and still rates");
{
  const shipper = fresh();
  const missing = () => Object.assign(new Error('column "user_role" of relation "forge_agent_turns" does not exist'), { code: "42703" });
  let thrown = 0;
  const realWarn = console.warn;
  const said: string[] = [];
  console.warn = (...a: unknown[]) => { said.push(a.join(" ")); };
  try {
    // The table has the old columns only: any write naming a new one fails, a write that does not name them works.
    const realInsert = fake.db.insert;
    fake.db.insert = ((t: any) => ({
      values(v: any) {
        if ("userRole" in v) { thrown++; return { returning() { return this; }, then: (_r: any, rej: any) => Promise.reject(missing()).then(_r, rej) }; }
        return realInsert(t).values(v);
      },
    })) as any;
    await turnStore.record(record());
    await turnStore.record(record({ conversationId: "conv-2" }));
    fake.db.insert = realInsert;
    eqJson([thrown, fake.rows.turns.length], [2, 2], "the turn is written again without the new columns");
    ok(!("userRole" in fake.rows.turns[0]) && fake.rows.turns[0].agentId === "support", "with what the old table has");
    eqJson(said.length, 1, "and the log says it once");
    ok(/drizzle-kit push/.test(said[0]), "naming the fix");

    fake.faults.updateThrows = null;
    const realUpdate = fake.db.update;
    fake.db.update = ((t: any) => {
      let set: any;
      const q: any = {
        set(v: any) { set = v; return q; },
        where(p: any) { q.p = p; return q; },
        returning(c: any) { q.c = c; return q; },
        then(res: any, rej: any) {
          if ("ratingAt" in set) return Promise.reject(missing()).then(res, rej);
          return (realUpdate(t) as any).set(set).where(q.p).returning(q.c).then(res, rej);
        },
      };
      return q;
    }) as any;
    eqJson(await rateTurn({ conversationId: "conv-aaaa-0001", messageId: "msg-0001", rating: 1, note: null }), 1, "a rating is still saved with the columns the table has");
    eqJson(fake.rows.turns[0].rating, 1, "and sticks");
    fake.db.update = realUpdate;
    await shipper.settle();
  } finally {
    console.warn = realWarn;
  }
  fresh();
  seedTurn(1);
  fake.faults.selectThrows = missing;
  const r = await Outbox.runInsightsTick();
  ok(r.waiting && /drizzle-kit push/.test(r.note ?? "") && calls.length === 0, "a tick on such a database says what to do, and sends nothing");
  eqJson(Outbox.isMissingColumn(missing()) && Outbox.isMissingColumn(new Error('column "x" does not exist')) && !Outbox.isMissingColumn(new Error("connection refused")), true, "only a missing column counts as one");
}

done("insights outbox");
