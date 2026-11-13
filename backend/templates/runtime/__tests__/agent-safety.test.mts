/**
 * Confirm-before-changing and per-person limits, run from the SHIPPED files in templates/runtime/agents/.
 *
 * What is pinned: a tool that changes data does not run the first time it is called; it runs only when the person
 * pressed Go ahead on THAT hold (the button sends the hold's id) and the very same call is made in that turn; words
 * typed in the chat release nothing, in any language; Cancel refuses it; the assistant cannot confirm for the person
 * inside one reply; a different input is a new question; holds survive between requests and lapse; a plain read is
 * never held. And: messages per minute and hour and tokens per day stop a person with a
 * friendly reason before anything is saved or paid for; 0 means unlimited; a counter that cannot be read means
 * "not limited"; talking to a person on the team is never limited.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();

const { gate, actionKey, stableStringify, confirmSignalOf, HOLD_MINUTES } = await import("../agents/confirm.ts");
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

console.log("a button press is read from the request, and nothing else is");
{
  eqJson(confirmSignalOf({ holdId: "abcdef12-3456", decision: "confirm" }), { holdId: "abcdef12-3456", decision: "confirm" }, "a Go ahead press is read");
  eqJson(confirmSignalOf({ holdId: "abcdef12-3456", decision: "cancel" })?.decision, "cancel", "and so is Cancel");
  for (const bad of [undefined, null, "yes", 1, {}, { decision: "confirm" }, { holdId: "abcdef12", decision: "yes" }, { holdId: "short", decision: "confirm" },
    { holdId: "has a space in it", decision: "confirm" }, { holdId: 12345678, decision: "confirm" }, { holdId: "abcdef12", decision: "CONFIRM" }]) {
    eqJson(confirmSignalOf(bad), null, `${JSON.stringify(bad)} is not a press`);
  }
}

const press = (holdId: string, decision: "confirm" | "cancel" = "confirm") => ({ holdId, decision });

console.log("gate: a change is held, then released only by the person's button on the turn after");
{
  const spec = write();
  const input = { id: "t1", data: { status: "closed" } };
  const state: any = { turn: 1, holds: [] };
  const first: any = gate(state, spec, input, { now: 1000 });
  ok(first.run === false && first.held?.held === true, "the first call is held");
  ok(first.held.message.includes("update ticket") && first.held.message.includes('"status":"closed"'), "and says exactly what it would do");
  ok(typeof first.held.holdId === "string" && first.held.holdId.length >= 8, "under an id that the person's button press will carry");
  ok(/Go ahead button/.test(first.held.message) && /Typing yes does not count/.test(first.held.message), "the assistant is told only the button counts, so it never asks for a typed yes");
  eqJson(state.holds.length, 1, "one hold is kept");
  const id = first.held.holdId;

  const again: any = gate(state, spec, input, { now: 1100, confirm: press(id) });
  ok(again.run === false && again.held, "calling it again in the SAME turn is held again, press or not: it cannot confirm for the person");
  eqJson([again.held.holdId, state.holds.length], [id, 1], "under the same id (the one the person was shown), and still one hold");

  state.turn = 2;
  const ack: any = gate(state, spec, input, { now: 2000, confirm: press(id) });
  eqJson(ack.run, true, "next turn, same call, the person pressed Go ahead on it: it runs");
  eqJson(state.holds.length, 0, "and the hold is used up");

  const replay: any = gate(state, spec, input, { now: 2100, confirm: press(id) });
  ok(replay.run === false && replay.held, "running it a second time needs a new press");
}

console.log("gate: words typed release nothing, in any language");
{
  const spec = write();
  const input = { id: "t1", data: { status: "closed" } };
  const state: any = { turn: 1, holds: [] };
  const id1 = (gate(state, spec, input, { now: 1000 }) as any).held.holdId;
  // The next turn is the person TYPING "yes please" (or "sure", "oui", "kinda"): the request carries no press.
  state.turn = 2;
  const typed: any = gate(state, spec, input, { now: 2000 });
  ok(typed.run === false && typed.held, "the same call after a typed yes is held again: only a press counts");
  ok(typed.held.holdId !== id1, "as a new question, under a new id");
  state.turn = 3;
  const old: any = gate(state, spec, input, { now: 3000, confirm: press(id1) });
  ok(old.run === false && old.held, "a press for the earlier question no longer answers it");
  const id3 = old.held.holdId;
  state.turn = 4;
  eqJson(gate(state, spec, input, { now: 4000, confirm: press(id3) }).run, true, "a press for the question it is now asking does");
}

console.log("gate: Cancel, someone else's id, a different input, a lapse and an old hold");
{
  const spec = write();
  const input = { id: "t1", data: { status: "closed" } };
  const hold = (): [any, string] => {
    const s: any = { turn: 1, holds: [] };
    const id = (gate(s, spec, input, { now: 1000 }) as any).held.holdId;
    s.turn = 2;
    return [s, id];
  };

  let [state, id] = hold();
  const no: any = gate(state, spec, input, { now: 2000, confirm: press(id, "cancel") });
  ok(no.run === false && /cancelled/.test(no.refused), "Cancel is refused, and the assistant is told nothing changed");
  eqJson(state.holds.length, 0, "and the hold is gone");

  [state, id] = hold();
  const other: any = gate(state, spec, input, { now: 2000, confirm: press("00000000-0000-4000-8000-000000000000") });
  ok(other.run === false && other.held, "a press carrying some other id releases nothing");

  [state, id] = hold();
  const changed: any = gate(state, spec, { id: "t1", data: { status: "open" } }, { now: 2000, confirm: press(id) });
  ok(changed.run === false && changed.held, "a changed input is a new question, even right after a press");

  [state, id] = hold();
  state.turn = 3; // a turn in between: the press was not for this
  const stale: any = gate(state, spec, input, { now: 3000, confirm: press(id) });
  ok(stale.run === false && stale.held, "a hold only lasts until the next turn: after a detour it is asked again");

  [state, id] = hold();
  const late: any = gate(state, spec, input, { now: 1000 + (HOLD_MINUTES + 1) * 60_000, confirm: press(id) });
  ok(late.run === false && late.held, "and it lapses after " + HOLD_MINUTES + " minutes");

  const legacy: any = { turn: 2, holds: [{ tool: spec.name, key: actionKey(spec.name, input), summary: "x", at: 1000, turn: 1 }] };
  const kept: any = gate(legacy, spec, input, { now: 2000, confirm: press("abcdef12-3456") });
  ok(kept.run === false && kept.held, "a hold kept from before holds had ids can only be asked again");
}

console.log("gate: only tools that change data are held");
{
  const state: any = { turn: 1, holds: [] };
  eqJson(gate(state, read(), {}, { now: 1 }).run, true, "a read runs at once");
  eqJson(gate(state, write({ confirm: false }), {}, { now: 1 }).run, true, "a write switched to 'no need to ask' runs at once");
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

async function run(config: any, message: string, deps: any, conversationId: string | null = null, confirm: any = null) {
  const events: any[] = [];
  await runAgent(config, { message, confirm, conversationId, user, cookie: "", origin: "" }, deps, (e: any) => events.push(e));
  return events;
}

/** The id the chat was given for the change a request held. */
const heldId = (events: any[]): string => events.find((e: any) => e.type === "tool_result" && e.result?.held)?.result.holdId;

