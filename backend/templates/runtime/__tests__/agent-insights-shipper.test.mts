/**
 * Sending every assistant turn to the platform: the SHIPPED agents/insights-shipper.ts, with the network, the clock, the
 * timers and the database faked.
 *
 * What is pinned: events are built exactly as the platform's contract says for every kind of turn, and nothing private
 * leaves by default; they are sent in ONE request when 100 are waiting or 1 second has passed, never more than 500
 * events or 1 MB per request, gzipped when large; 202 marks rows sent; a slow platform (429, 5xx, no answer) is
 * backed off from with jitter and Retry-After, and loses nothing; a refused batch is split so one bad event closes only
 * itself; a throwing or hanging network never fails or delays the caller; the queue in memory is bounded; an app that is
 * not set up does nothing; and ratings and hand-offs are sent as their own events.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { gunzipSync } from "node:zlib";
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { validateBatch } from "./_insights-contract.mts";

installHarness();
const S = await import("../agents/insights-shipper.ts");

// ── a world the test steers: a fake network, a fake clock, a fake database ──

const SALT = "salt-for-tests-0123456789abcdef";
const goodEnv = { FORGE_INSIGHTS_URL: "https://platform.test/api/insights/ingest", FORGE_INSIGHTS_KEY: "fik_" + "k".repeat(40), FORGE_INSIGHTS_USER_SALT: SALT, NODE_ENV: "production" };

type Reply = { status: number; headers?: Record<string, string>; body?: unknown } | "throw" | "hang" | "throw-sync";

function world(env: Record<string, string> = goodEnv, opts: { random?: number } = {}) {
  const clock = { t: 1_700_000_000_000 };
  const timers: Array<{ at: number; fn: () => void; live: boolean }> = [];
  const setTimer = (fn: () => void, ms: number) => {
    const t = { at: clock.t + ms, fn, live: true };
    timers.push(t);
    return () => { t.live = false; };
  };
  /** Move the clock, running every timer that comes due on the way. */
  const advance = async (ms: number) => {
    const end = clock.t + ms;
    for (;;) {
      const next = timers.filter((t) => t.live && t.at <= end).sort((a, b) => a.at - b.at)[0];
      if (!next) break;
      clock.t = Math.max(clock.t, next.at);
      next.live = false;
      next.fn();
      await new Promise((r) => setTimeout(r, 15));
    }
    clock.t = end;
  };
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  const calls: Array<{ at: number; url: string; headers: Record<string, string>; bytes: number; sentBytes: number; body: any; gzipped: boolean }> = [];
  let reply: (call: (typeof calls)[number], n: number) => Reply = () => ({ status: 202, body: { accepted: 1, duplicates: 0, rejected: [], serverTime: "x" } });
  const fetch = async (url: string, init: any) => {
    const raw: Uint8Array = init.body;
    const gz = init.headers["content-encoding"] === "gzip";
    const text = new TextDecoder().decode(gz ? gunzipSync(raw) : raw);
    const call = { at: clock.t, url, headers: init.headers, bytes: new TextEncoder().encode(text).byteLength, sentBytes: raw.byteLength, body: JSON.parse(text), gzipped: gz };
    calls.push(call);
    const r = reply(call, calls.length);
    if (r === "throw-sync") throw new Error("fetch exploded");
    if (r === "throw") return Promise.reject(new Error("ECONNRESET"));
    if (r === "hang") return new Promise(() => {});
    return { status: r.status, headers: { get: (k: string) => r.headers?.[k.toLowerCase()] ?? null }, text: async () => JSON.stringify(r.body ?? {}) };
  };

  const store = {
    shipped: new Set<string>(),
    rejected: new Map<string, string>(),
    failed: new Map<string, number>(),
    reasons: [] as string[],
    async markShipped(items: any[]) { for (const i of items) store.shipped.add(i.rowId); },
    async markRejected(items: any[], reason: string) { for (const i of items) store.rejected.set(i.rowId, reason); },
    async markFailed(items: any[], reason: string) { for (const i of items) store.failed.set(i.rowId, (store.failed.get(i.rowId) ?? 0) + 1); store.reasons.push(reason); },
  };
  const lines: string[] = [];
  const shipper = S.createShipper({ env, fetch: fetch as any, store, now: () => clock.t, setTimer, random: () => opts.random ?? 0.5, log: (l: string) => lines.push(l) });
  return { clock, calls, store, lines, shipper, advance, sleep, reply: (f: typeof reply) => { reply = f; } };
}

