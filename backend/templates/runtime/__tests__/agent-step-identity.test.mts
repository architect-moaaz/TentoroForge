/**
 * Who an assistant step acts as — the SHIPPED agents/workflow-actor.ts, with the data layer and the app's other
 * back-ends faked.
 *
 * The design is "no credential at all": the step runs its tools in the app's own process as an actor object that holds
 * exactly the assistant's own tools. So what is pinned here is not that a forged header is refused (there is no header
 * to forge) but that nothing leaves the process, that the actor can do only what it was granted and only as itself,
 * that a write is never granted while the model runs, and that every call leaves one line.
 *
 * Run: __tests__/run-agent-step-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();

const A = await import("../agents/workflow-actor.ts");
const { createToolRunner, RateLimiter, ToolError } = await import("../agents/tools.ts");
const { changesData } = await import("../agents/confirm.ts");
const { isWorkflowOnly } = await import("../agents/workflow-only.ts");
const { instrumentIO } = await import("../agents/debug.ts");

// ── fixtures ──────────────────────────────────────────────────────────────

const spec = (name: string, over: Record<string, unknown> = {}): any => ({
  name, description: name, kind: "data", entity: "pets", operation: "list",
  inputSchema: { type: "object", properties: {} }, ...over,
});
const TOOLS = [
  spec("list_pets"),
  spec("get_pet", { operation: "get" }),
  spec("list_owners", { entity: "pet_owners" }),
  spec("add_note", { entity: "notes", operation: "create", confirm: true }),
  spec("edit_pet", { operation: "update", confirm: true }),
  spec("delete_pet", { operation: "delete", confirm: true }),
  spec("book", { kind: "workflow", workflowId: "book-appointment", entity: undefined, operation: undefined, confirm: true }),
  spec("search_kb", { kind: "mcp", mcpServerId: "kb", mcpToolName: "search", entity: undefined, operation: undefined }),
  spec("classify", { kind: "ai_action", aiAction: "classify", entity: undefined, operation: undefined }),
  spec("calc", { kind: "function", handler: "calc", entity: undefined, operation: undefined }),
  spec("page_route", { kind: "api", method: "GET", endpoint: "/api/pets", entity: undefined, operation: undefined }),
  spec("request_human", { kind: "handoff", entity: undefined, operation: undefined }),
];
const byName = (n: string) => TOOLS.find((t) => t.name === n);

const ID = { workflowId: "handle-request", stepId: "triage", runId: "run-1", agentId: "triage" };
const actorOf = (granted: string[]) => A.makeActor({ ...ID, tools: TOOLS, granted });
const READS = ["list_pets", "get_pet", "list_owners", "search_kb", "classify", "calc"];

/** Everything the app's back-ends were asked, so a test can say what did and did not happen. */
function backends() {
  const seen: any = { data: [], workflow: [], mcp: [], ai: [], fn: [], http: 0 };
  const layer = {
    async ready() { seen.data.push(["ready"]); },
    async query(entity: string, opts: any, ctx: any) { seen.data.push(["query", entity, opts, ctx]); return { data: [{ id: "p1", name: "Rex", createdAt: new Date("2026-10-01T10:00:00Z"), passwordHash: "x" }], total: 1, page: 1, limit: opts.limit }; },
    async findById(entity: string, id: string, ctx: any) { seen.data.push(["get", entity, id, ctx]); if (id === "gone") { const e = new Error("pets with id gone not found"); e.name = "NotFoundError"; throw e; } return { id, name: "Rex" }; },
    async create(entity: string, data: any, ctx: any) { seen.data.push(["create", entity, data, ctx]); if (data.bad) { const e: any = new Error("name is required"); e.name = "ValidationError"; throw e; } return { data: { id: "n1", ...data }, event: "x" }; },
    async update(entity: string, id: string, data: any, ctx: any) { seen.data.push(["update", entity, id, data, ctx]); return { data: { id, ...data } }; },
    async remove(entity: string, id: string, ctx: any) { seen.data.push(["remove", entity, id, ctx]); return { data: { id } }; },
    isAppendOnly: (entity: string) => entity === "ledger",
  };
  const base = {
    async triggerWorkflow(id: string, input: any, user: any) { seen.workflow.push([id, input, user]); return { status: "completed", output: {} }; },
    async callMcp(server: string, tool: string, args: any) { seen.mcp.push([server, tool, args]); return { hits: 1 }; },
    async runAi(action: string, config: any, input: any, user: any) { seen.ai.push([action, input, user]); return { label: "x" }; },
    async runFunction(handler: string, input: any, ctx: any) { seen.fn.push([handler, input, ctx]); return { n: 1 }; },
  };
  return { seen, layer, base };
}

