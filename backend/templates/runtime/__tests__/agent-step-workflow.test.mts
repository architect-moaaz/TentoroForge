/**
 * An assistant step inside a real workflow run: the SHIPPED engine (workflows/engine.ts), the SHIPPED handler
 * (agents/workflow-step.ts) and the SHIPPED model/tool wiring (agents/io.ts), with only the outside world faked: the
 * Anthropic SDK, the app's data engine, its secrets, its list of assistants.
 *
 * What is pinned: the envelope reaches the steps after it under the step's id; onFailure human and skip complete the run
 * with an error envelope while fail fails it (and the engine does not mistake the envelope's `error` for a crash);
 * the execution log; a missing assistant; the stub an app without assistants has; a dry-run flag; and Watch live, which
 * stays inert unless someone watches.
 *
 * Run: __tests__/run-agent-step-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const g = globalThis as any;

installHarness({
  stubs: {
    "../feel-lite": "export const evaluateExpression = () => true;",
    "./types": "export default {};",
    "@/agents/registry": "export const AGENTS = globalThis.__agents;",
    "@/lib/integrations/resolver": "export async function getSecret(_p, k) { return k === 'ANTHROPIC_API_KEY' ? (globalThis.__key ?? '') : ''; }",
    "@anthropic-ai/sdk": `
      export default class Anthropic {
        constructor(o) { globalThis.__apiKeyUsed = o.apiKey; }
        messages = { stream: (req) => {
          globalThis.__requests.push(JSON.parse(JSON.stringify(req)));
          let cb = () => {};
          return { on: (_e, fn) => { cb = fn; }, finalMessage: async () => {
            const r = globalThis.__replies.shift() ?? { content: [{ type: 'text', text: '(no more replies)' }] };
            for (const b of r.content) if (b.type === 'text') cb(b.text);
            return { content: r.content, usage: { input_tokens: 10, output_tokens: 5 }, model: 'claude-test' };
          } };
        } };
      }`,
    "@/lib/data-engine": `
      const log = (...a) => globalThis.__dataCalls.push(a);
      export async function query(e, o, c) { log('query', e, o, c); return { data: [{ id: 'p1', name: 'Rex' }], total: 1, page: 1, limit: 50 }; }
      export async function findById(e, id, c) { log('get', e, id, c); return { id, name: 'Rex', species: 'dog' }; }
      export async function create(e, d, c) { log('create', e, d, c); return { data: { id: 'n1', ...d } }; }
      export async function update(e, id, d, c) { log('update', e, id, d, c); return { data: { id, ...d } }; }
      export async function remove(e, id, c) { log('remove', e, id, c); return { data: { id } }; }`,
    "@/lib/data-init": "export async function ensureDataEngineInitialized() {}",
    "@/lib/append-only-entities": "export const isAppendOnly = () => false;",
  },
});

const engine: any = await import("../workflows/engine.ts");
const nodeIo: any = await import("../workflows/node-io.ts");
const stub: any = await import("../workflows/agent-step.ts");
const real: any = await import("../agents/workflow-step.ts");
const watch: any = await import("../agents/watch.ts");

real.registerAgentStepAction();
const logRows: any[] = [];
nodeIo.registerExecutionLogger((row: any) => { logRows.push(row); });
let seen: any = null;
engine.registerActionHandler("db_query", async () => ({ pet: { id: "pet-1", name: "Rex" } }));
engine.registerActionHandler("capture", async (_c: any, ctx: any) => { seen = JSON.parse(JSON.stringify(ctx.variables)); return { captured: true }; });

let fetched = 0;
const realFetch = globalThis.fetch;
globalThis.fetch = (async () => { fetched++; throw new Error("no network in an assistant step"); }) as any;

// ── fixtures ──────────────────────────────────────────────────────────────

const tool = (name: string, over: Record<string, unknown> = {}): any => ({
  name, description: name, kind: "data", entity: "pets", operation: "get",
  inputSchema: { type: "object", properties: { id: { type: "string" } } }, ...over,
});
g.__agents = [{
  id: "triage", name: "Triage", enabled: true,
  model: { maxTokens: 512 },
  systemPrompt: "You triage requests.",
  tools: [
    tool("get_pet"),
    tool("add_note", { entity: "notes", operation: "create", confirm: true }),
    tool("book", { kind: "workflow", workflowId: "book-appointment", entity: undefined, operation: undefined, confirm: true }),
  ],
  memory: { type: "conversation", maxMessages: 6, summarizeAfter: 80 },
  guardrails: { input: { maxLength: 2000, blockPatterns: [], requireAuth: true }, output: { blockPatterns: [], contentFilter: "standard" }, outputRules: [] },
  maxTurns: 6, ui: { title: "Triage", position: "bottom-right" }, workflowOnly: true,
}];
const FIELDS = [
  { name: "urgency", type: "enum", values: ["routine", "soon", "urgent"], required: true },
  { name: "reason", type: "string", required: true },
];
const answer = (over: Record<string, unknown> = {}) => ({ type: "tool_use", id: "r1", name: "return_result", input: { urgency: "urgent", reason: "bleeding", confidence: 0.95, needsHuman: false, summary: "Needs a visit today.", ...over } });
const read = (id = "t1") => ({ type: "tool_use", id, name: "get_pet", input: { id: "pet-1" } });

const workflowOf = (config: Record<string, unknown>, nodeType = "action") => ({
  id: "wf-handle", name: "Handle request",
  definition: {
    trigger: { type: "manual" },
    nodes: [
      { id: "trigger", type: "trigger", data: { label: "Start", config: {} } },
      { id: "find", type: "action", data: { label: "Look up pet", config: { actionType: "db_query" } } },
      { id: "triage", type: nodeType, data: { label: "Triage", config: { actionType: "agent_step", agentId: "triage", task: "Triage: {{request}}", input: { pet: "{{find.pet}}", asked: "{{request}}" }, outputFields: FIELDS, ...config } } },
      { id: "after", type: "action", data: { label: "Use the answer", config: { actionType: "capture" } } },
      { id: "end", type: "end", data: { label: "Done", config: {} } },
    ],
    edges: [
      { id: "e1", source: "trigger", target: "find" },
      { id: "e2", source: "find", target: "triage" },
      { id: "e3", source: "triage", target: "after" },
      { id: "e4", source: "after", target: "end" },
    ],
  },
});

function reset(replies: any[] = [], key: string | undefined = "sk-test") {
  g.__replies = replies; g.__requests = []; g.__dataCalls = []; g.__key = key; seen = null; logRows.length = 0;
}
async function runFlow(config: Record<string, unknown> = {}, nodeType = "action") {
  let result: any;
  try { result = await engine.executeWorkflow(workflowOf(config, nodeType), { request: "he is limping" }, { id: "u1", role: "Receptionist" }); }
  catch (e) { result = { status: "failed", thrown: String(e) }; }
  await new Promise((r) => setTimeout(r, 15)); // the execution log is fire-and-forget
  return result;
}

// ── the answer reaches the steps after it ────────────────────────────────

console.log("a step's envelope is what later steps read");
{
  reset([{ content: [read()] }, { content: [answer()] }]);
  const r = await runFlow();
  ok(r.status === "completed", "the run completed");
  eqJson([seen.triage.ok, seen.triage.result, seen.triage.needsHuman, seen.triage.confidence], [true, { urgency: "urgent", reason: "bleeding" }, false, 0.95], "{{triage.result.urgency}}, {{triage.needsHuman}} and {{triage.confidence}} are there for the next step");
  eqJson([seen.triage.proposals, seen.triage.actions], [[], []], "with proposals and actions as empty lists");
  ok(seen.__triage_output?.ok === true, "and under the older __triage_output name as every step's output is");
  const asked = g.__requests[0];
  ok(asked.messages[0].content.startsWith("Triage: he is limping") && asked.messages[0].content.includes("- pet: {\"id\":\"pet-1\",\"name\":\"Rex\"}") && asked.messages[0].content.includes("- asked: he is limping"), "the task and the labelled facts were resolved from the workflow's variables");
  eqJson(g.__dataCalls.map((c: any) => c[0]), ["get"], "the assistant's read went to the data engine");
  eqJson(g.__dataCalls[0][3], { user: { id: "", role: "workflow" }, via: "workflow:wf-handle", runId: g.__dataCalls[0][3].runId }, "as role 'workflow' with no id, via workflow:<id>");
  ok(typeof g.__dataCalls[0][3].runId === "string" && g.__dataCalls[0][3].runId.length > 4, "inside a run id");
  const row = logRows.find((x) => x.nodeId === "triage");
  ok(row.status === "completed" && row.outputs.result.urgency === "urgent" && row.actionType === "agent_step", "the execution log holds the envelope");
  eqJson([fetched], [0], "no HTTP call was made by the assistant");
}

console.log("a node whose TYPE is agent_step runs the same");
{
  reset([{ content: [answer({ urgency: "routine" })] }]);
  const r = await runFlow({}, "agent_step");
  ok(r.status === "completed" && seen.triage.result.urgency === "routine", "type agent_step with actionType agent_step");
}

console.log("a change is a proposal at suggest, and made after the answer at limited");
{
  const propose = { type: "tool_use", id: "n1", name: "add_note", input: { data: { text: "bleeding" }, proposal_reason: "keep the history" } };
  reset([{ content: [propose] }, { content: [answer()] }]);
  await runFlow({ autonomy: "suggest", allowedWriteTools: ["add_note"] });
  eqJson(g.__dataCalls, [], "suggest: the data engine was never asked to create anything");
  eqJson(seen.triage.proposals, [{ tool: "add_note", input: { data: { text: "bleeding" } }, reason: "keep the history" }], "the change is in {{triage.proposals}}");

  reset([{ content: [propose] }, { content: [answer()] }]);
  const r = await runFlow({ autonomy: "limited", allowedWriteTools: ["add_note"] });
  eqJson(g.__dataCalls.map((c: any) => c[0]), ["create"], "limited, sure enough: the engine created the note");
  const ctx = g.__dataCalls[0][g.__dataCalls[0].length - 1];
  ok(ctx.via === "workflow:wf-handle" && ctx.user.role === "workflow" && ctx.reason.includes("assistant step"), "as the workflow actor, with a reason on the trail");
  eqJson(seen.triage.actions, [{ tool: "add_note", input: { data: { text: "bleeding" } }, ok: true }], "and it is in {{triage.actions}}");
  ok(seen.triage.proposals.length === 0 && seen.triage.needsHuman === false && r.status === "completed", "nothing left over");
}

// ── onFailure through the engine ──────────────────────────────────────────

console.log("a step that cannot run follows onFailure");
for (const [onFailure, expectRun] of [["human", "completed"], ["skip", "completed"], ["fail", "failed"]] as const) {
  reset([], "");
  const r = await runFlow({ onFailure });
  ok(r.status === expectRun, `onFailure ${onFailure}: the run ${expectRun === "completed" ? "carries on" : "fails"} (no model key)`);
  const row = logRows.find((x) => x.nodeId === "triage");
  if (onFailure === "fail") {
    ok(String(r.error).includes("no AI key") && row.status === "failed", "fail: the node fails with the reason in words");
    ok(seen === null, "fail: nothing after it ran");
  } else {
    ok(seen.triage.ok === false && seen.triage.reason === "no model key" && String(seen.triage.error).includes("ANTHROPIC_API_KEY"), `${onFailure}: the next step reads ok false, the reason and the error`);
    ok(seen.triage.needsHuman === (onFailure === "human") && seen.triage.proposals.length === 0, `${onFailure}: needsHuman is ${onFailure === "human"}`);
    ok(row.status === "completed" && row.error === undefined, `${onFailure}: the execution log row is completed, not failed`);
  }
  eqJson([g.__requests.length], [0], `${onFailure}: no model call was made`);
}

console.log("a step with no assistant, or one that is not installed, is the builder's to fix");
for (const [config, words] of [[{ agentId: "" }, "no assistant yet"], [{ agentId: "ghost" }, "not installed"]] as const) {
  reset([]);
  const r = await runFlow({ ...config, onFailure: "human" });
  ok(r.status === "completed" && seen.triage.reason === "setup" && seen.triage.error.includes(words), `${JSON.stringify(config)}: a setup failure saying "${words}"`);
  reset([]);
  const r2 = await runFlow({ ...config, onFailure: "fail" });
  ok(r2.status === "failed" && String(r2.error).includes(words), "and with onFailure fail the run fails with it");
}

console.log("an app without assistants has a stub that says so");
{
  stub.registerAgentStepAction();
  reset([]);
  const r = await runFlow({ onFailure: "human" });
  ok(r.status === "failed" && String(r.error).includes("no assistants installed"), "the step fails in words instead of being skipped");
  real.registerAgentStepAction();
  reset([{ content: [answer()] }]);
  ok((await runFlow()).status === "completed", "and installing the assistants puts the real handler back");
}

console.log("a dry-run flag never calls a model");
{
  reset([{ content: [answer()] }]);
  const out: any = await real.agentStepAction({ ...workflowOf({}).definition.nodes[2].data.config, __nodeId: "triage" }, { variables: {}, input: {}, log: [], dryRun: true } as any);
  eqJson([out.ok, out.needsHuman, out.confidence, out.result], [true, false, 1, { urgency: "routine", reason: "sample" }], "the sample envelope answers");
  eqJson([g.__requests.length, g.__dataCalls.length], [0, 0], "no model call and no tool");
}

console.log("the execution log keeps tool inputs short");
{
  reset([{ content: [{ type: "tool_use", id: "n1", name: "add_note", input: { data: { text: "x".repeat(6000) } } }] }, { content: [answer()] }]);
  await runFlow();
  const row = logRows.find((x) => x.nodeId === "triage");
  ok(row.outputs.proposals[0].input.truncated === true && JSON.stringify(row.outputs).length < 4000, "a 6 KB input is a flagged preview of 2 KB in the log");
}

// ── Watch live ────────────────────────────────────────────────────────────

console.log("Watch live is inert unless someone watches");
{
  watch.resetFeed();
  reset([{ content: [read()] }, { content: [answer()] }]);
  await runFlow();
  const later: any[] = [];
  const off = watch.subscribe((e: any) => later.push(e));
  off();
  eqJson([later.length, g.__forgeWatchFeed.runs.size], [0, 0], "no watcher: nothing was recorded, nothing replays");
}

console.log("a watcher sees the step like a chat, with the workflow on run_start");
{
  watch.resetFeed();
  const got: any[] = [];
  const off = watch.subscribe((e: any) => got.push(e));
  reset([{ content: [read()] }, { content: [answer()] }]);
  await runFlow();
  off();
  const types = got.map((e) => e.type);
  const start = got.find((e) => e.type === "run_start");
  ok(!!start && start.agentId === "triage" && start.agentName === "Triage", "run_start names the assistant");
  eqJson([start.workflow.id, start.workflow.stepId, typeof start.workflow.runId], ["wf-handle", "triage", "string"], "and the workflow, its run and the step");
  eqJson([start.user.id, start.user.role], ["workflow:wf-handle", "workflow"], "the 'user' is the workflow actor");
  ok(start.conversationId === `wf:${start.workflow.runId}:triage`, "with the conversation id the turn is recorded under");
  ok(types[0] === "run_start" && types.includes("model_start") && types.includes("model_call") && types.includes("tool_call") && types.includes("tool_result") && types.includes("app_call") && types.at(-1) === "done", "then the model calls, the tool call, the real request behind it, and done");
  const call = got.find((e) => e.type === "app_call");
  ok(call.label === "/api/data/pets/pet-1" && call.method === "GET" && call.ok, "the request behind the tool is shown as the data call it was");
  ok(types.includes("phase"), "and the runtime's checks");
}

globalThis.fetch = realFetch;
done("agent step workflow");