const cfg = { salt: SALT, includeText: false, env: "production" as const };
let seq = 0;
const uuid = () => `00000000-0000-4000-8000-${String(++seq).padStart(12, "0")}`;
const baseRow = (over: Record<string, unknown> = {}): any => ({
  id: uuid(), conversationId: "conv-0000-0001", agentId: "support", userId: "user-42", userRole: "Admin", model: "claude-answered",
  inputTokens: 20, outputTokens: 10, ms: 2250, status: "ok", error: null, toolCalls: 1, toolErrors: 0,
  toolStats: [{ name: "get_order", ok: true, ms: 250 }], handedOff: false, turnNumber: 3, rating: null, ratingNote: null, ratingAt: null,
  problemMessage: null, createdAt: new Date("2026-10-20T10:00:00.000Z"), ...over,
});
const itemOf = (over: Record<string, unknown> = {}) => S.itemForTurnRow(baseRow(over), cfg)!;
const ids = (calls: Array<{ body: any }>) => calls.flatMap((c) => c.body.events.map((e: any) => e.id));

// ── the events are what the contract says ─────────────────────────────────

console.log("a turn that went fine");
{
  const row = baseRow();
  const e = S.buildTurnEvent(row, cfg)!;
  eqJson(validateBatch({ schema: 1, events: [e] }), [], "the event meets every rule of the contract");
  eqJson(
    [e.type, e.id, e.at, e.agentId, e.conversationId, e.role, e.env, e.model, e.inputTokens, e.outputTokens, e.ms, e.status, e.toolCalls, e.toolErrors, e.handedOff, e.turnNumber, e.problem],
    ["turn", row.id, "2026-10-20T10:00:00.000Z", "support", "conv-0000-0001", "Admin", "production", "claude-answered", 20, 10, 2250, "ok", 1, 0, false, 3, null],
    "every field is the turn's own",
  );
  eqJson(e.tools, [{ name: "get_order", ok: true, ms: 250 }], "tools carry the name, whether it worked and how long: nothing else");
  ok(/^[0-9a-f]{24}$/.test(e.userKey), "the person is 24 hex characters");
}

console.log("a turn that failed, was blocked, handed over, was slow, or had a failing tool");
{
  const cases: Array<[string, Record<string, unknown>, string, string]> = [
    ["failed", { status: "error", error: "overloaded_error: user 42 not found" }, "error", "The turn failed."],
    ["blocked", { status: "blocked", error: "Mentioned a password" }, "blocked", "The answer was blocked."],
    ["handed over", { handedOff: true }, "handed_off", "Handed over to a person."],
    ["slow", { ms: 45_000 }, "slow", "It took 45 seconds."],
    ["a failing tool", { toolErrors: 1, toolStats: [{ name: "get_order", ok: false, ms: 5 }, { name: "get_order", ok: false, ms: 6 }] }, "tool_failed", "A tool failed: get_order."],
    ["thumbs down", { rating: -1, ratingNote: "wrong date" }, "thumbs_down", "The person marked the answer as bad."],
  ];
  for (const [label, over, reason, detail] of cases) {
    const e = S.buildTurnEvent(baseRow(over), cfg)!;
    eqJson([e.problem?.reason, e.problem?.detail, e.problem?.message], [reason, detail, null], `${label}: reason ${reason}, a generic sentence, no words of anyone's`);
    eqJson(validateBatch({ schema: 1, events: [e] }), [], `${label}: valid`);
  }
  const worst = S.buildTurnEvent(baseRow({ status: "error", error: "x" }), cfg)!;
  eqJson([worst.status], ["error"], "the status is the turn's");
  eqJson(S.buildTurnEvent(baseRow({ status: "weird" }), cfg)!.status, "ok", "a status nobody knows is not invented as a failure");
  const order = S.buildTurnEvent(baseRow({ status: "error", error: "e", handedOff: true, toolErrors: 2, ms: 99_999, rating: -1 }), cfg)!;
  eqJson(order.problem?.reason, "error", "when several things are wrong the worst one is named");
}

