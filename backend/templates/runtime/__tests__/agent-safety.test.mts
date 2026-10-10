/**
 * Confirm-before-changing and per-person limits, run from the SHIPPED files in templates/runtime/agents/.
 *
 * What is pinned: a tool that changes data does not run the first time it is called; it runs only when the very
 * same call is made in the turn after the person replied, and that reply is not a "no"; the assistant cannot
 * confirm for the person inside one reply; a different input is a new question; holds survive between requests
 * and lapse; a plain read is never held. And: messages per minute and hour and tokens per day stop a person with a
 * friendly reason before anything is saved or paid for; 0 means unlimited; a counter that cannot be read means
 * "not limited"; talking to a person on the team is never limited.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();

const { gate, actionKey, stableStringify, declined, HOLD_MINUTES } = await import("../agents/confirm.ts");
const { checkLimits, limitsOf, memoryUsage, DEFAULT_LIMITS } = await import("../agents/limits.ts");
const { runAgent } = await import("../agents/runtime.ts");
const { memoryStore } = await import("../agents/memory.ts");

const usage = { inputTokens: 10, outputTokens: 5 };
const user = { id: "u1", role: "Support Agent", email: "pat@example.test" };

const write = (over: Record<string, unknown> = {}): any => ({
  name: "update_ticket", description: "d", kind: "data", entity: "tickets", operation: "update", confirm: true,
  inputSchema: { type: "object", properties: { id: { type: "string" }, data: { type: "object" } } },
  ...over,
});
const read = (): any => ({
  name: "list_tickets", description: "d", kind: "data", entity: "tickets", operation: "list",
  inputSchema: { type: "object", properties: {} },
});

// ── the rule itself ───────────────────────────────────────────────────────

console.log("the same input always gives the same key");
{
  eqJson(stableStringify({ b: 1, a: { d: 2, c: [3, { z: 1, y: 2 }] } }), '{"a":{"c":[3,{"y":2,"z":1}],"d":2},"b":1}', "keys are sorted all the way down");
  ok(actionKey("t", { a: 1, b: 2 }) === actionKey("t", { b: 2, a: 1 }), "the order the model wrote them in does not matter");
  ok(actionKey("t", { a: 1 }) !== actionKey("t", { a: 2 }), "a different value is a different action");
  ok(actionKey("t", undefined) === actionKey("t", {}), "no input and an empty input are the same");
}

console.log("what counts as a no");
{
  for (const no of ["no", "No thanks", "nope", "cancel that", "don't", "dont do it", "wait, not that one", "never mind", "not now", "stop"]) ok(declined(no), `"${no}" is a no`);
  for (const yes of ["yes", "yes please", "go ahead", "ok do it", "sure", "yep, assign it to Maya", "nothing to add, proceed", "note: yes"]) ok(!declined(yes), `"${yes}" is not a no`);
}

console.log("gate: a change is held, then released only on the next turn");
{
  const spec = write();
  const input = { id: "t1", data: { status: "closed" } };
  const state: any = { turn: 1, holds: [] };
  const first: any = gate(state, spec, input, { now: 1000, reply: "close ticket t1" });
  ok(first.run === false && first.held?.held === true, "the first call is held");
  ok(first.held.message.includes("update ticket") && first.held.message.includes('"status":"closed"'), "and says exactly what it would do");
  eqJson(state.holds.length, 1, "one hold is kept");

  const again: any = gate(state, spec, input, { now: 1100, reply: "close ticket t1" });
  ok(again.run === false && again.held, "calling it again in the SAME turn is held again: it cannot confirm for the person");
  eqJson(state.holds.length, 1, "still one hold, not two");

  state.turn = 2;
  const ack: any = gate(state, spec, input, { now: 2000, reply: "yes please" });
  eqJson(ack.run, true, "next turn, same call, the person said yes: it runs");
  eqJson(state.holds.length, 0, "and the hold is used up");

  const replay: any = gate(state, spec, input, { now: 2100, reply: "yes please" });
  ok(replay.run === false && replay.held, "running it a second time needs a new yes");
}

console.log("gate: a no, a different input and a lapse");
{
  const spec = write();
  const input = { id: "t1", data: { status: "closed" } };
  let state: any = { turn: 1, holds: [] };
  gate(state, spec, input, { now: 1000, reply: "close it" });
  state.turn = 2;
  const no: any = gate(state, spec, input, { now: 2000, reply: "no, leave it open" });
  ok(no.run === false && /said no/.test(no.refused), "a no is refused, and the assistant is told nothing changed");
  eqJson(state.holds.length, 0, "and the hold is gone");

  state = { turn: 1, holds: [] };
  gate(state, spec, input, { now: 1000, reply: "close it" });
  state.turn = 2;
  const other: any = gate(state, spec, { id: "t1", data: { status: "open" } }, { now: 2000, reply: "yes" });
  ok(other.run === false && other.held, "a changed input is a new question, even right after a yes");

  state = { turn: 1, holds: [] };
  gate(state, spec, input, { now: 1000, reply: "close it" });
  state.turn = 3; // a turn in between: the yes was not for this
  const stale: any = gate(state, spec, input, { now: 3000, reply: "yes" });
  ok(stale.run === false && stale.held, "a hold only lasts until the next turn: after a detour it is asked again");

  state = { turn: 1, holds: [] };
  gate(state, spec, input, { now: 1000, reply: "close it" });
  state.turn = 2;
  const late: any = gate(state, spec, input, { now: 1000 + (HOLD_MINUTES + 1) * 60_000, reply: "yes" });
  ok(late.run === false && late.held, "and it lapses after " + HOLD_MINUTES + " minutes");
}

console.log("gate: only tools that change data are held");
{
  const state: any = { turn: 1, holds: [] };
  eqJson(gate(state, read(), {}, { now: 1, reply: "show them" }).run, true, "a read runs at once");
  eqJson(gate(state, write({ confirm: false }), {}, { now: 1, reply: "x" }).run, true, "a write switched to 'no need to ask' runs at once");
  eqJson(state.holds.length, 0, "and nothing is held for either");
}

// ── through the real loop ─────────────────────────────────────────────────

const baseConfig = (tools: any[], over: Record<string, unknown> = {}): any => ({
  id: "app_assistant", name: "Assistant", enabled: true, model: { maxTokens: 256 }, systemPrompt: "You help.",
  tools, memory: { type: "conversation", maxMessages: 12, summarizeAfter: 40 },
  guardrails: { input: { maxLength: 500, blockPatterns: [], requireAuth: true }, output: { blockPatterns: [], contentFilter: "standard" }, outputRules: [] },
  maxTurns: 4, ui: { title: "Assistant", position: "bottom-right" }, ...over,
});

/** A model that calls `update_ticket` with the same input whenever it is told to, and otherwise talks. */
function scriptedModel(script: Array<"call" | "talk">, input: Record<string, unknown>) {
  let step = 0;
  const seenResults: string[] = [];
  return {
    seenResults,
    async callModel(req: any, onText: (c: string) => void) {
      const last = req.messages.at(-1);
      if (Array.isArray(last?.content)) for (const b of last.content) if (b.type === "tool_result") seenResults.push(String(b.content));
      const what = script[Math.min(step++, script.length - 1)];
      if (what === "call" && !(Array.isArray(last?.content) && last.content.some((b: any) => b.type === "tool_result"))) {
        return { content: [{ type: "tool_use", id: `t${step}`, name: "update_ticket", input }], usage };
      }
      onText("ok");
      return { content: [{ type: "text", text: "ok" }], usage };
    },
  };
}