/** The tool runner a step builds for an actor: guard in front of the app's normal runner over the actor's own back-ends. */
function runnerFor(granted: string[], b = backends(), lines: any[] = []) {
  const actor = actorOf(granted);
  const io = A.workflowToolIO(actor, b.base, async () => b.layer);
  const run = A.guardTools(actor, TOOLS, createToolRunner(io, new RateLimiter()), (e: any) => lines.push(e));
  const ctx = (over: Record<string, unknown> = {}) => ({ user: A.actorUser(actor), cookie: "", origin: "", conversationId: "wf:run-1:triage", agentId: "triage", handoff: null, ...over });
  return { actor, run, ctx, b, lines };
}

// no network at all: a route call from a step would show up here
const realFetch = globalThis.fetch;
let fetched = 0;
globalThis.fetch = (async () => { fetched++; throw new Error("the network must not be used by an assistant step"); }) as any;

// ── the actor ─────────────────────────────────────────────────────────────

console.log("the actor holds exactly the tools it was given");
{
  const a = actorOf(["list_pets", "add_note", "no_such_tool", "page_route", "request_human"]);
  eqJson([...a.grants], ["list_pets", "add_note"], "only real tools of the assistant, and never a page route or a handoff (they have no in-process form)");
  eqJson([...a.keys], ["data:pets:list", "data:notes:create"], "each as the thing it reaches");
  ok(a.id === "workflow:handle-request" && a.kind === "workflow", "named workflow:<workflowId>");
  ok(Object.isFrozen(a), "and cannot be changed after it is made");
  eqJson([...actorOf([]).grants], [], "an actor can hold nothing at all");
  eqJson(A.actorUser(a), { id: "workflow:handle-request", role: "workflow" }, "to the tool runner it is that id with the role 'workflow'");
  eqJson(A.engineUser(), { id: "", role: "workflow" }, "to the engines it is the role 'workflow' with no id (so no row is its own)");
}

console.log("what counts as a change is the compiler's mark OR the tool's own shape");
{
  eqJson(TOOLS.map((t) => [t.name, changesData(t)]).filter(([, c]) => c).map(([n]) => n), ["add_note", "edit_pet", "delete_pet", "book", "request_human"], "creates, updates, deletes, workflows and handoffs change things");
  ok(!changesData(spec("x", { kind: "function", handler: "h" })) && changesData(spec("x", { kind: "function", handler: "h", confirm: true })), "a function is a change only when marked");
  ok(changesData(spec("x", { kind: "api", method: "post" })) && !changesData(spec("x", { kind: "api", method: "HEAD" })), "an api call is a change unless it is a GET or HEAD");
}

// ── the guard in front of the tool runner ────────────────────────────────