console.log("what leaves the app: no raw id, no email, no tool data, no words — unless allowed");
{
  const row = baseRow({
    userId: "alice@example.com", conversationId: "c-9999-9999", error: "Key (email)=(alice@example.com) already exists", status: "error",
    toolStats: [{ name: "get_order", ok: false, ms: 3, input: { email: "alice@example.com" }, result: { secret: "hunter2" } }],
    toolErrors: 1, problemMessage: "please delete bob@example.com", ratingNote: "alice is unhappy", rating: -1, ratingAt: "2026-10-20T11:00:00Z",
  });
  const item = S.itemForTurnRow(row, cfg)!;
  const wire = JSON.stringify(item.events);
  ok(!/alice|example\.com|hunter2|bob|unhappy|Key \(email\)/.test(wire), "no email, tool input, tool result, error text, message or note by default");
  ok(!wire.includes("alice@example.com") && /"userKey":"[0-9a-f]{24}"/.test(wire), "the person is only a hash");
  eqJson(item.events.length, 2, "a rated turn sends the turn and its rating");
  const on = S.itemForTurnRow(row, { ...cfg, includeText: true })!;
  const onWire = JSON.stringify(on.events);
  ok(onWire.includes("please delete bob@example.com") && onWire.includes("alice is unhappy"), "with FORGE_INSIGHTS_INCLUDE_TEXT=1 the words of the person are included");
  ok(!onWire.includes("hunter2") && !onWire.includes('"input"'), "and still no tool data");
  const withText = S.buildTurnEvent({ ...row, problemMessage: "m".repeat(500), error: "e".repeat(500) }, { ...cfg, includeText: true })!;
  ok(withText.problem!.message!.length === 200 && withText.problem!.detail!.length === 200, "text is cut to 200 characters");
  eqJson(validateBatch({ schema: 1, events: on.events }), [], "the batch with text is valid too");
}

console.log("the person's key");
{
  const k = (salt: string, userId: string, conversationId = "c1") => S.userKeyOf(salt, { userId, conversationId });
  eqJson(k("s", "u1"), k("s", "u1"), "the same person in the same app is always the same key");
  ok(k("s", "u1") !== k("s", "u2"), "another person is another key");
  ok(k("s", "u1") !== k("other-salt", "u1"), "the same id under another salt is another key");
  ok(/^[0-9a-f]{24}$/.test(k("s", "u1")), "24 hex characters");
  ok(k("s", "anonymous", "c1") !== k("s", "anonymous", "c2") && k("s", "anonymous", "c1") === k("s", "anonymous", "c1"), "a visitor who is not signed in is one visitor per conversation");
  ok(k("s", "anonymous", "c1") !== k("s", "u1"), "and is nobody's real id");
  const { createHmac } = await import("node:crypto");
  eqJson(k("s", "u1"), createHmac("sha256", "s").update("u1").digest("hex").slice(0, 24), "it is exactly HMAC-SHA256(salt, id), first 24 hex characters");
}

console.log("a row that cannot be told truthfully");
{
  eqJson(S.buildTurnEvent(baseRow({ createdAt: null }), cfg), null, "no time: no event");
  eqJson(S.buildTurnEvent(baseRow({ createdAt: "not a date" }), cfg), null, "a time that is no time: no event");
  const old = S.buildTurnEvent(baseRow({ turnNumber: null, inputTokens: null, ms: -5, toolStats: "x", userRole: null, model: null, agentId: "", conversationId: "" }), cfg)!;
  eqJson([old.turnNumber, old.inputTokens, old.ms, old.tools, old.role, old.model, old.agentId, old.conversationId], [1, 0, 0, [], null, null, "unknown", "none"], "an old row with empty columns is filled in honestly");
  eqJson(validateBatch({ schema: 1, events: [old] }), [], "and is still valid");
  const many = S.buildTurnEvent(baseRow({ toolStats: Array.from({ length: 30 }, (_, i) => ({ name: "t".repeat(200) + i, ok: true, ms: 1 })) }), cfg)!;
  eqJson([many.tools.length, many.tools[0].name.length], [20, 80], "at most 20 tools, names cut to 80");
}

