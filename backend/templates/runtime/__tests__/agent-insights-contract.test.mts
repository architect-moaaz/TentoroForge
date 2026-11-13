/**
 * The contract between the app and the platform's ingest, checked end to end: a batch the app really produces (through
 * the shipped shipper, over a fake network) is validated against the written rules of POST /api/insights/ingest —
 * field types, lengths, hex userKey, at most 20 tools, ids of 8 to 64 safe characters, at most 500 events and 1 MB.
 *
 * The checker is itself tested, with batches that break each rule, so a checker that approves everything cannot pass.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { validateBatch } from "./_insights-contract.mts";

installHarness();
const S = await import("../agents/insights-shipper.ts");

const cfg = { salt: "contract-salt-0123456789", includeText: true, env: "development" as const };
let n = 0;
const row = (over: Record<string, unknown> = {}): any => ({
  id: `11111111-2222-4333-8444-${String(++n).padStart(12, "0")}`, conversationId: `conv-${n}`, agentId: "support", userId: `person-${n}`, userRole: n % 2 ? "Admin" : null,
  model: "claude-sonnet-4-6", inputTokens: 100, outputTokens: 50, ms: 1500, status: "ok", error: null, toolCalls: 2, toolErrors: 0,
  toolStats: [{ name: "get_order", ok: true, ms: 120 }, { name: "list_orders", ok: true, ms: 80 }], handedOff: false, turnNumber: 1,
  rating: null, ratingNote: null, ratingAt: null, problemMessage: null, createdAt: new Date("2026-10-21T08:00:00Z"), ...over,
});

// What the app really sends: every kind of event, through the real shipper, read off the wire.
const wire: Array<{ body: any; bytes: number }> = [];
const shipper = S.createShipper({
  env: { FORGE_INSIGHTS_URL: "https://platform.test/ingest", FORGE_INSIGHTS_KEY: "fik_" + "a".repeat(40), FORGE_INSIGHTS_USER_SALT: cfg.salt },
  fetch: (async (_u: string, init: any) => {
    const text = new TextDecoder().decode(init.headers["content-encoding"] === "gzip" ? (await import("node:zlib")).gunzipSync(init.body) : init.body);
    wire.push({ body: JSON.parse(text), bytes: text.length });
    return { status: 202, headers: { get: () => null }, text: async () => "{}" };
  }) as any,
  store: { markShipped: async () => {}, markRejected: async () => {}, markFailed: async () => {} },
});
const items = [
  S.itemForTurnRow(row(), cfg),
  S.itemForTurnRow(row({ status: "error", error: "overloaded_error: try later", problemMessage: "where is my order" }), cfg),
  S.itemForTurnRow(row({ status: "blocked", error: "The answer was blocked." }), cfg),
  S.itemForTurnRow(row({ handedOff: true, toolCalls: 1, toolStats: [{ name: "request_human", ok: true, ms: 10 }] }), cfg),
  S.itemForTurnRow(row({ userId: "anonymous", userRole: null, conversationId: "" , turnNumber: null }), cfg),
  S.itemForTurnRow(row({ rating: 1, ratingAt: "2026-10-21T08:05:00Z" }), cfg),
  S.itemForTurnRow(row({ rating: -1, ratingNote: "wrong", ratingAt: "2026-10-21T08:06:00Z", toolErrors: 1, toolStats: [{ name: "get_order", ok: false, ms: 9 }] }), cfg),
  S.itemForHandoff({ id: "22222222-2222-4222-8222-222222222222", conversationId: "conv-1", agentId: "support", status: "open", createdAt: "2026-10-21T08:00:00Z" }),
  S.itemForHandoff({ id: "22222222-2222-4222-8222-222222222222", conversationId: "conv-1", agentId: "support", status: "resolved", createdAt: "2026-10-21T08:00:00Z", resolvedAt: "2026-10-21T08:20:00Z" }),
].filter(Boolean) as any[];

console.log("a batch the app really produces");
{
  await shipper.send(items);
  eqJson(wire.length, 1, "one request");
  const { body, bytes } = wire[0];
  eqJson(validateBatch(body, bytes), [], "it meets every rule of the contract");
  eqJson(body.events.map((e: any) => e.type), ["turn", "turn", "turn", "turn", "turn", "turn", "rating", "turn", "rating", "handoff", "handoff"], "turns, ratings and hand-offs, in order");
  const turns = body.events.filter((e: any) => e.type === "turn");
  eqJson(turns.map((e: any) => e.status), ["ok", "error", "blocked", "ok", "ok", "ok", "ok"], "ok, error and blocked turns");
  eqJson(turns[3].handedOff, true, "a hand-off turn says so");
  ok(turns.every((e: any) => /^[0-9a-f]{24}$/.test(e.userKey) && e.tools.length <= 20), "every person is a 24-hex key, every turn at most 20 tools");
  ok(new Set(body.events.map((e: any) => e.id)).size === body.events.length, "every event id is its own");
  ok(!JSON.stringify(body).includes("person-"), "no raw person id anywhere");
  eqJson(turns[4].turnNumber, 1, "a turn with no known number is the first");
  ok(turns[4].conversationId.length > 0, "and with no conversation still has a conversation id");
  const generated = ["env", "role", "userKey"].map((k) => new Set(turns.map((e: any) => JSON.stringify(e[k]))).size > 0);
  ok(generated.every(Boolean), "the fields the platform splits by are all present");
}

console.log("a batch at the limits is still valid");
{
  const events = Array.from({ length: 500 }, (_, i) => S.buildTurnEvent(row({ toolStats: Array.from({ length: 25 }, (_, k) => ({ name: "n".repeat(120), ok: true, ms: k })) }), { ...cfg, includeText: true })!);
  eqJson(validateBatch({ schema: 1, events }), [], "500 events, each with its tools cut to 20 and names to 80");
}

// ── the checker itself ────────────────────────────────────────────────────

console.log("the checker catches every rule being broken");
{
  const good = () => JSON.parse(JSON.stringify(wire[0].body));
  const first = (b: any) => b.events[0];
  const flaws: Array<[string, (b: any) => void, RegExp]> = [
    ["a userKey that is not hex", (b) => { first(b).userKey = "Zebra-not-hex-at-all-xx"; }, /userKey/],
    ["a userKey that is too short", (b) => { first(b).userKey = "abc123"; }, /userKey/],
    ["21 tools", (b) => { first(b).tools = Array.from({ length: 21 }, () => ({ name: "t", ok: true, ms: 1 })); }, /at most 20/],
    ["a tool carrying its input", (b) => { first(b).tools[0].input = { email: "x" }; }, /unknown field "input"/],
    ["an id with a space", (b) => { first(b).id = "has a space in it"; }, /id must be/],
    ["an id that is too short", (b) => { first(b).id = "short"; }, /id must be/],
    ["an id that is too long", (b) => { first(b).id = "x".repeat(65); }, /id must be/],
    ["a time that is not ISO", (b) => { first(b).at = "21/10/2026"; }, /ISO/],
    ["a negative token count", (b) => { first(b).inputTokens = -1; }, /inputTokens/],
    ["a fractional duration", (b) => { first(b).ms = 12.5; }, /ms must be/],
    ["an unknown status", (b) => { first(b).status = "fine"; }, /status/],
    ["a turn number of 0", (b) => { first(b).turnNumber = 0; }, /turnNumber/],
    ["a role over 60 characters", (b) => { first(b).role = "r".repeat(61); }, /role/],
    ["a problem message over 200 characters", (b) => { b.events[1].problem.message = "m".repeat(201); }, /message/],
    ["a problem reason nobody knows", (b) => { b.events[1].problem.reason = "weird"; }, /reason/],
    ["a field the platform does not know (a leak)", (b) => { first(b).email = "a@b.c"; }, /unknown field "email"/],
    ["a missing field", (b) => { delete first(b).userKey; }, /missing field "userKey"/],
    ["a rating of 5", (b) => { b.events.find((e: any) => e.type === "rating").rating = 5; }, /rating must be 1 or -1/],
    ["a rating note over 300", (b) => { b.events.find((e: any) => e.type === "rating").note = "n".repeat(301); }, /note/],
    ["a hand-off with a status of its own", (b) => { b.events.find((e: any) => e.type === "handoff").status = "stuck"; }, /status/],
    ["the wrong schema number", (b) => { b.schema = 2; }, /schema must be 1/],
    ["an event of an unknown type", (b) => { first(b).type = "click"; }, /type must be/],
    ["more than 500 events", (b) => { b.events = Array.from({ length: 501 }, () => first(good())); }, /more than 500/],
    ["no events", (b) => { b.events = []; }, /at least one/],
  ];
  for (const [label, damage, expect] of flaws) {
    const b = good();
    damage(b);
    const problems = validateBatch(b);
    ok(problems.length > 0 && problems.some((p) => expect.test(p)), `${label} is refused`);
  }
  ok(validateBatch(good(), 1_000_001).some((p) => /1 MB/.test(p)), "a body over 1 MB is refused");
  ok(validateBatch(null).length > 0 && validateBatch([]).length > 0 && validateBatch("x").length > 0, "something that is not a batch at all is refused");
}

done("insights contract");