console.log("the actor can run what it holds, as itself, and nothing else");
{
  const r = runnerFor(READS);
  const out: any = await r.run(byName("list_pets"), { search: "rex" }, r.ctx(), {});
  ok(out.data[0].name === "Rex", "a granted read runs");
  const refused = async (fn: () => Promise<unknown>) => { try { await fn(); return null; } catch (e: any) { return e; } };
  const e1 = await refused(() => r.run(byName("add_note"), { text: "x" }, r.ctx(), {}));
  ok(e1 instanceof ToolError && e1.code === "auth" && e1.message.includes("changes data"), "a change it was not granted is refused, and the refusal says it is recorded as a proposal instead");
  const e2 = await refused(() => r.run(byName("book"), {}, r.ctx(), {}));
  ok(e2?.code === "auth", "a workflow it was not granted is refused");
  const e3 = await refused(() => r.run(spec("list_pets"), {}, r.ctx(), {}));
  ok(e3?.code === "auth" && e3.message.includes("not one of this assistant's tools"), "a look-alike of a granted tool (same name, not the assistant's own) is refused");
  const e4 = await refused(() => r.run(spec("totally_new", { entity: "users" }), {}, r.ctx(), {}));
  ok(e4?.code === "auth", "a tool the assistant never had is refused");
  const e5 = await refused(() => r.run(byName("list_pets"), {}, r.ctx({ user: { id: "u-17", role: "Admin" } }), {}));
  ok(e5?.code === "auth" && e5.message.includes("its own workflow"), "a person's identity cannot be put in front of the actor's tools");
  const e6 = await refused(() => r.run(byName("list_pets"), {}, r.ctx({ user: null }), {}));
  ok(e6?.code === "auth", "nor can no identity at all");
  eqJson(r.b.seen.data.filter((d: any) => d[0] !== "ready").length, 1, "of all these only the one allowed call reached the data layer");
}

console.log("a write is granted only for the tools the gates approved");
{
  const r = runnerFor([...READS, "book"]);
  const out: any = await r.run(byName("book"), { petId: "p1" }, r.ctx(), {});
  ok(out.status === "completed", "the approved workflow runs");
  const e: any = await r.run(byName("add_note"), {}, r.ctx(), {}).catch((x) => x);
  ok(e instanceof ToolError, "the unapproved change next to it still does not");
  eqJson(r.b.seen.workflow, [["book-appointment", { petId: "p1" }, { id: "", role: "workflow" }]], "the workflow was started as role 'workflow' with no id, never as a person");
}

console.log("every call leaves one line, refusals included, with no values in it");
{
  const lines: any[] = [];
  const r = runnerFor(READS, backends(), lines);
  await r.run(byName("list_pets"), { search: "secret-value" }, r.ctx(), {});
  await r.run(byName("add_note"), { text: "secret-value" }, r.ctx(), {}).catch(() => {});
  eqJson(lines.length, 2, "two calls, two lines");
  eqJson(Object.keys(lines[0]).sort(), ["actor", "agentId", "changes", "error", "event", "kind", "ms", "ok", "refused", "runId", "stepId", "tool", "workflowId"].filter((k) => k !== "error").sort(), "who, which run and step, which tool, how long, whether it worked and whether it was refused");
  ok(lines[0].ok && !lines[0].refused && lines[0].actor === "workflow:handle-request" && lines[0].runId === "run-1" && lines[0].tool === "list_pets", "the allowed read");
  ok(!lines[1].ok && lines[1].refused && lines[1].changes === true && typeof lines[1].error === "string", "the refused change, flagged as a change and as refused");
  ok(!JSON.stringify(lines).includes("secret-value"), "no input value is logged");
  const printed: string[] = [];
  const info = console.info;
  console.info = (...a: unknown[]) => printed.push(a.join(" "));
  const r2 = A.guardTools(actorOf(READS), TOOLS, async () => 1);
  await r2(byName("list_pets"), {}, { user: A.actorUser(actorOf(READS)), cookie: "", origin: "" }, {});
  console.info = info;
  ok(printed.length === 1 && printed[0].startsWith("[agent-step] {"), "by default the line goes to the log as one JSON object");
}

// ── the data layer, in process ────────────────────────────────────────────

