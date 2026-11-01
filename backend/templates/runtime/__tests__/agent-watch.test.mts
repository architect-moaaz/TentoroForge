/**
 * Watching the real chat live, from the SHIPPED files in templates/runtime/agents/.
 *
 * What is pinned: the feed is inert in production and with nobody watching, records only while someone watches,
 * replays a chat to a watcher who joins late, keeps a bounded amount, and forgets everything when the last watcher
 * leaves; the observer changes nothing about the chat (same answers, same errors) and only reports; the runtime says
 * where it is (input check, memory, with a person, answer check) for whoever is watching.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();

const watch = await import("../agents/watch.ts");
const { runAgent } = await import("../agents/runtime.ts");
const { memoryStore } = await import("../agents/memory.ts");

const usage = { inputTokens: 100, outputTokens: 20 };
const user = { id: "u1", role: "Support", email: "pat@example.test" };

function reset() {
  watch.resetFeed();
  process.env.NODE_ENV = "development";
}

console.log("the feed is inert unless someone watches, and never in production");
{
  reset();
  ok(!watch.watching(), "nobody watching: nothing is recorded");
  watch.publish("r1", Date.now(), { type: "text", content: "hi" });
  const seen: any[] = [];
  const stop = watch.subscribe((e) => seen.push(e));
  eqJson(seen.length, 0, "and an event from before anyone watched is not kept");
  ok(watch.watching(), "with a watcher it is on");
  watch.publish("r1", Date.now() - 50, { type: "text", content: "hello" });
  eqJson([seen.length, seen[0].type, seen[0].runId, seen[0].t >= 50], [1, "text", "r1", true], "an event reaches the watcher, stamped with its run and how long into it");
  stop();
  ok(!watch.watching(), "and it is off again when the watcher leaves");

  process.env.NODE_ENV = "production";
  const stop2 = watch.subscribe(() => seen.push("x"));
  ok(!watch.watching(), "in production it is never on, even with a watcher");
  watch.publish("r2", Date.now(), { type: "text", content: "secret" });
  eqJson(seen.length, 1, "so nothing is sent");
  stop2();
  reset();
}

console.log("a watcher who joins late sees the chat from its start, and the last one to leave wipes it");
{
  reset();
  const a: any[] = [];
  const stopA = watch.subscribe((e) => a.push(e));
  const t0 = Date.now();
  watch.publish("r1", t0, { type: "run_start", agentId: "a", agentName: "A", user: { id: "u1", name: "Lena", role: "Support", email: null }, message: "hello", conversationId: null });
  watch.publish("r1", t0, { type: "text", content: "Hi there" });
  const late: any[] = [];
  const stopLate = watch.subscribe((e) => late.push(e));
  eqJson(late.map((e) => e.type), ["run_start", "text"], "the late watcher is replayed what it missed, in order");
  watch.publish("r1", t0, { type: "done", conversationId: "c1", tokens: { input: 1, output: 1 }, turns: 1 } as any);
  eqJson([a.at(-1).type, late.at(-1).type], ["done", "done"], "and both get what comes next");
  stopA();
  const still: any[] = [];
  const stopStill = watch.subscribe((e) => still.push(e));
  ok(still.length === 3, "one watcher leaving keeps the record for the others");
  stopLate();
  stopStill();
  const after: any[] = [];
  const stopAfter = watch.subscribe((e) => after.push(e));
  eqJson(after.length, 0, "when the last leaves, everything is forgotten: the next watcher starts clean");
  stopAfter();
  reset();
}

console.log("what it keeps is bounded");
{
  reset();
  const got: any[] = [];
  const stop = watch.subscribe((e) => got.push(e));
  for (let i = 0; i < 20; i++) watch.publish(`run-${i}`, 1_000 + i, { type: "text", content: "x" });
  const replay: any[] = [];
  const stop2 = watch.subscribe((e) => replay.push(e));
  const runs = new Set(replay.map((e) => e.runId));
  ok(runs.size <= 12 && runs.has("run-19") && !runs.has("run-0"), "only the latest runs are kept");
  for (let i = 0; i < 900; i++) watch.publish("long", 5_000, { type: "text", content: "y" });
  const replay2: any[] = [];
  const stop3 = watch.subscribe((e) => replay2.push(e));
  ok(replay2.filter((e) => e.runId === "long").length <= 600, "and only so many events of one run");
  stop(); stop2(); stop3();
  reset();
}

console.log("a tool's result goes to the watcher whole, unlike the customer's own stream");
{
  const big = watch.feedEvent({ type: "tool_result", id: "t", tool: "x", ok: true, result: { data: [{ a: 1 }] } } as any) as any;
  eqJson([big.result, big.chars > 0, big.cut], [{ data: [{ a: 1 }] }, true, false], "the result, its size, and not cut");
  eqJson((watch.feedEvent({ type: "text", content: "x" } as any) as any).content, "x", "other events are as they are");
}

// ── the observer ──────────────────────────────────────────────────────────

function fakeBase(over: Record<string, unknown> = {}): any {
  let n = 0;
  return {
    store: memoryStore(),
    async runTool(spec: any) { return { name: spec.name, rows: [1, 2] }; },
    async callModel(_r: any, onText: (c: string) => void) {
      if (n++ === 0) return { content: [{ type: "tool_use", id: "a", name: "list_x", input: {} }], usage };
      onText("done");
      return { content: [{ type: "text", text: "done" }], usage };
    },
    ...over,
  };
}
const config = (over: Record<string, unknown> = {}): any => ({
  id: "a", name: "A", enabled: true, model: { maxTokens: 64 }, systemPrompt: "You help.",
  tools: [{ name: "list_x", description: "d", kind: "data", entity: "x", operation: "list", inputSchema: { type: "object", properties: {} } }],
  memory: { type: "conversation", maxMessages: 12, summarizeAfter: 40 },
  guardrails: { input: { maxLength: 500, blockPatterns: [], requireAuth: true }, output: { blockPatterns: [], contentFilter: "standard" }, outputRules: [] },
  maxTurns: 4, ui: { title: "A", position: "bottom-right" }, ...over,
});
async function run(deps: any, message = "go", cfg = config(), conversationId: string | null = null) {
  const events: any[] = [];
  await runAgent(cfg, { message, conversationId, user, cookie: "", origin: "" }, deps, (e: any) => events.push(e));
  return events;
}

console.log("the observer changes nothing about the chat");
{
  const plainEvents = await run(fakeBase());
  const sent: any[] = [];
  const observed = observeWith(sent);
  const watchedEvents = await run(observed);
  eqJson(watchedEvents.map((e) => e.type), plainEvents.map((e) => e.type), "the same events, in the same order");
  eqJson(watchedEvents.find((e) => e.type === "tool_result").result, plainEvents.find((e) => e.type === "tool_result").result, "the same tool results");
  eqJson(watchedEvents.filter((e) => e.type === "text").map((e) => e.content).join(""), plainEvents.filter((e) => e.type === "text").map((e) => e.content).join(""), "the same words");
}

function observeWith(sent: any[]) {
  return watch.observeDeps(fakeBase(), (e) => sent.push(e));
}

console.log("it announces each model call before and after, with time and tokens");
{
  const sent: any[] = [];
  await run(observeWith(sent));
  const kinds = sent.map((e) => e.type);
  eqJson(kinds.filter((k) => k === "model_start" || k === "model_call"), ["model_start", "model_call", "model_start", "model_call"], "start then result, for each call");
  const start = sent.find((e) => e.type === "model_start");
  eqJson([start.n, start.tools, start.systemChars], [1, 1, "You help.".length], "what it is about to send: how many messages and tools, how long the instructions");
  const call = sent.find((e) => e.type === "model_call");
  eqJson([call.n, call.inputTokens, call.outputTokens, call.toolsRequested], [1, 100, 20, ["list_x"]], "and what came back: tokens, and the tools it chose");
  ok(kinds.indexOf("model_start") < kinds.indexOf("model_call"), "in that order");
}

console.log("a model failure is reported and still fails the chat as before");
{
  const sent: any[] = [];
  const failing = watch.observeDeps(fakeBase({ async callModel() { throw new Error("overloaded"); } }), (e) => sent.push(e));
  const events = await run(failing);
  ok(events.some((e) => e.type === "error"), "the chat reports its error as ever");
  const failed = sent.find((e) => e.type === "model_failed");
  eqJson([failed.n, failed.error], [1, "overloaded"], "and the watcher is told why");
}

console.log("the runtime says where it is");
{
  const sent: any[] = [];
  await run(observeWith(sent));
  const phases = sent.filter((e) => e.type === "phase").map((e) => e.phase);
  eqJson(phases, ["input_check", "memory", "output_check"], "check the message, load memory, check the answer, in order");
  eqJson(sent.find((e) => e.phase === "memory").messages, 0, "how much it remembered");
  ok(sent.find((e) => e.phase === "input_check").ok === true && sent.find((e) => e.phase === "output_check").ok === true, "and whether each check passed");

  const blocked: any[] = [];
  const b = await run(watch.observeDeps(fakeBase(), (e) => blocked.push(e)), "x".repeat(600));
  eqJson(blocked.filter((e) => e.type === "phase").map((e) => [e.phase, e.ok]), [["input_check", false]], "a refused message stops at the first check, and says so");
  ok(/too long/.test(blocked.find((e) => e.phase === "input_check").reason) && b[0].type === "blocked", "with why");

  const unseen: any[] = [];
  const cfgBad = config({ guardrails: { input: { maxLength: 500, blockPatterns: [], requireAuth: true }, output: { blockPatterns: ["done"], contentFilter: "standard" }, outputRules: [] } });
  await run(watch.observeDeps(fakeBase(), (e) => unseen.push(e)), "go", cfgBad);
  const out = unseen.find((e) => e.phase === "output_check");
  eqJson(out.ok, false, "an answer that fails its check is reported as failed");

  const handed: any[] = [];
  const store = memoryStore();
  const cid = await store.createConversation("a", user.id);
  const withPerson = watch.observeDeps(fakeBase({ store, handoffs: { async openFor() { return { ref: "HO-1", status: "open", assignedToName: null }; } } }), (e) => handed.push(e));
  await run(withPerson, "go", config(), cid);
  eqJson(handed.filter((e) => e.type === "phase").map((e) => e.phase), ["input_check", "memory", "with_person"], "a chat that is with a person says so, and stops there");
  eqJson(handed.find((e) => e.phase === "with_person").ref, "HO-1", "with its reference");
}

console.log("a normal chat, with nothing observing, is untouched");
{
  const events = await run(fakeBase());
  ok(events.at(-1).type === "done" && !events.some((e) => e.type === "error"), "no trace hook, no problem");
}

console.log("watching only one role, or one person");
{
  reset();
  const start = (runId: string, id: string, role: string | null, name = "x") =>
    watch.publish(runId, Date.now(), { type: "run_start", agentId: "a", agentName: "A", user: { id, name, role, email: null }, message: `hello from ${name}`, conversationId: null });
  const say = (runId: string, content: string) => watch.publish(runId, Date.now(), { type: "text", content });

  const everyone: any[] = [];
  const stopEveryone = watch.subscribe((e) => everyone.push(e));
  const admins: any[] = [];
  const stopAdmins = watch.subscribe((e) => admins.push(e), { role: "admin" });
  const lena: any[] = [];
  const stopLena = watch.subscribe((e) => lena.push(e), { userId: "u-lena" });

  start("r1", "u-lena", "Support", "Lena");
  say("r1", "lena's chat");
  start("r2", "u-ada", "Admin", "Ada");
  say("r2", "ada's chat");
  start("r3", "u-anon", null, "Visitor");
  say("r3", "a visitor's chat");

  eqJson(everyone.filter((e) => e.type === "run_start").length, 3, "no filter: every chat");
  eqJson(admins.map((e) => e.runId), ["r2", "r2"], "a role: only the chats of people holding it (whatever its capitals), start and the rest");
  ok(!admins.some((e) => e.content === "lena's chat" || e.content === "a visitor's chat"), "and never another role's, nor a visitor's");
  eqJson(lena.map((e) => e.runId), ["r1", "r1"], "a person: only theirs");

  const lateAdmin: any[] = [];
  const stopLate = watch.subscribe((e) => lateAdmin.push(e), { role: "Admin" });
  eqJson(lateAdmin.map((e) => e.runId), ["r2", "r2"], "a watcher joining late is replayed only what its filter allows");

  const personOverRole: any[] = [];
  const stopBoth = watch.subscribe((e) => personOverRole.push(e), { role: "Admin", userId: "u-lena" });
  eqJson([...new Set(personOverRole.map((e) => e.runId))], ["r1"], "a person outranks a role");

  const nobody: any[] = [];
  const stopNobody = watch.subscribe((e) => nobody.push(e), { role: "Janitor" });
  say("r2", "more from ada");
  eqJson(nobody.length, 0, "a role nobody holds sees nothing");
  eqJson(admins.at(-1).content, "more from ada", "and what comes later in a watched chat still arrives");

  ok(watch.matchesFilter({ id: "1", role: "Admin" }, {}) && watch.matchesFilter(null, {}), "no filter matches anyone, signed in or not");
  ok(!watch.matchesFilter(null, { role: "Admin" }) && !watch.matchesFilter({ id: "1", role: null }, { role: "Admin" }), "a role filter never matches someone with no role");
  stopEveryone(); stopAdmins(); stopLena(); stopLate(); stopBoth(); stopNobody();
  reset();
}

done("watching the real chat live");