async function run(config: any, message: string, deps: any, conversationId: string | null = null) {
  const events: any[] = [];
  await runAgent(config, { message, conversationId, user, cookie: "", origin: "" }, deps, (e: any) => events.push(e));
  return events;
}

console.log("the loop: held first, run after the person says yes, across separate requests");
{
  const store = memoryStore();
  const ran: any[] = [];
  const input = { id: "t1", data: { status: "closed" } };
  const model = scriptedModel(["call", "talk", "call", "talk"], input);
  const deps: any = { store, ...model, async runTool(_s: any, i: any) { ran.push(i); return { ok: true }; } };
  const cfg = baseConfig([write()]);

  const a = await run(cfg, "please close ticket t1", deps);
  const cid = a.at(-1).conversationId;
  eqJson(ran.length, 0, "the first request changes nothing");
  const held = a.find((e: any) => e.type === "tool_result");
  ok(held.ok === true && held.result.held === true, "the chat is told the change is waiting");
  ok(model.seenResults.some((r) => r.includes("Nothing has been changed yet")), "and so is the model, in words it can pass on");

  const b = await run(cfg, "yes go ahead", deps, cid);
  eqJson(ran.length, 1, "after the person says yes, the same call runs");
  eqJson(ran[0], input, "with exactly that input");
  ok(b.some((e: any) => e.type === "tool_result" && e.ok === true && !e.result?.held), "and the chat sees it done");
}