console.log("rating and hand-off events");
{
  const r1 = S.buildRatingEvent({ turnId: "t-1234-5678", rating: 1, note: null, ratingAt: "2026-10-20T10:05:00Z" }, cfg)!;
  const r2 = S.buildRatingEvent({ turnId: "t-1234-5678", rating: -1, note: "x", ratingAt: "2026-10-20T10:06:00Z" }, cfg)!;
  eqJson([r1.turnId, r2.turnId, r1.id !== r2.id, r2.rating, r2.note], ["t-1234-5678", "t-1234-5678", true, -1, null], "a changed mind is a new event for the same turn (the note only with text allowed)");
  eqJson(validateBatch({ schema: 1, events: [r1, r2] }), [], "ratings are valid");
  eqJson(S.buildRatingEvent({ turnId: "t-1234-5678", rating: 0, note: null, ratingAt: "2026-10-20T10:05:00Z" }, cfg), null, "no rating, no event");

  const made = new Date("2026-10-20T10:00:00Z");
  const open = S.buildHandoffEvent({ id: uuid(), conversationId: "conv-1", agentId: "support", status: "open", createdAt: made })!;
  const claimed = S.buildHandoffEvent({ id: "h-1", conversationId: "conv-1", agentId: "support", status: "claimed", createdAt: made, claimedAt: new Date("2026-10-20T10:03:00Z") })!;
  const resolved = S.buildHandoffEvent({ id: "h-1", conversationId: "conv-1", agentId: "support", status: "resolved", createdAt: made, claimedAt: new Date("2026-10-20T10:03:00Z"), resolvedAt: new Date("2026-10-20T10:30:30Z") })!;
  eqJson([open.status, open.resolveMinutes, claimed.at, claimed.resolveMinutes, resolved.resolveMinutes], ["open", null, "2026-10-20T10:03:00.000Z", null, 30.5], "open, claimed and resolved, with how long it took");
  ok(claimed.id !== resolved.id && claimed.id.startsWith("ho_h-1_claimed"), "each change has its own id, so none is counted twice or missed");
  eqJson(validateBatch({ schema: 1, events: [open, claimed, resolved] }), [], "hand-off events are valid");
  eqJson(S.buildHandoffEvent({ id: "h-1", conversationId: "c", agentId: "a", status: "resolved", createdAt: made }), null, "resolved with no time it was resolved: nothing true to say");
}

console.log("the settings");
{
  eqJson(S.readConfig({}).config, null, "nothing set: off");
  eqJson(S.readConfig({ FORGE_INSIGHTS_URL: "ftp://x", FORGE_INSIGHTS_KEY: "k", FORGE_INSIGHTS_USER_SALT: "s" }).config, null, "an address that is not a web address: off");
  ok(/SALT/.test(S.readConfig({ FORGE_INSIGHTS_URL: "https://x", FORGE_INSIGHTS_KEY: "k" }).reason ?? ""), "without a salt: off, and it says why");
  const c = S.readConfig({ ...goodEnv, FORGE_INSIGHTS_INCLUDE_TEXT: "1", NODE_ENV: "development" }).config!;
  eqJson([c.includeText, c.env], [true, "development"], "text allowed only with the flag, and the environment is told apart");
  eqJson(S.readConfig({ ...goodEnv, FORGE_INSIGHTS_INCLUDE_TEXT: "true" }).config!.includeText, false, "only 1 switches text on");
}

// ── sending ───────────────────────────────────────────────────────────────