console.log("a data tool is answered by the data layer as the actor, never over HTTP");
{
  const r = runnerFor(["list_pets", "get_pet"]);
  const out: any = await r.run(byName("list_pets"), { search: "rex", page: "2", limit: 9999, sort: "name", order: "asc", unmask: "ssn", species: "dog", filters: { age: 3 } }, r.ctx(), {});
  const q = r.b.seen.data.find((d: any) => d[0] === "query");
  eqJson(q[2], { search: "rex", filters: { age: "3", species: "dog" }, sort: "name", order: "asc", page: 2, limit: 200 }, "the request is read as the data route reads its URL: named options, the rest filters, page and limit bounded, unmask never");
  eqJson(q[3], { user: { id: "", role: "workflow" }, via: "workflow:handle-request", runId: "run-1" }, "the engine is told: a role 'workflow' with no id, made via workflow:<id>, in this run (and no reason for a read)");
  ok(r.b.seen.data[0][0] === "ready", "the engine's registry is made ready first");
  ok(out.data[0].createdAt === "2026-10-01T10:00:00.000Z", "a date comes out as text, as it would over HTTP");
  ok(!("passwordHash" in out.data[0]), "and the credential filter runs on it like on any tool result");
  const one: any = await r.run(byName("get_pet"), { id: "p1" }, r.ctx(), {});
  eqJson(one, { id: "p1", name: "Rex" }, "a get is a findById");
  const gone: any = await r.run(byName("get_pet"), { id: "gone" }, r.ctx(), {}).catch((e) => e);
  ok(gone instanceof ToolError && gone.message === "No record with that id.", "a missing record is the plain sentence the route gives");
  eqJson([fetched], [0], "and the network was never used");
}

console.log("a granted change is made through the data layer with a reason and the run on the trail");
{
  const r = runnerFor(["add_note", "edit_pet", "delete_pet"]);
  await r.run(byName("add_note"), { data: { text: "limping" } }, r.ctx(), {});
  await r.run(byName("edit_pet"), { id: "p1", data: { weight: 12 } }, r.ctx(), {});
  await r.run(byName("delete_pet"), { id: "p1" }, r.ctx(), {});
  const calls = r.b.seen.data.filter((d: any) => d[0] !== "ready");
  eqJson(calls.map((c: any) => c[0]), ["create", "update", "remove"], "create, update and remove");
  eqJson(calls[0][2], { text: "limping" }, "a create gets the record's fields");
  for (const c of calls) {
    const ctx = c[c.length - 1];
    ok(ctx.via === "workflow:handle-request" && ctx.runId === "run-1" && ctx.user.role === "workflow" && ctx.user.id === "" && ctx.reason.includes("assistant step (triage)"), `${c[0]}: via workflow:<id>, the run id, the actor, and a plain reason`);
  }
  const bad: any = await r.run(byName("add_note"), { data: { bad: true } }, r.ctx(), {}).catch((e) => e);
  ok(bad instanceof ToolError && bad.code === "invalid" && bad.message === "name is required", "the engine's validation reaches the model as a plain error");
}

console.log("the actor cannot reach what it was not granted, even by a tool that exists");
{
  const r = runnerFor(["list_pets"]);
  const io = A.workflowToolIO(actorOf(["list_pets"]), r.b.base, async () => r.b.layer);
  const refused = async (fn: () => Promise<unknown>) => { try { await fn(); return null; } catch (e: any) { return e; } };
  ok((await refused(() => io.data!({ operation: "update", entity: "pets", id: "p1", body: {} }, {} as any)))?.code === "auth", "update on an entity it may only list");
  ok((await refused(() => io.data!({ operation: "list", entity: "users" }, {} as any)))?.code === "auth", "an entity it never had");
  ok((await refused(() => io.data!({ operation: "list", entity: "PETS" }, {} as any))) === null, "entity names match whatever their capitals");
  ok((await refused(() => io.triggerWorkflow("book-appointment", {}, null)))?.code === "auth", "a workflow it was not granted");
  ok((await refused(() => io.callMcp("kb", "search", {})))?.code === "auth", "an MCP tool it was not granted");
  ok((await refused(() => io.runAi("classify", {}, {}, null)))?.code === "auth", "an AI action it was not granted");
  ok((await refused(() => io.runFunction("calc", {}, {} as any)))?.code === "auth", "a tool module it was not granted");
  eqJson([r.b.seen.workflow.length, r.b.seen.mcp.length, r.b.seen.ai.length, r.b.seen.fn.length], [0, 0, 0, 0], "none of them reached its back-end");
}

