/**
 * The builder's live run, from the SHIPPED files in templates/runtime/agents/.
 *
 * What is pinned: a debug conversation is remembered between messages (a "yes" finds the held change) and forgotten
 * after an hour; the secret is compared without leaking; a tool known to change data is NOT run unless the builder
 * said so, and the assistant is told plainly; a read always runs; limits and handoffs stay out of a test; every
 * model call is timed and counted; and a huge result is cut for the screen and said to be.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();

const { debugDeps, describeAgent, sameSecret, sessionStore, wireResult, MAX_RESULT_WIRE_CHARS } = await import("../agents/debug.ts");
const { changesData } = await import("../agents/confirm.ts");
const { runAgent } = await import("../agents/runtime.ts");
const { memoryStore } = await import("../agents/memory.ts");

const usage = { inputTokens: 100, outputTokens: 20 };
const user = { id: "u1", role: "Support Agent", email: "pat@example.test" };

const tool = (over: Record<string, unknown>): any => ({
  name: "t", description: "d", kind: "data", inputSchema: { type: "object", properties: {} }, ...over,
});

console.log("what counts as a change");
{
  ok(changesData(tool({ kind: "data", operation: "update" })), "an update");
  ok(changesData(tool({ kind: "data", operation: "create" })) && changesData(tool({ kind: "data", operation: "delete" })), "a create and a delete");
  ok(!changesData(tool({ kind: "data", operation: "list" })) && !changesData(tool({ kind: "data", operation: "get" })), "a list and a get are reads");
  ok(changesData(tool({ kind: "api", method: "post" })) && !changesData(tool({ kind: "api", method: "GET" })) && !changesData(tool({ kind: "api" })), "an api call by its method");
  ok(changesData(tool({ kind: "workflow" })), "a workflow is an action");
  ok(!changesData(tool({ kind: "function" })) && !changesData(tool({ kind: "mcp" })), "a function or MCP tool is not judged");
}

console.log("sessions");
{
  const a = sessionStore("s1", 1_000);
  ok(sessionStore("s1", 2_000) === a, "the same id gets the same conversation, so a follow-up finds what came before");
  ok(sessionStore("s2", 2_000) !== a, "another id gets its own");
  const later = sessionStore("s1", 1_000 + 61 * 60_000);
  ok(later !== a, "after an hour it is forgotten");
  for (let i = 0; i < 80; i++) sessionStore(`many-${i}`, 5_000_000 + i);
  ok(sessionStore("many-79", 5_000_100) !== undefined, "and the number kept is capped, newest first");
}

console.log("the secret");
{
  ok(sameSecret("abc123", "abc123"), "the same secret matches");
  ok(!sameSecret("abc123", "abc124") && !sameSecret("abc123", "abc12") && !sameSecret("abc123", ""), "anything else does not");
  ok(!sameSecret("", ""), "and an empty secret never does");
}

console.log("what the builder is shown");
{
  const d: any = describeAgent({
    id: "a", name: "A", model: { maxTokens: 1, name: "m" }, systemPrompt: "You help.", maxTurns: 4,
    tools: [tool({ name: "list_x", operation: "list" }), tool({ name: "set_x", operation: "update", confirm: true }), tool({ name: "request_human", kind: "handoff" })],
  } as any);
  eqJson(d.systemPrompt, "You help.", "the prompt exactly as the model gets it");
  eqJson(d.tools.map((t: any) => [t.name, t.changes]), [["list_x", false], ["set_x", true], ["request_human", true]], "each tool, and whether it changes anything");
  const w = wireResult({ rows: [1, 2, 3] });
  ok(w.cut === false && w.chars > 0, "a small result goes whole");
  const big = wireResult({ blob: "x".repeat(MAX_RESULT_WIRE_CHARS + 500) });
  ok(big.cut === true && big.chars > MAX_RESULT_WIRE_CHARS && String(big.result).length <= MAX_RESULT_WIRE_CHARS + 2, "a huge one is cut, and says how big it was");
}

// ── the instrumented loop ─────────────────────────────────────────────────

function baseDeps(ran: string[], over: Record<string, unknown> = {}): any {
  let n = 0;
  return {
    store: memoryStore(),
    usage: { async read() { throw new Error("usage must not be touched"); }, async add() { throw new Error("usage must not be touched"); } },
    handoffs: { async openFor() { throw new Error("handoffs must not be touched"); } },
    async runTool(spec: any) { ran.push(spec.name); return { rows: [{ id: "1" }] }; },
    async callModel(_r: any, onText: (c: string) => void) {
      if (n++ === 0) {
        return { content: [{ type: "tool_use", id: "a", name: "list_x", input: {} }, { type: "tool_use", id: "b", name: "set_x", input: { id: "1", data: { s: 1 } } }], usage };
      }
      onText("done");
      return { content: [{ type: "text", text: "done" }], usage };
    },
    ...over,
  };
}
const config = (): any => ({
  id: "a", name: "A", enabled: true, model: { maxTokens: 64 }, systemPrompt: "You help.",
  tools: [tool({ name: "list_x", operation: "list" }), tool({ name: "set_x", operation: "update", confirm: false })],
  memory: { type: "conversation", maxMessages: 12, summarizeAfter: 40 },
  guardrails: { input: { maxLength: 500, blockPatterns: [], requireAuth: true }, output: { blockPatterns: [], contentFilter: "standard" }, outputRules: [] },
  maxTurns: 4, ui: { title: "A", position: "bottom-right" },
});

async function run(allowChanges: boolean) {
  const ran: string[] = [];
  const extra: any[] = [];
  const events: any[] = [];
  const deps = debugDeps(baseDeps(ran), (e) => extra.push(e), { allowChanges });
  await runAgent(config(), { message: "go", conversationId: null, user, cookie: "", origin: "" }, deps, (e: any) => events.push(e));
  return { ran, extra, events, deps };
}

console.log("a debug run does not change anything unless asked to");
{
  const { ran, extra, events } = await run(false);
  eqJson(ran, ["list_x"], "the read ran, the update did not");
  eqJson(extra.filter((e) => e.type === "tool_faked").map((e) => e.tool), ["set_x"], "and the screen is told which one was held back, and why");
  ok(/changes data/.test(extra.find((e) => e.type === "tool_faked").reason), "in words");
  const faked = events.find((e: any) => e.type === "tool_result" && e.tool === "set_x");
  ok(faked.ok === true && /Not run/.test(faked.result.debug_note) && faked.result.would_have_run_with.id === "1", "the assistant is told plainly it was not run, and with what");
  ok(events.at(-1).type === "done", "and the run carries on to the end");
}

console.log("with 'run changes for real' on, it runs");
{
  const { ran, extra } = await run(true);
  eqJson(ran, ["list_x", "set_x"], "both ran");
  eqJson(extra.filter((e) => e.type === "tool_faked").length, 0, "nothing was held back");
}

console.log("every model call is timed and counted");
{
  const { extra } = await run(true);
  const calls = extra.filter((e) => e.type === "model_call");
  eqJson(calls.map((c) => c.n), [1, 2], "numbered in order");
  eqJson(calls[0].toolsRequested, ["list_x", "set_x"], "what the model asked for at each step");
  eqJson([calls[0].inputTokens, calls[0].outputTokens], [100, 20], "with its tokens");
  ok(typeof calls[0].ms === "number" && calls[0].ms >= 0 && calls[0].messages >= 1, "and its time and how many messages it was given");
}

console.log("a test does not use anyone's allowance or page a person");
{
  const { deps } = await run(false);
  eqJson([deps.usage, deps.handoffs], [undefined, undefined], "limits and handoffs are out of it (the base deps would have thrown)");
}

console.log("a handoff tool is never run for real in a test unless allowed");
{
  const ran: string[] = [];
  const cfg = config();
  cfg.tools = [tool({ name: "request_human", kind: "handoff" })];
  let n = 0;
  const base = baseDeps(ran, {
    async callModel(_r: any, onText: (c: string) => void) {
      if (n++ === 0) return { content: [{ type: "tool_use", id: "h", name: "request_human", input: { reason: "x" } }], usage };
      onText("ok"); return { content: [{ type: "text", text: "ok" }], usage };
    },
  });
  const extra: any[] = [];
  await runAgent(cfg, { message: "a person please", conversationId: null, user, cookie: "", origin: "" }, debugDeps(base, (e) => extra.push(e), { allowChanges: false }), () => {});
  eqJson(ran, [], "no handoff was created");
  ok(/hand the conversation to a person/.test(extra.find((e) => e.type === "tool_faked").reason), "and it says why");
}

done("the builder's live run");
