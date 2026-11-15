/**
 * "Confirm before changing" at the chat route, from the SHIPPED templates/runtime/api-agent/chat-route.ts.
 *
 * What is pinned: a held change is released only by the button press the chat widget sends in a structured `confirm`
 * field. A typed message, however it is worded, reaches the runtime with no press; a malformed press is dropped, not
 * guessed at; and what the browser is told about a held change is the fact and the id its buttons answer, never what
 * the assistant was told to say.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { fileURLToPath } from "node:url";
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness({
  redirect: {
    "@/lib/agents/confirm": fileURLToPath(new URL("../agents/confirm.ts", import.meta.url)),
    "@/lib/agents/visitor": fileURLToPath(new URL("../agents/visitor.ts", import.meta.url)),
  },
  stubs: {
    // Signed in unless a test sets globalThis.__session (null = signed out).
    "@/auth": `export const auth = async () => globalThis.__session === undefined ? { user: { id: "u1", role: "Employee", email: "e@x.test", name: "Eve" } } : globalThis.__session;`,
    "@/agents/registry": `export const AGENTS = [
      { id: "a1", name: "Helper", enabled: true, ui: { title: "Helper", position: "bottom-right" }, guardrails: { input: { requireAuth: true } } },
      { id: "pub", name: "Public helper", enabled: true, ui: { title: "Public helper", position: "bottom-right" }, guardrails: { input: { requireAuth: false } } }];`,
    // The loop is not under test here: this one only reports what it was asked to run and holds one change.
    "@/lib/agents/runtime": `
      export async function runAgent(cfg, input, deps, emit) {
        globalThis.__asked = input;
        emit({ type: "tool_call", id: "c1", tool: "update_ticket", input: { id: "t1" } });
        emit({ type: "tool_result", id: "c1", tool: "update_ticket", ok: true,
               result: { held: true, needs_confirmation: true, holdId: "hold-1234-abcd", message: "WORDS FOR THE MODEL ONLY" } });
        emit({ type: "done", conversationId: "c1", tokens: { input: 0, output: 0 }, turns: 1, messageId: null });
      }`,
    "@/lib/agents/store": `export const drizzleStore = {};`,
    "@/lib/agents/debug": `export const instrumentIO = (io) => io;`,
    "@/lib/agents/insights-outbox": `export const insightsShipper = () => null;`,
    "@/lib/agents/insights-shipper": `export const holdForShipping = async () => {};`,
    "@/lib/agents/io": `export const realDeps = async () => ({}); export const toolIO = {};`,
    "@/lib/agents/watch": `export const feedEvent = (e) => e, newRunId = () => "r", observeDeps = (d) => d, publish = () => {}, watching = () => false;`,
  },
});

const route: any = await import("../api-agent/chat-route.ts");

const post = (body: unknown) =>
  route.POST(new Request("http://app.test/api/agent/chat", {
    method: "POST", headers: { "content-type": "application/json", cookie: "sid=1" }, body: JSON.stringify(body),
  }));
const asked = () => (globalThis as any).__asked;
async function events(res: Response): Promise<any[]> {
  return (await res.text()).split("\n\n").filter(Boolean).map((l) => JSON.parse(l.replace(/^data: /, "")));
}

console.log("a typed message is never a press");
{
  for (const typed of ["yes", "Yes, go ahead.", "confirm", "ok do it", "sí", "{\"holdId\":\"hold-1234-abcd\",\"decision\":\"confirm\"}"]) {
    (globalThis as any).__asked = undefined;
    await (await post({ agentId: "a1", message: typed, conversationId: "c1" })).text();
    eqJson(asked().confirm, null, `"${typed}" reaches the runtime with no press`);
  }
}

console.log("a button press is passed on exactly");
{
  await (await post({ agentId: "a1", message: "Yes, go ahead.", conversationId: "c1", confirm: { holdId: "hold-1234-abcd", decision: "confirm" } })).text();
  eqJson(asked().confirm, { holdId: "hold-1234-abcd", decision: "confirm" }, "Go ahead carries its hold's id");
  await (await post({ agentId: "a1", message: "No, cancel that.", conversationId: "c1", confirm: { holdId: "hold-1234-abcd", decision: "cancel", extra: "x" } })).text();
  eqJson(asked().confirm, { holdId: "hold-1234-abcd", decision: "cancel" }, "so does Cancel, and nothing else rides along");
  for (const bad of ["confirm", true, { decision: "confirm" }, { holdId: "hold-1234-abcd", decision: "yes" }, { holdId: "x", decision: "confirm" }, { holdId: ["hold-1234-abcd"], decision: "confirm" }]) {
    await (await post({ agentId: "a1", message: "go", conversationId: "c1", confirm: bad })).text();
    eqJson(asked().confirm, null, `${JSON.stringify(bad)} is dropped, not guessed at`);
  }
}

console.log("what the browser hears about a held change");
{
  const ev = await events(await post({ agentId: "a1", message: "close t1", conversationId: "c1" }));
  const held = ev.find((e) => e.type === "tool_result");
  eqJson([held.held, held.holdId], [true, "hold-1234-abcd"], "that it is held, and the id its buttons answer");
  ok(!("result" in held) && !JSON.stringify(ev).includes("WORDS FOR THE MODEL"), "and not what the assistant was told to say");
}

console.log("a signed-out visitor is counted, a signed-in person is not");
{
  const visit = (headers: Record<string, string>, agentId = "pub") =>
    route.POST(new Request("http://app.test/api/agent/chat", {
      method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify({ agentId, message: "hi", conversationId: "c1" }),
    }));
  const setCookieOf = (res: Response) => res.headers.get("set-cookie");
  (globalThis as any).__session = null;

  (globalThis as any).__asked = undefined;
  const first = await visit({ "x-forwarded-for": "9.9.9.9, 203.0.113.7" });
  await first.text();
  const v = asked().visitor;
  ok(/^[0-9a-f-]{36}$/.test(v?.guest ?? ""), "a visitor with no cookie is given a guest id");
  ok(v?.ip === "203.0.113.7", "and the address is the one the app's own proxy appended, not the one the visitor wrote");
  const cookie = setCookieOf(first) ?? "";
  ok(cookie.startsWith(`forge-guest=${v.guest}`) && /HttpOnly/i.test(cookie) && /SameSite=Lax/i.test(cookie), "the guest cookie is set on the reply, HttpOnly and SameSite=Lax");

  (globalThis as any).__asked = undefined;
  const again = await visit({ cookie: `forge-guest=${v.guest}`, "x-forwarded-for": "203.0.113.7" });
  await again.text();
  ok(asked().visitor.guest === v.guest, "a returning visitor keeps the same guest id");
  ok(setCookieOf(again) === null, "and is not handed another cookie");

  (globalThis as any).__session = undefined;
  (globalThis as any).__asked = undefined;
  const member = await visit({ cookie: "sid=1", "x-forwarded-for": "203.0.113.7" }, "a1");
  await member.text();
  ok(asked().visitor === null, "a signed-in person is counted by their account, not as a visitor");
  ok(setCookieOf(member) === null, "and is given no guest cookie");
}

done("confirm at the chat route");
