/**
 * Human handoff, run from the SHIPPED files in templates/runtime/agents/.
 *
 * What is pinned: who may work the inbox; who takes a handoff under each assignment; that the handoff is
 * recorded before anyone is told and that the tool FAILS when it cannot be recorded (the assistant must never
 * say "passed to the team" over nothing); that nothing after the record can fail it — no email set up, a mail
 * server down, a notification that cannot be written; that asking twice is one handoff; and that the assistant
 * stops answering a conversation that is with a person.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();

const { requestHandoff, canHandle, pickAssignee, handoffNotice } = await import("../agents/handoff.ts");
const { ToolError } = await import("../agents/tools.ts");
const { runAgent } = await import("../agents/runtime.ts");
const { memoryStore } = await import("../agents/memory.ts");

// ── fixtures ──────────────────────────────────────────────────────────────

const spec = (over: Record<string, unknown> = {}): any => ({
  handlers: { roles: ["Manager"], people: [] },
  assignment: "queue",
  questions: ["Why do you need a person?"],
  notify: { inApp: true, email: false, emailUrgentOnly: true },
  keywords: [],
  ...over,
});

const user = { id: "u1", role: "Support Agent", email: "pat@example.test" };
const ctxFor = (s: any, over: Record<string, unknown> = {}): any => ({
  user, cookie: "", origin: "", conversationId: "c1", agentId: "app_assistant", handoff: s, ...over,
});

function fakeDeps(over: Record<string, unknown> = {}) {
  const records: any[] = [];
  const notes: any[] = [];
  const emails: any[] = [];
  const deps: any = {
    records, notes, emails,
    store: {
      async create(h: any) {
        const rec = { id: `h${records.length + 1}`, ref: `HO-00${records.length + 1}`, status: "open", createdAt: "now", ...h };
        records.push(rec);
        return rec;
      },
      async openFor(conversationId: string) {
        return records.find((r) => r.conversationId === conversationId && r.status !== "resolved") ?? null;
      },
      async openCounts(ids: string[]) {
        const out: Record<string, number> = {};
        for (const id of ids) out[id] = records.filter((r) => r.assignedToId === id && r.status !== "resolved").length;
        return out;
      },
    },
    async people(roles: string[]) {
      return [{ id: "m1", name: "Maya", email: "maya@example.test", role: "Manager" },
              { id: "m2", name: "Idris", email: "idris@example.test", role: "Manager" }].filter((p) => roles.includes(p.role));
    },
    async notify(n: any) { notes.push(n); },
    async snapshot() { return "customer: my headphones broke"; },
    ...over,
  };
  return deps;
}

async function refusal(promise: Promise<unknown>): Promise<any> {
  try { await promise; } catch (e) { return e; }
  return null;
}

// ── who may work the inbox ────────────────────────────────────────────────

console.log("who may work the inbox");
{
  const s = spec({ handlers: { roles: ["Manager"], people: [{ id: "u9" }] } });
  ok(canHandle(s, { id: "x", role: "manager" }), "a role matches whatever its capitals");
  ok(canHandle(s, { id: "u9", role: "Customer" }), "a named person may, whatever their role");
  ok(!canHandle(s, { id: "x", role: "Support Agent" }), "someone else may not");
  ok(!canHandle(s, null), "nobody signed out may");
  ok(canHandle(spec({ handlers: { roles: [], people: [] } }), user), "with nobody named, any signed-in person may, so no handoff is stranded");
  ok(!canHandle(null, user), "and no handoff settings means no inbox");
}

// ── who takes it ──────────────────────────────────────────────────────────

console.log("assignment");
{
  const pool = [{ id: "b" }, { id: "a" }, { id: "c" }];
  eqJson(pickAssignee(spec(), pool, {}), null, "queue: nobody yet, the team claims it");
  eqJson(pickAssignee(spec({ assignment: "owner", ownerId: "c" }), pool, {})?.id, "c", "owner: the named person");
  eqJson(pickAssignee(spec({ assignment: "owner", ownerId: "zz" }), pool, {})?.id, "zz", "owner: even when they are not in the pool");
  eqJson(pickAssignee(spec({ assignment: "owner" }), pool, {}), null, "owner with no one named falls back to the queue");
  eqJson(pickAssignee(spec({ assignment: "round_robin" }), pool, { a: 2, b: 0, c: 1 })?.id, "b", "round robin: whoever holds the fewest");
  eqJson(pickAssignee(spec({ assignment: "round_robin" }), pool, {})?.id, "a", "a tie goes to the lowest id, so it is repeatable");
  eqJson(pickAssignee(spec({ assignment: "round_robin" }), [], {}), null, "round robin with nobody to give it to is the queue");
}

// ── the handoff ───────────────────────────────────────────────────────────

console.log("a handoff is recorded, then the team is told");
{
  const deps = fakeDeps();
  const out: any = await requestHandoff(deps, ctxFor(spec()), { reason: "Headphones broke", urgency: "urgent", contact: "555-0100" });
  eqJson(out.ok, true, "it succeeds");
  ok(/^HO-/.test(out.ref) && out.message.includes(out.ref), "and gives the person a reference to quote");
  const rec = deps.records[0];
  eqJson([rec.reason, rec.urgency, rec.contact, rec.requestedById, rec.conversationId, rec.agentId],
    ["Headphones broke", "urgent", "555-0100", "u1", "c1", "app_assistant"], "the record has the reason, urgency, contact, who and which conversation");
  eqJson(rec.summary, "customer: my headphones broke", "and the last of the conversation, so whoever takes it has the context");
  eqJson(deps.notes.map((n: any) => [n.userId, n.role]), [[null, "Manager"]], "the queue is told through the role, so every manager's bell rings");
  ok(deps.notes[0].title.includes("urgent") && deps.notes[0].message.includes("555-0100") && deps.notes[0].entityId === rec.id, "the notice carries the reason, how to reach them and the handoff");
  eqJson(out.notified, { inApp: 1, emailed: 0 }, "and says who was told");
}

console.log("defaults, and what is refused");
{
  const deps = fakeDeps();
  await requestHandoff(deps, ctxFor(spec()), { reason: "Need help", urgency: "whenever" });
  eqJson([deps.records[0].urgency, deps.records[0].contact], ["normal", "pat@example.test"], "an unknown urgency is normal and contact falls back to the account's email");

  const noReason = await refusal(requestHandoff(deps, ctxFor(spec(), { conversationId: "c2" }), { reason: "   " }));
  ok(noReason instanceof ToolError && noReason.code === "invalid" && /reason/i.test(noReason.message), "no reason is refused, in words the assistant can act on");
  const signedOut = await refusal(requestHandoff(deps, ctxFor(spec(), { user: null }), { reason: "x" }));
  ok(signedOut instanceof ToolError && signedOut.code === "auth", "signed-out people cannot be handed over");
  const noConv = await refusal(requestHandoff(deps, ctxFor(spec(), { conversationId: undefined }), { reason: "x" }));
  ok(noConv instanceof ToolError && noConv.code === "invalid", "no conversation, no handoff");
  const notSetUp = await refusal(requestHandoff(deps, ctxFor(null), { reason: "x" }));
  ok(notSetUp instanceof ToolError && notSetUp.code === "unavailable", "an assistant with no handoff settings says it is not set up");
  eqJson(deps.records.length, 1, "none of those left a record behind");
}

console.log("asking twice is one handoff");
{
  const deps = fakeDeps();
  const first: any = await requestHandoff(deps, ctxFor(spec()), { reason: "x" });
  const second: any = await requestHandoff(deps, ctxFor(spec()), { reason: "x again" });
  eqJson([deps.records.length, second.ref], [1, first.ref], "the same reference comes back and nothing is recorded or sent again");
  eqJson(deps.notes.length, 1, "and the team is not told twice");
}

console.log("assignment is applied, and the person is told directly");
{
  const deps = fakeDeps();
  const a: any = await requestHandoff(deps, ctxFor(spec({ assignment: "round_robin" }), { conversationId: "c1" }), { reason: "x" });
  eqJson([deps.records[0].assignedToId, deps.records[0].assignedToName], ["m1", "Maya"], "round robin gives the first to the lowest id");
  eqJson(deps.notes.map((n: any) => [n.userId, n.role]), [["m1", null]], "and only she is notified, by name");
  await requestHandoff(deps, ctxFor(spec({ assignment: "round_robin" }), { conversationId: "c2" }), { reason: "y" });
  eqJson(deps.records[1].assignedToId, "m2", "the next goes to the one with fewer");
  ok(a.ok, "both succeed");
}

// ── nothing after the record can fail it ──────────────────────────────────

console.log("no email set up is not a problem");
{
  const deps = fakeDeps(); // no `email` at all
  const out: any = await requestHandoff(deps, ctxFor(spec({ notify: { inApp: true, email: true, emailUrgentOnly: false } })), { reason: "x" });
  eqJson(out.ok, true, "the handoff still works");
  eqJson(out.notified, { inApp: 1, emailed: 0 }, "the bell still rings");
  eqJson(out.emailNote, "email is not set up", "and it says why no email went");
}

console.log("a failing mail server or notification never fails the handoff");
{
  const deps = fakeDeps({
    async email() { throw new Error("connect ECONNREFUSED"); },
    async notify() { throw new Error('relation "forge_notifications" does not exist'); },
  });
  const out: any = await requestHandoff(deps, ctxFor(spec({ notify: { inApp: true, email: true, emailUrgentOnly: false } })), { reason: "x" });
  eqJson(out.ok, true, "recorded all the same");
  eqJson(deps.records.length, 1, "and it is in the inbox");
  eqJson(out.notified, { inApp: 0, emailed: 0 }, "nobody was told, and it says so");
  ok(/ECONNREFUSED/.test(out.emailNote), "with the reason");
}

console.log("email: only when asked for, only when urgent if that is the rule, only to people with an address");
{
  const deps = fakeDeps({ async email(to: string, subject: string) { deps.emails.push({ to, subject }); return { sent: true }; } });
  const urgentOnly = spec({ notify: { inApp: false, email: true, emailUrgentOnly: true } });
  await requestHandoff(deps, ctxFor(urgentOnly, { conversationId: "a" }), { reason: "x", urgency: "normal" });
  eqJson(deps.emails.length, 0, "a normal one is not emailed when the rule is urgent only");
  const urgent: any = await requestHandoff(deps, ctxFor(urgentOnly, { conversationId: "b" }), { reason: "x", urgency: "urgent" });
  eqJson(deps.emails.map((e: any) => e.to).sort(), ["idris@example.test", "maya@example.test"], "an urgent one goes to each handler");
  eqJson(urgent.notified, { inApp: 0, emailed: 2 }, "counted");
  const off = fakeDeps({ async email() { throw new Error("must not be called"); } });
  const quiet: any = await requestHandoff(off, ctxFor(spec(), { conversationId: "z" }), { reason: "x", urgency: "urgent" });
  eqJson(quiet.ok, true, "email off means no email, even when urgent");

  const noAddress = fakeDeps({ async people() { return [{ id: "m1", name: "Maya", email: null, role: "Manager" }]; }, async email() { return { sent: true }; } });
  const none: any = await requestHandoff(noAddress, ctxFor(spec({ notify: { inApp: true, email: true, emailUrgentOnly: false } })), { reason: "x" });
  ok(/no email address/.test(none.emailNote), "no address on file is said, not guessed at");
}

console.log("a handoff that cannot be recorded FAILS, so nobody is told it worked");
{
  const deps = fakeDeps();
  deps.store.create = async () => { throw new Error("connection terminated"); };
  const err = await refusal(requestHandoff(deps, ctxFor(spec()), { reason: "x" }));
  ok(err instanceof ToolError && /could not be recorded/.test(err.message) && /administrator/.test(err.message), "the assistant is told plainly, and what to say");
  eqJson(deps.notes.length, 0, "and nobody was notified of a handoff that does not exist");
}

console.log("a lookup that fails still leaves a working queue");
{
  const deps = fakeDeps({ async people() { throw new Error("users table missing"); }, async snapshot() { throw new Error("nope"); } });
  const out: any = await requestHandoff(deps, ctxFor(spec()), { reason: "x" });
  eqJson(out.ok, true, "recorded without the people lookup or the transcript");
  eqJson(deps.notes.map((n: any) => n.role), ["Manager"], "the role is still told");
}

// ── the assistant steps back ──────────────────────────────────────────────

const usage = { inputTokens: 1, outputTokens: 1 };
const baseConfig = (): any => ({
  id: "app_assistant", name: "Assistant", enabled: true, model: { maxTokens: 256 }, systemPrompt: "You help.",
  tools: [], memory: { type: "conversation", maxMessages: 6, summarizeAfter: 20 },
  guardrails: { input: { maxLength: 500, blockPatterns: [], requireAuth: true }, output: { blockPatterns: [], contentFilter: "standard" }, outputRules: [] },
  maxTurns: 3, ui: { title: "Assistant", position: "bottom-right" }, handoff: spec(),
});
async function run(config: any, message: string, deps: any, conversationId: string | null = null) {
  const events: any[] = [];
  await runAgent(config, { message, conversationId, user, cookie: "", origin: "" }, deps, (e: any) => events.push(e));
  return events;
}

console.log("the assistant stops answering a conversation that is with a person");
{
  const store = memoryStore();
  let modelCalls = 0;
  const open: any = { ref: "HO-9", status: "open", assignedToName: null };
  const state = { handed: null as any };
  const deps: any = {
    store, runTool: async () => 0,
    handoffs: { async openFor() { return state.handed; } },
    async callModel(_r: any, onText: (c: string) => void) { modelCalls++; onText("Hello"); return { content: [{ type: "text", text: "Hello" }], usage }; },
  };
  const first = await run(baseConfig(), "hi", deps);
  const cid = first.at(-1).conversationId;
  eqJson(modelCalls, 1, "before a handoff the assistant answers");

  state.handed = open;
  const during = await run(baseConfig(), "are you there?", deps, cid);
  eqJson(modelCalls, 1, "once it is with a person the model is not called");
  eqJson(during.map((e: any) => e.type), ["text", "handoff", "done"], "the person is told, and the chat is told to show the status");
  ok(during[0].content.includes("HO-9") && during[1].ref === "HO-9" && during[1].status === "open", "with the reference");
  const kept = (await store.listMessages(cid)).map((m: any) => [m.role, m.content.slice(0, 22)]);
  ok(kept.some((m: any) => m[0] === "user" && m[1] === "are you there?"), "what they wrote is kept for whoever has it");

  state.handed = { ...open, status: "claimed", assignedToName: "Maya" };
  const claimed = await run(baseConfig(), "hello?", deps, cid);
  ok(claimed[0].content.includes("Maya is looking at it"), "once someone claims it, the person is told who");

  state.handed = null;
  const after = await run(baseConfig(), "thanks, one more thing", deps, cid);
  eqJson(modelCalls, 2, "resolved, the conversation is the assistant's again");
  ok(after.some((e: any) => e.type === "text" && e.content === "Hello"), "and it answers");
}

console.log("an app with no handoff table is never 'handed over'");
{
  const deps: any = {
    store: memoryStore(), runTool: async () => 0,
    handoffs: { async openFor() { throw new Error('relation "forge_agent_handoffs" does not exist'); } },
    async callModel(_r: any, onText: (c: string) => void) { onText("Hi"); return { content: [{ type: "text", text: "Hi" }], usage }; },
  };
  const ev = await run(baseConfig(), "hello", deps);
  ok(ev.some((e: any) => e.type === "text" && e.content === "Hi") && ev.at(-1).type === "done" && !ev.some((e: any) => e.type === "error"),
     "a failed lookup means not handed over: the chat carries on");
}

console.log("the tool is given the conversation, the agent and the handoff settings");
{
  let seen: any = null;
  const cfg = baseConfig();
  cfg.tools = [{ name: "request_human", description: "d", kind: "handoff", inputSchema: { type: "object", properties: {} } }];
  let n = 0;
  const deps: any = {
    store: memoryStore(),
    async runTool(_spec: any, _input: any, ctx: any) { seen = ctx; return { ok: true, ref: "HO-1" }; },
    async callModel(_r: any, onText: (c: string) => void) {
      if (n++ === 0) return { content: [{ type: "tool_use", id: "t1", name: "request_human", input: { reason: "x" } }], usage };
      onText("Passed on."); return { content: [{ type: "text", text: "Passed on." }], usage };
    },
  };
  const ev = await run(cfg, "I want a person", deps);
  ok(seen.conversationId && seen.conversationId === ev.at(-1).conversationId, "the call knows its conversation");
  eqJson([seen.agentId, seen.handoff.assignment], ["app_assistant", "queue"], "its agent and the handoff settings");
}

eqJson(handoffNotice({ ref: "HO-1", status: "open", assignedToName: null }).includes("HO-1"), true, "the notice names the reference");
done("human handoff");