console.log("sent as one request at 100 events, or after 1 second");
{
  const w = world();
  for (let i = 0; i < 99; i++) w.shipper.enqueue(itemOf());
  await w.sleep(20);
  eqJson(w.calls.length, 0, "99 waiting events send nothing yet");
  w.shipper.enqueue(itemOf());
  await w.shipper.flush();
  eqJson([w.calls.length, w.calls[0]?.body.events.length], [1, 100], "the 100th sends ALL of them in ONE request");
  eqJson(w.store.shipped.size, 100, "and a 202 marks every row sent");

  const t = world();
  t.shipper.enqueue(itemOf());
  await t.advance(999);
  eqJson(t.calls.length, 0, "one event is not sent at 999 ms");
  await t.advance(1);
  await t.shipper.flush();
  eqJson(t.calls.length, 1, "it is at 1 second");
  t.shipper.enqueue(itemOf());
  t.shipper.enqueue(itemOf());
  await t.advance(1000);
  await t.shipper.flush();
  eqJson([t.calls.length, t.calls[1].body.events.length], [2, 2], "events that arrive within the second go together");
  const c = t.calls[0];
  eqJson([c.url, c.headers.authorization, c.headers["content-type"], c.body.schema], [goodEnv.FORGE_INSIGHTS_URL, `Bearer ${goodEnv.FORGE_INSIGHTS_KEY}`, "application/json", 1], "to the platform's address with the key, schema 1");
  eqJson(validateBatch(c.body, c.bytes), [], "the request meets the contract");
}

console.log("never more than 500 events or 1 MB in a request");
{
  const w = world();
  const items = Array.from({ length: 1200 }, () => itemOf());
  const r = await w.shipper.send(items);
  eqJson(w.calls.map((c) => c.body.events.length), [500, 500, 200], "1200 events go as 500, 500 and 200");
  eqJson([r.done, r.deferred], [1200, 0], "all taken");
  eqJson(new Set(ids(w.calls)).size, 1200, "every event once");

  const big = (i: number) => S.itemForTurnRow(baseRow({ toolStats: Array.from({ length: 20 }, (_, k) => ({ name: `tool_${"n".repeat(70)}_${k}`, ok: false, ms: 99999 })), toolErrors: 20, status: "error", error: "e".repeat(400), problemMessage: "m".repeat(400) }), { ...cfg, includeText: true })!;
  const w2 = world();
  const heavy = Array.from({ length: 500 }, (_, i) => big(i));
  await w2.shipper.send(heavy);
  ok(w2.calls.length > 1, "500 heavy events do not fit one request");
  ok(w2.calls.every((c) => c.bytes <= 1_000_000 && c.body.events.length <= 500), `no request is over 1 MB (largest ${Math.max(...w2.calls.map((c) => c.bytes))} bytes)`);
  eqJson(new Set(ids(w2.calls)).size, 500, "and all 500 arrive");
  eqJson(w2.calls.flatMap((c) => validateBatch(c.body, c.bytes)), [], "each request meets the contract");
}

console.log("gzip when large");
{
  const w = world();
  w.shipper.enqueue(itemOf());
  await w.advance(1000);
  await w.shipper.flush();
  eqJson([w.calls[0].gzipped, w.calls[0].bytes < 1024], [false, true], "one small event is sent as it is");
  const w2 = world();
  for (let i = 0; i < 30; i++) w2.shipper.enqueue(itemOf());
  await w2.advance(1000);
  await w2.shipper.flush();
  ok(w2.calls[0].gzipped && w2.calls[0].bytes > 1024 && w2.calls[0].sentBytes < w2.calls[0].bytes, "a body over 1 KB is gzipped (and the platform can read it)");
  eqJson(w2.calls[0].body.events.length, 30, "with all its events");
}

console.log("a 202 says what was refused");
{
  const w = world();
  const a = itemOf(), b = itemOf(), c = itemOf();
  w.reply(() => ({ status: 202, body: { accepted: 2, duplicates: 0, rejected: [{ index: 1, reason: "too old" }], rejectedCount: 1 } }));
  await w.shipper.send([a, b, c]);
  eqJson([w.store.shipped.has(a.rowId), w.store.shipped.has(b.rowId), w.store.shipped.has(c.rowId)], [true, false, true], "the refused one is not marked sent");
  eqJson(w.store.rejected.get(b.rowId), "refused: too old", "it is closed with the platform's reason, and never retried");
  eqJson(w.calls.length, 1, "in the one request");
}

