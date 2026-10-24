/**
 * The helpers behind watching the app live, from the SHIPPED files in templates/runtime/agents/.
 *
 * What is pinned: the secret is compared without leaking; a tool's result goes to the builder whole, or cut with its
 * size said when it is huge; and what a tool did in the app is reported with the real method, route and status while
 * its result still passes through untouched, and a failure still fails.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();

const { instrumentIO, sameSecret, wireResult, MAX_RESULT_WIRE_CHARS } = await import("../agents/debug.ts");

console.log("the secret");
{
  ok(sameSecret("abc123", "abc123"), "the same secret matches");
  ok(!sameSecret("abc123", "abc124") && !sameSecret("abc123", "abc12") && !sameSecret("abc123", ""), "anything else does not");
  ok(!sameSecret("", ""), "and an empty secret never does");
}

console.log("what goes to the builder");
{
  const w = wireResult({ rows: [1, 2, 3] });
  ok(w.cut === false && w.chars > 0, "a small result goes whole");
  const big = wireResult({ blob: "x".repeat(MAX_RESULT_WIRE_CHARS + 500) });
  ok(big.cut === true && big.chars > MAX_RESULT_WIRE_CHARS && String(big.result).length <= MAX_RESULT_WIRE_CHARS + 2, "a huge one is cut, and says how big it was");
}

console.log("what the tools did in the app is reported, with the real method, route and status");
{
  const sent: any[] = [];
  const base: any = {
    async fetchInternal(path: string, init: any) {
      init.onResponse?.(path.includes("missing") ? 404 : 200);
      if (path.includes("missing")) throw new Error("Not found");
      return { data: [] };
    },
    async triggerWorkflow() { return { status: "completed" }; },
    async callMcp() { return "ok"; },
    async runAi() { return { label: "x" }; },
  };
  const io = instrumentIO(base, (e) => sent.push(e));

  eqJson(await io.fetchInternal("/api/data/tickets", { method: "GET", query: { status: "open", limit: 1 } }, {} as any), { data: [] }, "the answer passes through untouched");
  const get = sent.at(-1);
  eqJson([get.type, get.kind, get.method, get.label, get.status, get.ok], ["app_call", "request", "GET", "/api/data/tickets", 200, true], "a read: its method, route and status");
  eqJson(get.query, { status: "open", limit: 1 }, "with the filters it sent");
  ok(!("body" in get) && typeof get.ms === "number", "no body for a read, and its time");

  await io.fetchInternal("/api/data/tickets/t1", { method: "PUT", body: { data: { status: "closed" } } }, {} as any);
  eqJson(sent.at(-1).body, { data: { status: "closed" } }, "a change shows what was sent");
  eqJson(sent.at(-1).method, "PUT", "and its method");

  let threw = false;
  try { await io.fetchInternal("/api/data/missing", { method: "GET" }, {} as any); } catch { threw = true; }
  ok(threw, "a failure still fails the tool");
  eqJson([sent.at(-1).ok, sent.at(-1).status, sent.at(-1).error], [false, 404, "Not found"], "and is shown with its status and why");

  await io.triggerWorkflow("assign_ticket", { id: "t1" }, null);
  eqJson([sent.at(-1).kind, sent.at(-1).label, sent.at(-1).body], ["workflow", "assign_ticket", { id: "t1" }], "a workflow, by name, with its input");
  await io.callMcp("srv", "search", { q: "x" });
  eqJson([sent.at(-1).kind, sent.at(-1).label], ["mcp", "srv/search"], "an MCP tool");
  await io.runAi("classify", {}, { input: "x" }, null);
  eqJson([sent.at(-1).kind, sent.at(-1).label], ["ai", "classify"], "an AI action");

  await io.fetchInternal("/api/data/x", { method: "POST", body: { blob: "y".repeat(5000) } }, {} as any);
  ok(String(sent.at(-1).body).length <= 2002, "a huge body is cut for the screen");
}

done("watching the app live: its helpers");
