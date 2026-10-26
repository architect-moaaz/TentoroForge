/**
 * An assistant made for a workflow step is not one a person can talk to — the SHIPPED api-agent/chat-route.ts.
 *
 * `workflowOnly` (the definition's `workflow_only`) takes an assistant out of GET /api/agent/chat and makes
 * POST /api/agent/chat answer 404 for it, exactly as for an id that does not exist; the widget only mounts what the
 * list returns, so it never shows one. The flag defaults to false, and every chat behaviour that existed before it is
 * pinned here as well: what is listed, who is offered what, which assistant answers when none is named, the answer to
 * an unknown or switched-off one.
 *
 * Run: __tests__/run-agent-step-tests.sh
 */
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const g = globalThis as any;
/** The registry's list is one array the stub hands out; a scenario swaps what is in it. */
g.__holder = [];
const setAgents = (xs: any[]) => { g.__holder.length = 0; g.__holder.push(...xs); };
const here = fileURLToPath(new URL(".", import.meta.url));

installHarness({
  redirect: { "@/lib/agents/workflow-only": resolve(here, "../agents/workflow-only.ts") },
  stubs: {
    "@/auth": "export const auth = async () => globalThis.__session;",
    "@/agents/registry": "export const AGENTS = globalThis.__holder;",
    "@/lib/agents/runtime": "export async function runAgent(config, input, _deps, emit) { globalThis.__ran.push({ id: config.id, message: input.message }); emit({ type: 'text', content: 'hi' }); emit({ type: 'done', conversationId: 'c1', tokens: { input: 1, output: 1 }, turns: 1 }); }",
    "@/lib/agents/store": "export const drizzleStore = {};",
    "@/lib/agents/debug": "export const instrumentIO = (io) => io;",
    "@/lib/agents/insights-outbox": "export const insightsShipper = () => ({});",
    "@/lib/agents/insights-shipper": "export async function holdForShipping() {}",
    "@/lib/agents/io": "export const realDeps = async () => ({}); export const toolIO = {};",
    "@/lib/agents/watch": "export const feedEvent = (e) => e; export const newRunId = () => 'r'; export const observeDeps = (d) => d; export const publish = () => {}; export const watching = () => false;",
  },
});

const route: any = await import("../api-agent/chat-route.ts");

const agent = (id: string, over: Record<string, unknown> = {}): any => ({
  id, name: `Agent ${id}`, description: `${id} helps`, enabled: true,
  model: { maxTokens: 100 }, systemPrompt: "x", tools: [],
  memory: { type: "conversation", maxMessages: 6, summarizeAfter: 80 },
  guardrails: { input: { maxLength: 100, blockPatterns: [], requireAuth: true }, output: { blockPatterns: [], contentFilter: "standard" }, outputRules: [] },
  maxTurns: 4, ui: { title: id, position: "bottom-right" }, ...over,
});

const list = async () => (await route.GET()).json();
const post = async (body: Record<string, unknown>) => {
  const res: Response = await route.POST(new Request("http://x/api/agent/chat", { method: "POST", body: JSON.stringify(body), headers: { "content-type": "application/json" } }));
  return { status: res.status, text: await res.text() };
};

g.__session = { user: { id: "u1", role: "customer" } };

console.log("regression: with no workflowOnly anywhere the chat is exactly what it was");
{
  g.__ran = [];
  setAgents([agent("support"), agent("billing"), agent("off", { enabled: false }), agent("members", { guardrails: { input: { maxLength: 100, blockPatterns: [], requireAuth: true }, output: { blockPatterns: [], contentFilter: "standard" }, outputRules: [] } }), agent("public", { guardrails: { input: { maxLength: 100, blockPatterns: [], requireAuth: false }, output: { blockPatterns: [], contentFilter: "standard" }, outputRules: [] } })]);
  const l = await list();
  eqJson(l.map((a: any) => a.id), ["support", "billing", "members", "public"], "every enabled assistant is listed");
  eqJson(Object.keys(l[0]), ["id", "name", "description", "ui"], "with the same four fields, never the prompt, tools or guardrails");
  const named = await post({ agentId: "billing", message: "hi" });
  ok(named.status === 200 && g.__ran.at(-1).id === "billing", "an assistant named by id answers");
  const unnamed = await post({ message: "hi" });
  ok(unnamed.status === 200 && g.__ran.at(-1).id === "support", "with none named, the first enabled one answers");
  const missing = await post({ agentId: "nobody", message: "hi" });
  eqJson([missing.status, JSON.parse(missing.text)], [404, { error: "No such agent." }], "an unknown id is a 404 'No such agent.'");
  const off = await post({ agentId: "off", message: "hi" });
  ok(off.status === 404, "a switched-off assistant is a 404");
  g.__session = null;
  const visitor = await list();
  eqJson(visitor.map((a: any) => a.id), ["public"], "a visitor is offered only what does not need a person");
  g.__session = { user: { id: "u1", role: "customer" } };
  ok((await post({ message: "" })).status === 400 && (await post({ message: "hi" })).status === 200, "the other checks are untouched (an empty message is 400)");
}

console.log("a workflow-only assistant is not listed and not answered");
for (const spelling of ["workflowOnly", "workflow_only"]) {
  g.__ran = [];
  setAgents([agent("wf_triage", { [spelling]: true }), agent("support")]);
  const l = await list();
  eqJson(l.map((a: any) => a.id), ["support"], `${spelling}: left out of the list`);
  const refused = await post({ agentId: "wf_triage", message: "hi" });
  const unknown = await post({ agentId: "nobody", message: "hi" });
  ok(refused.status === 404, `${spelling}: POST by id is a 404…`);
  eqJson([refused.status, JSON.parse(refused.text)], [unknown.status, JSON.parse(unknown.text)], `${spelling}: …the very answer an unknown id gets, so its existence is not given away`);
  ok(g.__ran.length === 0, `${spelling}: the assistant never ran`);
  const dflt = await post({ message: "hi" });
  ok(dflt.status === 200 && g.__ran.at(-1).id === "support", `${spelling}: with none named, it is skipped even though it is first`);
}

console.log("only a real true counts");
{
  g.__ran = [];
  setAgents([agent("a", { workflowOnly: false }), agent("b", { workflowOnly: "true" }), agent("c", { workflowOnly: 1 }), agent("d", { workflow_only: null }), agent("e")]);
  eqJson((await list()).map((x: any) => x.id), ["a", "b", "c", "d", "e"], "false, text, 1 and null are all normal assistants");
}

console.log("an app whose only assistants are made for workflows has no chat");
{
  g.__ran = [];
  setAgents([agent("wf_only", { workflowOnly: true })]);
  eqJson(await list(), [], "an empty list, so the widget mounts nothing");
  const r = await post({ message: "hi" });
  ok(r.status === 404 && g.__ran.length === 0, "and a message with no assistant named is a 404");
}

done("agent workflow-only");