console.log("429, 5xx and no answer: back off, lose nothing");
{
  const w = world(goodEnv, { random: 1 });
  const a = itemOf();
  w.shipper.enqueue(a);
  let n = 0;
  w.reply(() => (n++ < 7 ? { status: 503 } : { status: 202 }));
  const waits: number[] = [];
  await w.advance(1000);
  await w.shipper.flush();
  let last = w.calls[0].at;
  for (let i = 0; i < 8 && w.calls.length < 8; i++) {
    const before = w.calls.length;
    for (let step = 0; step < 70 && w.calls.length === before; step++) await w.advance(1000);
    if (w.calls.length > before) { waits.push(w.calls.at(-1)!.at - last); last = w.calls.at(-1)!.at; }
    await w.shipper.flush();
  }
  eqJson(waits.slice(0, 7), [1000, 2000, 4000, 8000, 16000, 32000, 60000], "after each failure it waits twice as long, up to 60 seconds (jitter at its top here)");
  eqJson([w.store.shipped.has(a.rowId), w.store.rejected.size], [true, 0], "and once the platform is back the event is taken: nothing was lost or closed");
  ok((w.store.failed.get(a.rowId) ?? 0) >= 5, "each failure was counted against the row");
  ok(w.lines.filter((l) => /could not|answered 503/.test(l)).length === 1 && w.lines.some((l) => /reachable again/.test(l)), "the log says it once, and says when it is over");

  const j = world(goodEnv, { random: 0 });
  j.shipper.enqueue(itemOf());
  j.reply(() => ({ status: 500 }));
  await j.advance(1000);
  await j.shipper.flush();
  eqJson(j.shipper.stats().backoffUntil - j.clock.t, 500, "the wait has jitter: between half and all of the step");

  const cap = world(goodEnv, { random: 1 });
  cap.reply(() => ({ status: 500 }));
  const x = itemOf();
  for (let i = 0; i < 12; i++) {
    cap.shipper.enqueue(i === 0 ? x : itemOf());
    await cap.advance(61_000);
    await cap.shipper.flush();
  }
  ok(cap.shipper.stats().backoffUntil - cap.clock.t <= 60_000, "never longer than 60 seconds");
}

console.log("Retry-After is respected");
{
  const w = world(goodEnv, { random: 0 });
  const a = itemOf();
  w.shipper.enqueue(a);
  let n = 0;
  w.reply(() => (n++ === 0 ? { status: 429, headers: { "retry-after": "20" } } : { status: 202 }));
  await w.advance(1000);
  await w.shipper.flush();
  eqJson(w.calls.length, 1, "a 429 is one request");
  await w.advance(19_000);
  eqJson(w.calls.length, 1, "nothing again before the 20 seconds are up (the jittered 500 ms alone would have been sooner)");
  await w.advance(1000);
  await w.shipper.flush();
  eqJson([w.calls.length, w.store.shipped.has(a.rowId)], [2, true], "then it tries again and is taken");
  const d = world(goodEnv, { random: 0 });
  d.shipper.enqueue(itemOf());
  d.reply(() => ({ status: 429, headers: { "retry-after": new Date(d.clock.t + 30_000).toUTCString() } }));
  await d.advance(1000);
  await d.shipper.flush();
  ok(d.shipper.stats().backoffUntil - d.clock.t >= 28_000, "a Retry-After given as a date works too");
}