console.log("the loop: the model cannot confirm for the person within one reply");
{
  const store = memoryStore();
  const ran: any[] = [];
  const input = { id: "t1", data: { status: "closed" } };
  let n = 0;
  const deps: any = {
    store, async runTool(_s: any, i: any) { ran.push(i); return { ok: true }; },
    async callModel(req: any, onText: (c: string) => void) {
      if (n++ < 3) return { content: [{ type: "tool_use", id: `t${n}`, name: "update_ticket", input }], usage };
      onText("done"); return { content: [{ type: "text", text: "done" }], usage };
    },
  };
  await run(baseConfig([write()], { maxTurns: 6 }), "close t1", deps);
  eqJson(ran.length, 0, "calling again and again in one reply never runs it");
}

console.log("the loop: a no, and a store that cannot keep holds");
{
  const store = memoryStore();
  const ran: any[] = [];
  const input = { id: "t1", data: { status: "closed" } };
  const model = scriptedModel(["call", "talk", "call", "talk"], input);
  const deps: any = { store, ...model, async runTool(_s: any, i: any) { ran.push(i); return { ok: true }; } };
  const cfg = baseConfig([write()]);
  const a = await run(cfg, "close t1", deps);
  const b = await run(cfg, "no, leave it", deps, a.at(-1).conversationId);
  eqJson(ran.length, 0, "a no means it never runs");
  ok(b.some((e: any) => e.type === "tool_result" && e.ok === false && /said no/.test(e.error)), "and the assistant is told why");

  const dumb = memoryStore();
  const noState: any = { store: { ...dumb, getState: undefined, setState: undefined }, ...scriptedModel(["call", "talk", "call", "talk"], input), async runTool(_s: any, i: any) { ran.push(i); return { ok: true }; } };
  const c1 = await run(cfg, "close t1", noState);
  await run(cfg, "yes", noState, c1.at(-1).conversationId);
  eqJson(ran.length, 0, "a store that cannot keep holds can never release one: it is asked about, never skipped");
}

console.log("the loop: reads and unmarked tools are not held");
{
  const ran: string[] = [];
  let n = 0;
  const deps: any = {
    store: memoryStore(), async runTool(s: any) { ran.push(s.name); return { rows: [] }; },
    async callModel(_r: any, onText: (c: string) => void) {
      if (n++ === 0) return { content: [{ type: "tool_use", id: "a", name: "list_tickets", input: {} }, { type: "tool_use", id: "b", name: "update_ticket", input: { id: "x" } }], usage };
      onText("ok"); return { content: [{ type: "text", text: "ok" }], usage };
    },
  };
  await run(baseConfig([read(), write({ confirm: undefined })]), "show and tidy", deps);
  eqJson(ran, ["list_tickets", "update_ticket"], "a read, and a write nobody marked, run straight away");
}

// ── limits ────────────────────────────────────────────────────────────────