console.log("the loop: held first, run only after the person presses Go ahead, across separate requests");
{
  const store = memoryStore();
  const ran: any[] = [];
  const input = { id: "t1", data: { status: "closed" } };
  const model = scriptedModel(["call", "talk", "call", "talk", "call", "talk", "call", "talk"], input);
  const deps: any = { store, ...model, async runTool(_s: any, i: any) { ran.push(i); return { ok: true }; } };
  const cfg = baseConfig([write()]);

  const a = await run(cfg, "please close ticket t1", deps);
  const cid = a.at(-1).conversationId;
  eqJson(ran.length, 0, "the first request changes nothing");
  const held = a.find((e: any) => e.type === "tool_result");
  ok(held.ok === true && held.result.held === true, "the chat is told the change is waiting");
  ok(typeof heldId(a) === "string", "with the id its buttons answer");
  ok(model.seenResults.some((r) => r.includes("Nothing has been changed yet")), "and so is the model, in words it can pass on");

  const b = await run(cfg, "yes go ahead", deps, cid);
  eqJson(ran.length, 0, "a typed yes changes nothing: the assistant calls it again and it is held again");
  ok(b.some((e: any) => e.type === "tool_result" && e.result?.held === true) && heldId(b) !== heldId(a), "as a new question, with a new id for the buttons");

  const stale = await run(cfg, "Yes, go ahead.", deps, cid, press(heldId(a)));
  eqJson(ran.length, 0, "a press for the earlier question releases nothing");

  const cid2 = stale.at(-1).conversationId;
  const c = await run(cfg, "Yes, go ahead.", deps, cid2, press(heldId(stale)));
  eqJson(ran.length, 1, "after the person presses Go ahead on the question that is open, the same call runs");
  eqJson(ran[0], input, "with exactly that input");
  ok(c.some((e: any) => e.type === "tool_result" && e.ok === true && !e.result?.held), "and the chat sees it done");
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

console.log("the loop: Cancel, and a store that cannot keep holds");
{
  const store = memoryStore();
  const ran: any[] = [];
  const input = { id: "t1", data: { status: "closed" } };
  const model = scriptedModel(["call", "talk", "call", "talk"], input);
  const deps: any = { store, ...model, async runTool(_s: any, i: any) { ran.push(i); return { ok: true }; } };
  const cfg = baseConfig([write()]);
  const a = await run(cfg, "close t1", deps);
  const b = await run(cfg, "No, cancel that.", deps, a.at(-1).conversationId, press(heldId(a), "cancel"));
  eqJson(ran.length, 0, "Cancel means it never runs");
  ok(b.some((e: any) => e.type === "tool_result" && e.ok === false && /cancelled/.test(e.error)), "and the assistant is told why");

  const dumb = memoryStore();
  const noState: any = { store: { ...dumb, getState: undefined, setState: undefined }, ...scriptedModel(["call", "talk", "call", "talk"], input), async runTool(_s: any, i: any) { ran.push(i); return { ok: true }; } };
  const c1 = await run(cfg, "close t1", noState);
  await run(cfg, "Yes, go ahead.", noState, c1.at(-1).conversationId, press(heldId(c1)));
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