console.log("a network that throws or hangs never fails or delays the caller");
{
  for (const mode of ["throw", "throw-sync"] as const) {
    const w = world();
    w.reply(() => mode);
    const a = itemOf();
    let threw = false;
    try {
      w.shipper.enqueue(a);
      await w.advance(1000);
      await w.shipper.flush();
      await w.shipper.settle();
    } catch { threw = true; }
    eqJson([threw, w.store.shipped.size, w.store.rejected.size], [false, 0, 0], `${mode}: nothing thrown, nothing marked sent, nothing closed`);
    ok(w.shipper.stats().queued === 1, `${mode}: the event waits in the queue`);
  }
  const w = world();
  w.reply(() => "hang");
  const t0 = Date.now();
  w.shipper.enqueue(itemOf());
  ok(Date.now() - t0 < 50, "enqueue returns at once");
  await w.advance(1000);
  let finished = false;
  const flushing = w.shipper.flush().then(() => { finished = true; });
  await w.sleep(30);
  ok(!finished, "a request that never answers is still open at 2.9 seconds...");
  await w.advance(S.REQUEST_TIMEOUT_MS - 1);
  await w.sleep(20);
  ok(!finished, "(just under the timeout)");
  await w.advance(1);
  await flushing;
  ok(finished, "...and counts as failed at 3 seconds");
  eqJson([w.store.shipped.size, w.shipper.stats().queued], [0, 1], "the event is kept");
  ok(w.lines.length === 1 && /did not answer in time/.test(w.lines[0]), "one line in the log");
}

console.log("a refused batch: only the bad event is closed, the rest are sent");
{
  const w = world();
  const items = Array.from({ length: 20 }, () => itemOf());
  const bad = items[7];
  w.reply((call) => (call.body.events.some((e: any) => e.id === bad.rowId) ? { status: 400 } : { status: 202 }));
  const r = await w.shipper.send(items);
  eqJson([...w.store.rejected.keys()], [bad.rowId], "the one event the platform refused is closed");
  ok(/refused/.test(w.store.rejected.get(bad.rowId) ?? ""), "with a reason");
  eqJson([w.store.shipped.size, r.deferred, r.done], [19, 0, 20], "the other 19 are sent");
  ok(w.calls.length <= 12, `found in a handful of requests (${w.calls.length})`);
  eqJson(w.shipper.stats().failures, 0, "and it is not treated as an outage");

  const s = world();
  const many = Array.from({ length: 50 }, () => itemOf());
  s.reply(() => ({ status: 400 }));
  const res = await s.shipper.send(many);
  ok(s.store.rejected.size <= 5, `a platform that refuses EVERYTHING does not get the backlog closed one by one (${s.store.rejected.size} closed)`);
  ok(res.deferred > 40 && res.backoffMs !== null, "the rest wait, and it backs off");
}

console.log("a wrong key or address keeps every turn");
{
  for (const status of [401, 403, 404]) {
    const w = world();
    const a = itemOf();
    w.reply(() => ({ status }));
    w.shipper.enqueue(a);
    await w.advance(1000);
    await w.shipper.flush();
    eqJson([w.store.rejected.size, w.shipper.stats().queued], [0, 1], `${status}: nothing closed, the turn waits for the setting to be fixed`);
    ok(w.lines.some((l) => /FORGE_INSIGHTS_KEY/.test(l) && !l.includes(goodEnv.FORGE_INSIGHTS_KEY)), `${status}: the log says what to check, and never prints the key`);
  }
}

console.log("the queue in memory is bounded and loses nothing from the database");
{
  const w = world();
  w.reply(() => ({ status: 503 }));
  w.shipper.enqueue(itemOf());
  await w.advance(1000);
  await w.shipper.flush();
  for (let i = 0; i < S.QUEUE_LIMIT + 50; i++) w.shipper.enqueue(itemOf());
  eqJson(w.shipper.stats().queued, S.QUEUE_LIMIT, "no more than the limit is held in memory");
  eqJson([w.store.rejected.size, w.store.shipped.size], [0, 0], "what did not fit is not closed or marked: its row stays in the database for the tick");
  ok(w.lines.filter((l) => /too many turns/.test(l)).length === 1, "and the log says so once");
}