console.log("limits: what is asked of whom");
{
  eqJson(limitsOf(undefined), DEFAULT_LIMITS, "nothing set: the defaults");
  eqJson(limitsOf({ perMinute: 3 }), { ...DEFAULT_LIMITS, perMinute: 3 }, "one set: the rest stay default");
  eqJson(limitsOf({ perHour: -5, tokensPerDay: Number.NaN } as any), DEFAULT_LIMITS, "nonsense is ignored, not obeyed");
  const l = { perMinute: 3, perHour: 10, tokensPerDay: 1000 };
  eqJson(checkLimits(l, { minute: 2, hour: 9, tokensDay: 999 }), null, "within every limit: fine");
  ok(/very quickly/.test(checkLimits(l, { minute: 3, hour: 3, tokensDay: 0 })!.reason!), "too many this minute: slow down");
  ok(/hourly/.test(checkLimits(l, { minute: 0, hour: 10, tokensDay: 0 })!.reason!), "too many this hour");
  ok(/daily/.test(checkLimits(l, { minute: 0, hour: 0, tokensDay: 1000 })!.reason!), "too many tokens today");
  eqJson(checkLimits({ perMinute: 0, perHour: 0, tokensPerDay: 0 }, { minute: 999, hour: 999, tokensDay: 9e9 }), null, "0 means no limit");
}

console.log("limits: through the loop");
{
  const calls = { model: 0 };
  const mk = (usageStore: any, store = memoryStore(), extra: any = {}) => ({
    store, usage: usageStore, runTool: async () => 0, ...extra,
    async callModel(_r: any, onText: (c: string) => void) { calls.model++; onText("hi"); return { content: [{ type: "text", text: "hi" }], usage }; },
  });
  const cfg = baseConfig([], { guardrails: { input: { maxLength: 500, blockPatterns: [], requireAuth: true }, output: { blockPatterns: [], contentFilter: "standard" }, outputRules: [], limits: { perMinute: 2, perHour: 0, tokensPerDay: 100 } } });

  const counts = memoryUsage();
  const store = memoryStore();
  const deps: any = mk(counts, store);
  const a = await run(cfg, "one", deps);
  const cid = a.at(-1).conversationId;
  await run(cfg, "two", deps, cid);
  eqJson(counts.totals.minute, 2, "each message is counted");
  eqJson(counts.totals.tokensDay, 30, "and the tokens each answer used");
  const modelCalls = calls.model;
  const over = await run(cfg, "three", deps, cid);
  eqJson(over.map((e: any) => e.type), ["blocked"], "past the minute limit the person is stopped with a reason");
  ok(/very quickly/.test(over[0].reason) && over[0].stage === "input", "a friendly one, shown like any other refusal");
  eqJson(calls.model, modelCalls, "no model call was made for it");
  eqJson((await store.listMessages(cid)).length, 4, "and nothing more was saved");
  eqJson(counts.totals.minute, 2, "a refused message is not counted as used");

  const heavy = memoryUsage({ tokensDay: 100 });
  const day = await run(cfg, "again", mk(heavy));
  ok(day.length === 1 && /daily/.test(day[0].reason), "a person over their daily tokens is stopped");

  const fresh = memoryStore();
  const none = await run(cfg, "again", mk(heavy, fresh));
  eqJson(Object.keys(fresh.dump()).length, 0, "and no empty conversation is left behind");
}

console.log("limits: a counter that fails, and people with a person on the team");
{
  const broken: any = { async read() { throw new Error('relation "forge_agent_usage" does not exist'); }, async add() { throw new Error("nope"); } };
  const deps: any = {
    store: memoryStore(), usage: broken, runTool: async () => 0,
    async callModel(_r: any, onText: (c: string) => void) { onText("hi"); return { content: [{ type: "text", text: "hi" }], usage }; },
  };
  const ev = await run(baseConfig([]), "hello", deps);
  ok(ev.some((e: any) => e.type === "text") && ev.at(-1).type === "done" && !ev.some((e: any) => e.type === "error" || e.type === "blocked"),
     "with no usage table nobody is limited and the chat carries on");

  const maxed = memoryUsage({ minute: 99, hour: 999, tokensDay: 9e9 });
  const store = memoryStore();
  const cid = await store.createConversation("app_assistant", user.id);
  const handed: any = {
    store, usage: maxed, runTool: async () => 0,
    handoffs: { async openFor() { return { ref: "HO-1", status: "open", assignedToName: null }; } },
    async callModel() { throw new Error("the model must not be called"); },
  };
  const ev2 = await run(baseConfig([]), "are you there?", handed, cid);
  ok(!ev2.some((e: any) => e.type === "blocked") && ev2.some((e: any) => e.type === "handoff"), "someone whose usage is maxed can still write to the person who has their conversation");
}

done("agent safety");
