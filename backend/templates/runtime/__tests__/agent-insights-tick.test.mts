/**
 * The route the cron tick asks for the insights catch-up (api-agent/insights-tick-route.ts, installed at
 * /api/cron/insights), and the tick's own call to it (api-cron/route.ts).
 *
 * What is pinned: the route is guarded exactly like the tick (CRON_SECRET as a Bearer header or ?secret=), answers with
 * counts only, says a plain sentence when it fails, and the tick asks for it on every real run, not on a what-if clock,
 * not when the app has no such route (404), and never fails because of it.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const g = globalThis as any;
g.__secret = undefined;
g.__tick = async () => ({ configured: true, sent: 3, skipped: 0, waiting: false, pruned: 1 });
installHarness({
  stubs: {
    "@/lib/agents/insights-outbox": "export const runInsightsTick = (...a) => globalThis.__tick(...a);",
    "@/lib/integrations/resolver": "export const getSecret = async () => globalThis.__secret;",
    "@/lib/workflows": "export const listWorkflows = async () => []; export const triggerWorkflow = async () => ({});",
    "@/lib/runtime-loader": "export const initializeRuntime = async () => {};",
    "@/db": "export const db = {};",
    "@/db/schema/_forge_schedules": "export const forgeSchedules = {};",
    "drizzle-orm": "export const eq = () => 0;",
    "@/lib/events/scheduler": "export const runDueSchedules = async () => ({ fired: [] }); export const fireSchedule = async () => ({ fired: false });",
    "@/lib/workflows/escalation": "export const processTaskEscalations = async () => ({ escalated: 0 });",
    "@/lib/events/bus": "export const processPendingEvents = async () => null; export const resumeExpiredWaits = async () => 0;",
    "@/lib/events/triggers": "export const getTriggerContract = () => null;",
    "@/lib/audit": "export const pruneByPolicy = async () => 0;",
  },
});

const insightsRoute = await import("../api-agent/insights-tick-route.ts");
const get = async (h: (r: Request) => Promise<Response>, url: string, headers: Record<string, string> = {}) => {
  const res = await h(new Request(url, { headers }));
  return { status: res.status, text: await res.text() };
};

console.log("the catch-up route");
{
  let r = await get(insightsRoute.GET, "http://app/api/cron/insights");
  eqJson([r.status, JSON.parse(r.text)], [200, { configured: true, sent: 3, skipped: 0, waiting: false, pruned: 1 }], "with no secret set it answers, with counts only");
  g.__secret = "s3cret";
  r = await get(insightsRoute.POST, "http://app/api/cron/insights");
  eqJson(r.status, 401, "with a secret set, a request without it is turned away");
  r = await get(insightsRoute.POST, "http://app/api/cron/insights", { authorization: "Bearer wrong" });
  eqJson(r.status, 401, "so is a wrong one");
  r = await get(insightsRoute.POST, "http://app/api/cron/insights", { authorization: "Bearer s3cret" });
  eqJson(r.status, 200, "the Bearer header works");
  r = await get(insightsRoute.GET, "http://app/api/cron/insights?secret=s3cret");
  eqJson(r.status, 200, "and so does ?secret=");
  g.__tick = async () => { throw new Error('relation "forge_agent_turns" does not exist at pg.js:99'); };
  const realWarn = console.warn;
  console.warn = () => {};
  r = await get(insightsRoute.GET, "http://app/api/cron/insights?secret=s3cret");
  console.warn = realWarn;
  ok(r.status === 500 && JSON.parse(r.text).error === "Could not run the insights catch-up." && !r.text.includes("pg.js"), "a failure is one plain sentence with nothing of the cause");
  g.__secret = undefined;
}

// The tick as the agent install leaves it: the same file with its one switch turned on (agent_runtime_install.py).
const shipped = readFileSync(new URL("../api-cron/route.ts", import.meta.url), "utf8");
const off = "const HAS_AGENT_INSIGHTS = false; // forge-agent-insights";
ok(shipped.includes(off), "as shipped, the tick's insights call is switched off");
const withAgents = join(mkdtempSync(join(tmpdir(), "forge-tick-")), "route.ts");
writeFileSync(withAgents, shipped.replace(off, off.replace("false", "true")));

console.log("an app without agents");
{
  const tick = await import("../api-cron/route.ts");
  let calls = 0;
  g.fetch = async () => { calls++; return Response.json({ configured: true, sent: 2 }); };
  const res = await tick.GET(new Request("http://app.test/api/cron/tick"));
  const body: any = await res.json();
  ok(calls === 0 && res.status === 200 && !("insights" in body) && Array.isArray(body.fired), "the tick never asks for the catch-up (no wasted 404), and still runs");
}

console.log("the tick asks for it");
{
  const tick = await import(pathToFileURL(withAgents).href);
  const asked: Array<{ url: string; auth: string | null; method: string }> = [];
  let answer: () => Response | Promise<Response> = () => Response.json({ configured: true, sent: 2 });
  g.fetch = async (url: string, init: any) => {
    asked.push({ url: String(url), auth: init?.headers?.authorization ?? null, method: init?.method });
    return answer();
  };
  let res = await tick.GET(new Request("http://app.test/api/cron/tick"));
  let body: any = await res.json();
  eqJson([asked.length, asked[0]?.url, asked[0]?.method, body.insights], [1, "http://app.test/api/cron/insights", "POST", { configured: true, sent: 2 }], "a real run asks for the catch-up and shows its counts");
  eqJson(asked[0].auth, null, "with no secret set it carries none");
  g.__secret = "s3cret";
  asked.length = 0;
  res = await tick.GET(new Request("http://app.test/api/cron/tick", { headers: { authorization: "Bearer s3cret" } }));
  eqJson(asked[0]?.auth, "Bearer s3cret", "with a secret set it passes the same one on");
  asked.length = 0;
  res = await tick.GET(new Request("http://app.test/api/cron/tick?at=2030-01-01T00:00:00Z", { headers: { authorization: "Bearer s3cret" } }));
  eqJson(asked.length, 0, "a what-if clock (?at=) never touches real data");
  g.__secret = undefined;
  answer = () => new Response("not found", { status: 404 });
  res = await tick.GET(new Request("http://app.test/api/cron/tick"));
  body = await res.json();
  ok(res.status === 200 && !("insights" in body), "an app without the route (404) just has no insights part");
  answer = () => { throw new Error("network down"); };
  res = await tick.GET(new Request("http://app.test/api/cron/tick"));
  ok(res.status === 200 && Array.isArray((await res.json()).fired), "a catch-up that cannot be reached never fails the tick");
  process.env.FORGE_INTERNAL_URL = "http://127.0.0.1:3000/";
  asked.length = 0;
  answer = () => Response.json({});
  await tick.GET(new Request("http://public.example/api/cron/tick"));
  eqJson(asked[0].url, "http://127.0.0.1:3000/api/cron/insights", "FORGE_INTERNAL_URL is honoured, as the agents' own calls do");
  delete process.env.FORGE_INTERNAL_URL;
}

done("insights tick route");