console.log("not set up: silent, and nothing is sent");
{
  for (const [label, env, why] of [
    ["no address or key", {}, /not connected/],
    ["no salt", { FORGE_INSIGHTS_URL: goodEnv.FORGE_INSIGHTS_URL, FORGE_INSIGHTS_KEY: goodEnv.FORGE_INSIGHTS_KEY }, /SALT/],
  ] as const) {
    const w = world(env as any);
    ok(!w.shipper.configured(), `${label}: not configured`);
    for (let i = 0; i < 5; i++) w.shipper.enqueueFrom(() => itemOf());
    w.shipper.enqueue(itemOf());
    await w.advance(5000);
    await w.shipper.flush();
    await w.shipper.settle();
    const r = await w.shipper.send([itemOf()]);
    eqJson([w.calls.length, w.shipper.stats().queued, r.done], [0, 0, 0], `${label}: no request, nothing queued`);
    ok(w.lines.length === 1 && why.test(w.lines[0]) && !/fik_/.test(w.lines[0]), `${label}: exactly one log line, naming what is missing`);
  }
}

console.log("sending a turn from the queue after the outbox gave it up");
{
  const w = world();
  const first = itemOf();
  w.shipper.enqueue(first);
  await w.advance(1000);
  await w.shipper.flush();
  eqJson([...w.store.shipped], [first.rowId], "an event sent once is marked once");
  await w.shipper.send([first]);
  eqJson(ids(w.calls).filter((i) => i === first.rowId).length, 2, "sending it again is allowed (at-least-once): the platform ignores the repeat by its id");
}

console.log("tracked writes are waited for, then sent (hosts that freeze after the reply)");
{
  const w = world();
  let release: () => void = () => {};
  w.shipper.track(new Promise<void>((r) => { release = () => { w.shipper.enqueue(itemOf()); r(); }; }));
  let settled = false;
  const s = w.shipper.settle().then(() => { settled = true; });
  await w.sleep(20);
  ok(!settled && w.calls.length === 0, "settle waits for the write that is in flight");
  release();
  await s;
  eqJson(w.calls.length, 1, "then sends what that write queued, without waiting for the 1-second timer");
  const failing = world();
  failing.shipper.track(Promise.reject(new Error("db down")));
  await failing.shipper.settle();
  ok(true, "a write that failed does not break settle");
}

console.log("holdForShipping: only where the process may freeze, and never the chat's problem");
{
  const never = new Promise<void>(() => {});
  const mk = (configured: boolean) => { const calls = { settle: 0 }; return { calls, shipper: { configured: () => configured, settle: () => { calls.settle++; return never; } } }; };
  const timers = (list: Array<() => void>) => (fn: () => void) => { list.push(fn); return () => {}; };

  let m = mk(false);
  await S.holdForShipping(m.shipper, { VERCEL: "1" });
  eqJson(m.calls.settle, 0, "not set up: does nothing");
  m = mk(true);
  await S.holdForShipping(m.shipper, {});
  eqJson(m.calls.settle, 0, "on a server that keeps running: does nothing, the queue's own timer sends");
  m = mk(true);
  await S.holdForShipping(m.shipper, { VERCEL: "1" }, { keepAlive: async () => true });
  eqJson(m.calls.settle, 1, "on Vercel with its keep-running hook: starts the send and returns at once (the host waits for it)");
  m = mk(true);
  const fire: Array<() => void> = [];
  let returned = false;
  const held = S.holdForShipping(m.shipper, { AWS_LAMBDA_FUNCTION_NAME: "f" }, { keepAlive: async () => false, setTimer: timers(fire), holdMs: 2000 }).then(() => { returned = true; });
  await new Promise((r) => setTimeout(r, 20));
  ok(!returned, "with no hook it holds the stream's close for a moment...");
  fire.forEach((f) => f());
  await held;
  ok(returned, "...but only for a moment: a send that never finishes does not hold the reply for ever");
  m = mk(true);
  await S.holdForShipping({ configured: () => true, settle: () => { throw new Error("boom"); } } as any, { VERCEL: "1" });
  ok(true, "and a failure inside is swallowed");
  eqJson([S.freezesAfterReply({}), S.freezesAfterReply({ VERCEL: "1" }), S.freezesAfterReply({ FORGE_INSIGHTS_FLUSH_PER_REQUEST: "1" })], [false, true, true], "which hosts count as freezing");
}

done("insights shipper");