console.log("an append-only record is written once and never changed or removed");
{
  const b = backends();
  const ledgerTools = [spec("edit_ledger", { entity: "ledger", operation: "update", confirm: true }), spec("del_ledger", { entity: "ledger", operation: "delete", confirm: true }), spec("add_ledger", { entity: "ledger", operation: "create", confirm: true })];
  const actor = A.makeActor({ ...ID, tools: ledgerTools, granted: ledgerTools.map((t) => t.name) });
  const run = A.guardTools(actor, ledgerTools, createToolRunner(A.workflowToolIO(actor, b.base, async () => b.layer), new RateLimiter()), () => {});
  const ctx = { user: A.actorUser(actor), cookie: "", origin: "" } as any;
  const e1: any = await run(ledgerTools[0], { id: "1", data: {} }, ctx, {}).catch((e: any) => e);
  const e2: any = await run(ledgerTools[1], { id: "1" }, ctx, {}).catch((e: any) => e);
  ok(e1 instanceof ToolError && e1.message.includes("append-only") && e2 instanceof ToolError, "update and delete are refused");
  const made: any = await run(ledgerTools[2], { data: { amount: 5 } }, ctx, {});
  ok(made.amount === 5, "a create is allowed");
}

console.log("the other back-ends carry the actor, never a person or a cookie");
{
  const r = runnerFor(["search_kb", "classify", "calc", "book"]);
  await r.run(byName("search_kb"), { q: "x" }, r.ctx(), {});
  await r.run(byName("classify"), { text: "x" }, r.ctx(), {});
  await r.run(byName("calc"), { n: 1 }, r.ctx({ cookie: "session=abc", origin: "http://x" }), {});
  eqJson(r.b.seen.mcp, [["kb", "search", { q: "x" }]], "MCP: the server's tool and its arguments");
  eqJson(r.b.seen.ai[0][2], { id: "", role: "workflow" }, "an AI action sees the actor as role 'workflow'");
  eqJson([r.b.seen.fn[0][2].user, r.b.seen.fn[0][2].cookie], [{ id: "workflow:handle-request", role: "workflow" }, ""], "a tool module is handed the actor and an EMPTY cookie even if one was passed in");
}

console.log("a tool that calls a page route, or hands over to a person, has no in-process form");
{
  const r = runnerFor([...READS, "page_route", "request_human"]);
  const e1: any = await r.run(byName("page_route"), {}, r.ctx(), {}).catch((e) => e);
  ok(e1 instanceof ToolError && e1.code === "auth", "an api tool is not granted (refused by the guard)");
  const b = backends();
  const io = A.workflowToolIO(actorOf(READS), b.base, async () => b.layer);
  const e2: any = await io.fetchInternal("/api/pets", { method: "GET" }, r.ctx() as any).catch((e) => e);
  ok(e2 instanceof ToolError && e2.code === "unavailable" && e2.message.includes("signed-in person"), "and even if it were called, the route call is refused in words");
  const e3: any = await io.requestHandoff({}, r.ctx() as any).catch((e) => e);
  ok(e3 instanceof ToolError && e3.message.includes("needsHuman"), "a handoff points the model at needsHuman");
  eqJson([fetched], [0], "the network was never used, not even to be refused");
}

console.log("a cookie is never forwarded: the watching wrapper keeps it that way");
{
  const b = backends();
  const actor = actorOf(["list_pets"]);
  const events: any[] = [];
  const io = instrumentIO(A.workflowToolIO(actor, b.base, async () => b.layer), (e: any) => events.push(e));
  const out: any = await io.data!({ operation: "list", entity: "pets", query: { search: "r" } }, {} as any);
  ok(out.total === 1, "the wrapped back-end still answers");
  ok(events[0].type === "app_call" && events[0].kind === "request" && events[0].label === "/api/data/pets" && events[0].method === "GET" && events[0].ok === true, "and is reported to the watcher like the request it replaces");
}

console.log("workflowOnly is a real true and nothing else");
{
  ok(isWorkflowOnly({ workflowOnly: true }) && isWorkflowOnly({ workflow_only: true }), "either spelling");
  ok(!isWorkflowOnly({}) && !isWorkflowOnly(null) && !isWorkflowOnly({ workflowOnly: "true" }) && !isWorkflowOnly({ workflowOnly: 1 }) && !isWorkflowOnly({ workflowOnly: false }), "absent, null, false, text or 1 is a normal assistant");
}

globalThis.fetch = realFetch;
done("agent step identity");
