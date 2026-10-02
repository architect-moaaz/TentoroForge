/**
 * What a generated application tells Forge when it breaks, and what it must
 * never tell it.
 *
 * Runs the SHIPPED `error_reporter.ts` — its incident-map import stubbed with
 * a small application's declared routes and wires, `fetch` replaced by a
 * recorder. The rules under test are the two structural ones: a route leaves
 * as the pattern it matched or not at all, and nothing on this path can reach
 * a value.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

process.env.FORGE_URL = "http://forge.test";
process.env.FORGE_PROJECT_ID = "project-1";
process.env.FORGE_SLOW_MS = "2000";

installHarness({
  stubs: {
    "@/lib/incident-map": `
      export const ROUTES = ["/", "/cases", "/cases/[id]", "/cases/[id]/notes"];
      export const CONTROLS = {
        "approve-case": [{ route: "/cases/[id]", control: "Button", label: "Approve" }],
        "delete-case": [
          { route: "/cases", control: "Table.rowActions[0]", label: "Delete" },
          { route: "/cases/[id]", control: "Button", label: "Delete Case" },
        ],
      };
    `,
  },
});

const sent: Array<{ url: string; body: any }> = [];
(globalThis as any).fetch = async (url: string, init: any) => {
  sent.push({ url, body: JSON.parse(init.body) });
  return { ok: true };
};

const mod: any = await import("../error_reporter.ts");
const { routePattern, controlFor, reportRuntimeException, reportSlowResponse, measured } = mod;

// ── The route is a pattern, never a URL ────────────────────────────────────

eqJson(routePattern("/cases/8f2a1b3c-0000-4000-8000-000000000001"), "/cases/[id]",
       "a record id is reported as the pattern it matched, never as itself");
eqJson(routePattern("/cases"), "/cases", "a static route is itself");
eqJson(routePattern("/cases/8f2a/notes"), "/cases/[id]/notes", "nested patterns match");
eqJson(routePattern("/cases?q=jane%40example.com"), "/cases",
       "the query string is dropped — it is where a customer ends up");
eqJson(routePattern("/admin/secrets"), undefined,
       "a path this application does not declare is not reported at all");
eqJson(routePattern("/cases/a/b/c"), undefined, "a deeper path matches nothing");
eqJson(routePattern(""), undefined, "nothing in, nothing out");

// ── The control, when the contract names exactly one ───────────────────────

eqJson(controlFor("approve-case"), { route: "/cases/[id]", control: "Button", label: "Approve" },
       "a workflow with one wire names its control");
eqJson(controlFor("delete-case"), undefined,
       "two controls run it and nothing says which — naming the wrong button is worse than none");
eqJson(controlFor("delete-case", "/cases")?.label, "Delete",
       "the route it happened on tells them apart");
eqJson(controlFor("no-such-workflow"), undefined, "an unknown workflow names nothing");

// ── A crash carries names, and the report fills in the control ─────────────

sent.length = 0;
reportRuntimeException({
  kind: "workflow",
  message: "recipient is empty",
  stack: "at Object.run (src/lib/workflows/index.ts:42:3)",
  workflow_id: "approve-case",
  node_id: "notify",
  action_type: "send_email",
  payload_keys: ["caseId", "recipient"],
  role: "Case Worker",
});
eqJson(sent.length, 1, "the crash is sent");
eqJson(sent[0].url, "http://forge.test/api/projects/project-1/runtime-exceptions",
       "to the ingest endpoint for this project");
eqJson(sent[0].body.control, "Button", "the control is resolved from the app's own contract");
eqJson(sent[0].body.control_label, "Approve", "and named the way the owner named it");
eqJson(sent[0].body.payload_keys, ["caseId", "recipient"],
       "the KEYS the control sent");
eqJson(Object.keys(sent[0].body).sort(), [
  "action_type", "control", "control_label", "kind", "message", "node_id",
  "occurrences", "payload_keys", "role", "stack", "workflow_id",
], "and nothing else — no body, no user, no fields this file did not put there");
ok(!("page_route" in sent[0].body),
   "no route on the server, where there is no location to read — and none invented");

sent.length = 0;
reportRuntimeException({ kind: "page_render", message: "render failed",
                         page_route: "/cases/[id]" });
eqJson(sent[0].body.page_route, "/cases/[id]", "a route the caller knows rides along");

// ── A crash loop is one thing to fix, and the count stays true ─────────────

sent.length = 0;
for (let i = 0; i < 5; i++) {
  reportRuntimeException({ kind: "workflow", message: "same failure",
                           workflow_id: "approve-case", node_id: "notify" });
}
eqJson(sent.length, 1, "five identical crashes in a moment are one report");
reportRuntimeException({ kind: "workflow", message: "a different failure",
                         workflow_id: "approve-case", node_id: "notify" });
eqJson(sent.length, 2, "a different crash is its own report");
eqJson(sent[0].body.occurrences, 1, "the first one stands for itself");

// ── Slow responses ────────────────────────────────────────────────────────

sent.length = 0;
reportSlowResponse({ operation: "approve-case", workflow_id: "approve-case", ms: 4200 });
eqJson(sent.length, 1, "a slow response is reported");
eqJson(sent[0].url, "http://forge.test/api/projects/project-1/incidents",
       "to the incident ledger, which has nothing to heal and nothing to dedup");
eqJson(sent[0].body.kind, "slow", "as a slow incident");
eqJson(sent[0].body.ms, 4200, "with what was measured");
eqJson(sent[0].body.thresholdMs, 2000, "and what it was measured against");
eqJson(sent[0].body.label, "Approve", "named by the control that runs it");

sent.length = 0;
reportSlowResponse({ operation: "approve-case", workflow_id: "approve-case", ms: 1900 });
eqJson(sent.length, 0, "under the threshold is not an incident");

sent.length = 0;
for (let i = 0; i < 4; i++) {
  reportSlowResponse({ operation: "list", entity: "cases", ms: 2500 });
}
eqJson(sent.length, 4,
       "slow observations never coalesce — for slowness the repeats ARE the measurement");

// ── `measured` is beside the work, never in front of it ───────────────────

sent.length = 0;
eqJson(await measured({ operation: "list", entity: "cases" }, async () => "the rows"),
       "the rows", "it returns exactly what it was given to run");
eqJson(sent.length, 0, "a fast call is not reported");

let threw: string | null = null;
try {
  await measured({ operation: "create", entity: "cases" }, async () => {
    throw new Error("the driver refused");
  });
} catch (e: any) {
  threw = e.message;
}
eqJson(threw, "the driver refused", "and re-throws exactly what that threw");

done("error reporter");
