/**
 * The cost-and-quality report built from recorded turns, run from the SHIPPED files in templates/runtime/agents/ and
 * api-agent/.
 *
 * What is pinned: the totals, the percentiles, one entry for every day (zeros included), the models and tools, the
 * reason each problem is listed for and the words shown with it (cut, and never an answer or a tool result), the
 * hand-over figures, the agent filter, the day clamp; the report an app with no turns table gives (the same shape, all
 * zeros, with a warning); and that the route is shut like the debug route: development only, the platform's secret,
 * otherwise a plain 404.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const agents = (f: string) => path.resolve(HERE, "../agents", f);

// insights.ts loads the database on demand; the stand-ins here answer from a queue the test fills.
installHarness({
  redirect: { "@/lib/agents/insights": agents("insights.ts"), "@/lib/agents/debug": agents("debug.ts") },
  stubs: {
    "@/db": `
      const chain = new Proxy(function () {}, {
        get(_, k) {
          if (k === "then") return (res, rej) => { try { res(globalThis.__dbNext()); } catch (e) { rej(e); } };
          return () => chain;
        },
        apply() { return chain; },
      });
      export const db = { select: () => chain };`,
    "drizzle-orm": "export const and = (...a) => a, desc = (x) => x, eq = (a, b) => [a, b], gte = (a, b) => [a, b], inArray = (a, b) => [a, b], min = (x) => x;",
    "@/db/schema/_forge_agent_turns": "export const forgeAgentTurns = new Proxy({}, { get: (_, k) => String(k) });",
    "@/db/schema/_forge_agent_handoffs": "export const forgeAgentHandoffs = new Proxy({}, { get: (_, k) => String(k) });",
    "@/db/schema/_forge_agent": "export const forgeAgentMessages = new Proxy({}, { get: (_, k) => String(k) });",
  },
});

const { buildInsights, emptyInsights, clampDays, fetchInsights, reasonOf, NO_TURNS_WARNING } = await import("../agents/insights.ts");

// ── fixtures ──────────────────────────────────────────────────────────────

const NOW = new Date("2026-10-22T12:00:00Z");
const at = (iso: string) => new Date(`${iso}Z`);

let n = 0;
const turn = (over: Record<string, unknown> = {}): any => ({
  conversationId: `c${++n}`,
  agentId: "support",
  userId: "u1",
  model: "m-a",
  inputTokens: 10,
  outputTokens: 5,
  ms: 1000,
  status: "ok",
  error: null,
  toolCalls: 0,
  toolErrors: 0,
  toolStats: null,
  handedOff: false,
  assistantMessageId: `am${n}`,
  rating: null,
  ratingNote: null,
  createdAt: at("2026-10-22T09:00:00"),
  ...over,
});

const long = ("This is a very long question about my order and when it will arrive. ").repeat(6);

const rows = [
  // a good one, thumbs up, two tools that worked
  turn({ conversationId: "c1", userId: "u1", inputTokens: 100, outputTokens: 50, ms: 1000, toolCalls: 2, rating: 1, createdAt: at("2026-10-22T09:00:00"),
    toolStats: [{ name: "list_tickets", ok: true, ms: 100 }, { name: "get_ticket", ok: true, ms: 300 }] }),
  // a tool failed
  turn({ conversationId: "c1", userId: "u1", inputTokens: 200, outputTokens: 100, ms: 2000, toolCalls: 1, toolErrors: 1, createdAt: at("2026-10-22T10:00:00"),
    toolStats: [{ name: "list_tickets", ok: false, ms: 500 }] }),
  // slow AND thumbs down: the thumbs down is the better reason
  turn({ conversationId: "c2", userId: "u2", model: "m-b", inputTokens: 50, outputTokens: 20, ms: 40_000, rating: -1, ratingNote: "wrong date", createdAt: at("2026-10-21T10:00:00") }),
  // failed
  turn({ conversationId: "c3", userId: "u2", model: null, inputTokens: 0, outputTokens: 0, ms: 700, status: "error", error: "overloaded_error", assistantMessageId: null, createdAt: at("2026-10-21T11:00:00") }),
  // answer blocked (an answer was saved)
  turn({ conversationId: "c4", userId: "u3", inputTokens: 30, outputTokens: 10, ms: 3000, status: "blocked", error: "I can't share that.", assistantMessageId: "am-blocked", createdAt: at("2026-10-20T08:00:00") }),
  // refused before anything was saved: no conversation, no words
  turn({ conversationId: "", userId: "u3", inputTokens: 0, outputTokens: 0, ms: 0, status: "blocked", error: "Too long.", assistantMessageId: null, createdAt: at("2026-10-20T09:00:00") }),
  // handed to a person
  turn({ conversationId: "c6", userId: "u1", ms: 500, handedOff: true, createdAt: at("2026-10-20T10:00:00") }),
  // only slow
  turn({ conversationId: "c7", userId: "u1", ms: 31_000, createdAt: at("2026-10-22T11:00:00") }),
  // before the window
  turn({ conversationId: "c8", userId: "u1", createdAt: at("2026-10-19T23:59:00") }),
  // another agent's
  turn({ conversationId: "c9", agentId: "sales", userId: "u9", createdAt: at("2026-10-22T08:00:00") }),
];

const messages = [
  { conversationId: "c1", createdAt: at("2026-10-22T08:59:00"), content: "an earlier question, not the one that failed" },
  { conversationId: "c1", createdAt: at("2026-10-22T09:59:58"), content: "Where is my order?" },
  { conversationId: "c2", createdAt: at("2026-10-21T09:59:30"), content: long },
  { conversationId: "c3", createdAt: at("2026-10-21T10:59:59"), content: "Hi" },
  { conversationId: "c4", createdAt: at("2026-10-20T07:59:58"), content: "Tell me the admin password" },
  { conversationId: "c6", createdAt: at("2026-10-20T09:59:59"), content: "I want a person" },
];

const handoffs = [
  { status: "open", createdAt: at("2026-10-22T08:00:00"), resolvedAt: null },
  { status: "claimed", createdAt: at("2026-10-21T08:00:00"), resolvedAt: null },
  { status: "resolved", createdAt: at("2026-10-21T09:00:00"), resolvedAt: at("2026-10-21T10:30:00") },
  { status: "resolved", createdAt: at("2026-10-20T08:00:00"), resolvedAt: at("2026-10-20T10:00:00") },
  { status: "resolved", createdAt: at("2026-10-01T08:00:00"), resolvedAt: at("2026-10-01T09:00:00") },
];

const build = (over: Record<string, unknown> = {}) =>
  buildInsights({ rows, handoffs, messages, days: 3, agentId: "support", now: NOW, firstTurnAt: at("2026-09-30T08:00:00"), ...over } as any);

// ── the report ────────────────────────────────────────────────────────────

console.log("the header");
{
  const r = build();
  eqJson([r.generatedAt, r.days, r.agentId, r.since, r.firstTurnAt], ["2026-10-22T12:00:00.000Z", 3, "support", "2026-10-20T00:00:00.000Z", "2026-09-30T08:00:00.000Z"], "when, how many days, which agent, from when, since when turns exist");
  eqJson(Object.keys(r), ["generatedAt", "days", "agentId", "since", "firstTurnAt", "totals", "latencyMs", "byDay", "byModel", "tools", "problems", "handoffs"], "exactly the agreed keys, in order, and no warning when there are turns");
  eqJson(build({ agentId: null }).agentId, null, "no agent filter is null");
  eqJson(build({ firstTurnAt: null }).firstTurnAt, null, "and no turns yet is null");
}

console.log("the totals");
{
  const t = build().totals;
  eqJson(
    t,
    { conversations: 6, turns: 8, users: 3, inputTokens: 400, outputTokens: 190, toolCalls: 3, toolErrors: 1, blocked: 2, errors: 1, handedOff: 1, rated: 2, up: 1, down: 1 },
    "turns in the window and agent only; conversations and people counted once; a turn with no conversation adds none",
  );
  const all = build({ agentId: null }).totals;
  eqJson([all.turns, all.users], [9, 4], "with no agent named, every agent's turns count");
}

console.log("the speed");
{
  eqJson(build().latencyMs, { p50: 1000, p95: 40_000, avg: 9775 }, "the middle, the slow end (nearest rank) and the mean, from the rows");
  eqJson(build({ rows: [turn({ ms: 4000 })] }).latencyMs, { p50: 4000, p95: 4000, avg: 4000 }, "one turn is all three");
  eqJson(build({ rows: [] }).latencyMs, { p50: 0, p95: 0, avg: 0 }, "no turns is zeros");
  const hundred = Array.from({ length: 100 }, (_, i) => turn({ ms: (i + 1) * 10 }));
  eqJson(build({ rows: hundred }).latencyMs, { p50: 500, p95: 950, avg: 505 }, "100 turns: the 50th and 95th");
}

console.log("every day is listed, zeros included");
{
  const d = build().byDay;
  eqJson(d.map((x: any) => x.day), ["2026-10-20", "2026-10-21", "2026-10-22"], "oldest first, ending today");
  eqJson(d[0], { day: "2026-10-20", turns: 3, inputTokens: 40, outputTokens: 15, errors: 0, up: 0, down: 0 }, "a day's turns and tokens");
  eqJson(d[1], { day: "2026-10-21", turns: 2, inputTokens: 50, outputTokens: 20, errors: 1, up: 0, down: 1 }, "its errors and thumbs");
  eqJson(d[2], { day: "2026-10-22", turns: 3, inputTokens: 310, outputTokens: 155, errors: 0, up: 1, down: 0 }, "today so far");
  const quiet = build({ rows: [turn({ createdAt: at("2026-10-22T01:00:00") })], days: 5 }).byDay;
  eqJson(quiet.map((x: any) => x.turns), [0, 0, 0, 0, 1], "a quiet week is still five entries");
  ok(quiet.slice(0, 4).every((x: any) => x.inputTokens === 0 && x.outputTokens === 0 && x.errors === 0 && x.up === 0 && x.down === 0), "with zeros, not holes");
  eqJson(build({ days: 1, rows: [] }).byDay.map((x: any) => x.day), ["2026-10-22"], "one day is today");
  eqJson(build({ days: 90, rows: [] }).byDay.length, 90, "ninety days is ninety entries");
}

console.log("models and tools");
{
  const r = build();
  eqJson(r.byModel, [
    { model: "m-a", turns: 6, inputTokens: 350, outputTokens: 170 },
    { model: "m-b", turns: 1, inputTokens: 50, outputTokens: 20 },
    { model: "unknown", turns: 1, inputTokens: 0, outputTokens: 0 },
  ], "by model, the busiest first; a turn with no model is 'unknown'");
  eqJson(r.tools, [{ name: "list_tickets", calls: 2, errors: 1, avgMs: 300 }, { name: "get_ticket", calls: 1, errors: 0, avgMs: 300 }], "tools, busiest first, with failures and the average time");
  const many = Array.from({ length: 30 }, (_, i) => turn({ toolStats: [{ name: `tool_${String(i).padStart(2, "0")}`, ok: true, ms: 10 }] }));
  eqJson(build({ rows: many }).tools.length, 20, "at most 20 tools");
  eqJson(build({ rows: [turn({ toolStats: "garbage" }), turn({ toolStats: [null, { ok: true }, { name: "x", ok: true, ms: 5 }] })] }).tools, [{ name: "x", calls: 1, errors: 0, avgMs: 5 }], "stored detail that is not what was expected is skipped, not fatal");
}

console.log("the conversations to look at");
{
  const p = build().problems;
  eqJson(p.map((x: any) => x.reason), ["slow", "tool_failed", "error", "thumbs_down", "handed_off", "blocked", "blocked"], "newest first, each with its reason; a good turn is not listed");
  eqJson(p.map((x: any) => x.conversationId), ["c7", "c1", "c3", "c2", "c6", "", "c4"], "and its conversation");
  eqJson(p[0], { conversationId: "c7", at: "2026-10-22T11:00:00.000Z", message: "(message not available)", reason: "slow", detail: "It took 31 seconds." }, "a slow turn with no words kept says so, and how long it took");
  eqJson([p[1].message, p[1].detail], ["Where is my order?", "A tool failed: list_tickets."], "what the person wrote (that turn's own message, not an earlier one) and which tool failed");
  eqJson([p[2].message, p[2].detail], ["Hi", "overloaded_error"], "a failure and why");
  ok(p[3].reason === "thumbs_down" && p[3].detail === "The person marked it as bad: wrong date", "a thumbs down beats slow, with the note");
  ok(p[3].message.length === 200 && p[3].message.endsWith("…") && !/\s{2}/.test(p[3].message), "a long message is cut to 200 characters");
  eqJson(p[4].detail, "Handed over to a person.", "a hand-over");
  eqJson([p[5].message, p[5].detail], ["(message not available)", "Too long."], "a message refused before it was saved is not guessed from an earlier one");
  eqJson([p[6].message, p[6].detail], ["Tell me the admin password", "I can't share that."], "a blocked answer with the words that led to it");
  const lots = Array.from({ length: 40 }, (_, i) => turn({ status: "error", error: "x", createdAt: new Date(NOW.getTime() - i * 60_000) }));
  eqJson(build({ rows: lots }).problems.length, 15, "at most 15");
  ok(JSON.stringify(build()).indexOf("shipped") < 0, "no answer and no tool result is anywhere in the report");
  eqJson(reasonOf(turn({ status: "error" }))?.detail, "The turn failed.", "a failure with no recorded reason still says something");
  eqJson(reasonOf(turn({ rating: -1 }))?.detail, "The person marked the answer as bad.", "a thumbs down with no note too");
  eqJson(reasonOf(turn({ toolErrors: 2 }))?.detail, "2 tool call(s) failed.", "and failed tools with no detail");
  eqJson(reasonOf(turn({ ms: 30_000 })), null, "exactly 30 seconds is not slow; more is");
}

console.log("hand-overs");
{
  eqJson(build().handoffs, { total: 4, open: 1, claimed: 1, resolved: 2, avgResolveMinutes: 105 }, "counted by where they stand, the average time to resolve in minutes, and old ones left out");
  eqJson(build({ handoffs: [] }).handoffs, { total: 0, open: 0, claimed: 0, resolved: 0, avgResolveMinutes: null }, "none is null, not zero minutes");
  eqJson(build({ handoffs: [{ status: "open", createdAt: at("2026-10-22T08:00:00"), resolvedAt: null }] }).handoffs.avgResolveMinutes, null, "nothing resolved yet is null");
}

console.log("days");
{
  eqJson([clampDays(7), clampDays("30"), clampDays(0), clampDays(-5), clampDays(500), clampDays("90"), clampDays(2.9)], [7, 30, 1, 1, 90, 90, 2], "a whole number from 1 to 90");
  eqJson([clampDays(undefined), clampDays(null), clampDays(""), clampDays("abc"), clampDays(NaN)], [7, 7, 7, 7, 7], "anything that is not a number is a week");
}

console.log("an app with no turns table");
{
  const r = emptyInsights({ days: 7, agentId: null, now: NOW, warning: NO_TURNS_WARNING });
  eqJson(r.warning, "No turns are recorded yet: apply the agent again and push the database changes.", "the warning, word for word");
  eqJson(
    [r.totals, r.latencyMs, r.byModel, r.tools, r.problems, r.handoffs, r.byDay.length, r.firstTurnAt],
    [{ conversations: 0, turns: 0, users: 0, inputTokens: 0, outputTokens: 0, toolCalls: 0, toolErrors: 0, blocked: 0, errors: 0, handedOff: 0, rated: 0, up: 0, down: 0 }, { p50: 0, p95: 0, avg: 0 }, [], [], [], { total: 0, open: 0, claimed: 0, resolved: 0, avgResolveMinutes: null }, 7, null],
    "the same shape, all zeros",
  );
}

// ── reading the database ──────────────────────────────────────────────────

const g = globalThis as any;
const answers = (...list: Array<unknown | (() => unknown)>) => {
  g.__dbNext = () => {
    const next = list.shift();
    if (typeof next === "function") return (next as () => unknown)();
    return next;
  };
};

console.log("the table is missing");
{
  answers(() => { throw Object.assign(new Error("Failed query: select ..."), { cause: { code: "42P01", message: 'relation "forge_agent_turns" does not exist' } }); });
  const r = await fetchInsights({ days: "7", now: NOW });
  eqJson([r.warning, r.totals.turns, r.byDay.length], [NO_TURNS_WARNING, 0, 7], "a missing table is the empty report with the warning, not a failure");
  answers(() => { throw new Error('relation "forge_agent_turns" does not exist'); });
  eqJson((await fetchInsights({ now: NOW })).warning, NO_TURNS_WARNING, "recognised by its words too");
  answers(() => { throw new Error("connection refused"); });
  let failed = false;
  try { await fetchInsights({ now: NOW }); } catch { failed = true; }
  ok(failed, "any other database trouble is still an error");
}

console.log("the table is there");
{
  // The database holds conversation ids as uuids, and only those are looked up for their words.
  const uid = (c: string) => (c ? `00000000-0000-4000-8000-${c.replace("c", "").padStart(12, "0")}` : c);
  const stored = rows.map((x: any) => ({ ...x, conversationId: uid(x.conversationId) }));
  answers(stored.filter((x: any) => x.agentId === "support" && x.createdAt >= at("2026-10-20T00:00:00")), [{ at: at("2026-09-30T08:00:00") }], handoffs, messages.map((m: any) => ({ ...m, conversationId: uid(m.conversationId) })));
  const r = await fetchInsights({ days: 3, agentId: " support ", now: NOW });
  eqJson([r.agentId, r.totals.turns, r.warning, r.firstTurnAt], ["support", 8, undefined, "2026-09-30T08:00:00.000Z"], "turns, the first turn's time, no warning");
  eqJson([r.handoffs.total, r.problems.find((x: any) => x.reason === "tool_failed")?.message], [4, "Where is my order?"], "hand-overs and the words are read too");
  answers(rows.slice(0, 2), [{ at: null }], () => { throw new Error('relation "forge_agent_handoffs" does not exist'); }, () => { throw new Error("messages gone"); });
  const lean = await fetchInsights({ days: 3, now: NOW });
  eqJson([lean.totals.turns > 0, lean.handoffs.total, lean.firstTurnAt, lean.warning], [true, 0, null, undefined], "missing hand-overs or messages only leave those parts empty");
}

// ── the route is shut like the debug route ────────────────────────────────

console.log("the route");
{
  const dir = mkdtempSync(path.join(tmpdir(), "forge-insights-"));
  const before = process.cwd();
  const beforeEnv = process.env.NODE_ENV;
  const { GET } = await import("../api-agent/insights-route.ts");
  const ask = async (secret: string | null, query = "") => {
    const res = await GET(new Request(`http://x/api/agent/insights${query}`, { headers: secret === null ? {} : { "x-forge-debug-secret": secret } }));
    return { status: res.status, body: (await res.json()) as any };
  };
  const notFound = (r: any) => r.status === 404 && JSON.stringify(r.body) === '{"error":"Not found."}';
  try {
    process.chdir(dir);
    process.env.NODE_ENV = "development";
    answers(() => { throw new Error("must not be read"); });
    ok(notFound(await ask("s3cret")), "no secret file in the app: a plain 404");
    writeFileSync(path.join(dir, ".forge-debug-secret"), "s3cret\n");
    ok(notFound(await ask(null)), "no secret in the request: a plain 404");
    ok(notFound(await ask("wrong")), "the wrong secret: the same 404");
    process.env.NODE_ENV = "production";
    ok(notFound(await ask("s3cret")), "in production: a plain 404 even with the right secret");
    process.env.NODE_ENV = "development";

    answers([], [{ at: null }], []);
    let r = await ask("s3cret", "?days=500&agent=support");
    eqJson([r.status, r.body.days, r.body.agentId, r.body.byDay.length, r.body.totals.turns], [200, 90, "support", 90, 0], "the right secret: the report, with days clamped to 90 and the agent as asked");
    answers([], [{ at: null }], []);
    r = await ask("s3cret");
    eqJson([r.body.days, r.body.agentId], [7, null], "days left out is a week, and no agent is every agent");
    answers(() => { throw new Error("boom: secret detail"); });
    const realError = console.error;
    console.error = () => {}; // the route logs the real cause for the developer
    r = await ask("s3cret");
    console.error = realError;
    ok(r.status === 500 && r.body.error === "Could not work out the insights." && !JSON.stringify(r.body).includes("boom"), "a real failure is one plain sentence with nothing of the cause");
  } finally {
    process.chdir(before);
    if (beforeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = beforeEnv;
  }
}

done("agent insights");
