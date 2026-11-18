/**
 * A record a process writes starts the process that watches that record.
 *
 * Only the data engine put a record's change on the event bus; a workflow's
 * db_insert / db_update / db_delete wrote straight to the table and said
 * nothing. In DITANS (wzml1sa6, 2026-11-18), where records mostly change
 * through processes, forge_events was empty and "Record Placement And Fee",
 * "Apply Credential Hold", "Record Application Stage Event" and "Ask Stage
 * Survey" had never once run.
 *
 * And a process that writes the record it watches is not started again by its
 * own change — not by itself, not through another process, not without end.
 *
 * Runs the SHIPPED workflows/index.ts write steps, workflows/engine.ts,
 * events/bus.ts and events/triggers.ts, over a stub database that keeps the
 * rows (and the forge_events table) in memory.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { pathToFileURL, fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const engineUrl = pathToFileURL(resolve(here, "../workflows/engine.ts")).href;

const g = globalThis as any;
g.__T = {} as Record<string, any[]>;
g.__EVENTS = [] as any[];
g.__WFS = [] as any[];
g.__STARTED = [] as Array<{ id: string; input: any }>;
g.__INFLIGHT = 0;

installHarness({
  stubs: {
    "drizzle-orm": `
      export const getTableName = (t) => t.__name;
      export const is = (v) => !!(v && v.__name);
      export class Table {}
      const op = (o) => (c, v) => ({ op: o, col: c && c.__col, v });
      export const eq = op("eq"), ne = op("ne"), gt = op("gt"), gte = op("gte"), lt = op("lt"), lte = op("lte");
      export const inArray = op("in"), notInArray = op("nin");
      export const and = (...parts) => ({ op: "and", parts: parts.filter(Boolean) });
      export const sql = (strings, ...values) => ({ text: strings.join("?"), values });`,
    "@/db/schema": `
      const table = (name, cols) => {
        const t = { __name: name };
        for (const c of ["id", ...cols]) t[c] = { __col: c, dataType: "string", columnType: "PgText" };
        return t;
      };
      export const applications = table("applications", ["stage", "candidateId", "fee"]);
      export const candidates = table("candidates", ["status", "applicationId"]);
      export const stageEvents = table("stage_events", ["applicationId", "stage", "fromStage"]);
      export const surveys = table("surveys", ["stageEventId"]);`,
    "@/db": `
      const rows = (t) => (globalThis.__T[t.__name] ??= []);
      const match = (r, p) => !p ? true
        : p.op === "and" ? p.parts.every((q) => match(r, q))
        : p.op === "eq" ? String(r[p.col]) === String(p.v)
        : true;
      let n = 0;
      export const db = {
        insert: (t) => ({ values: (v) => ({ returning: async () => {
          const r = { id: t.__name + "-" + (++n), ...v }; rows(t).push(r); return [{ ...r }];
        } }) }),
        update: (t) => ({ set: (v) => ({ where: (p) => ({ returning: async () => {
          const out = [];
          for (const r of rows(t)) if (match(r, p)) { Object.assign(r, v); out.push({ ...r }); }
          return out;
        } }) }) }),
        select: () => ({ from: (t) => ({ where: (p) => {
          const found = rows(t).filter((r) => match(r, p)).map((r) => ({ ...r }));
          const pr = Promise.resolve(found); pr.limit = async (k) => found.slice(0, k); return pr;
        } }) }),
        delete: (t) => ({ where: (p) => ({ returning: async () => {
          const out = rows(t).filter((r) => match(r, p));
          globalThis.__T[t.__name] = rows(t).filter((r) => !match(r, p));
          return out;
        } }) }),
        async execute(q) {
          const text = q.text || "";
          if (text.includes("INSERT INTO forge_events")) {
            const [type, entity, entity_id, payload] = q.values;
            const id = "evt-" + (globalThis.__EVENTS.length + 1);
            globalThis.__EVENTS.push({ id, type, entity, entity_id, payload: JSON.parse(payload), processed: false, error: null });
            return [{ id }];
          }
          if (text.includes("UPDATE forge_events SET processed_at")) {
            const claimed = globalThis.__EVENTS.filter((e) => !e.processed).slice(0, q.values[0]);
            for (const e of claimed) e.processed = true;
            return claimed.map(({ id, type, entity, entity_id, payload }) => ({ id, type, entity, entity_id, payload }));
          }
          if (text.includes("UPDATE forge_events SET error")) {
            const e = globalThis.__EVENTS.find((x) => x.id === q.values[1]);
            if (e) e.error = q.values[0];
            return [];
          }
          return [];
        },
      };`,
    // The bus starts a run the way the app's runtime does: through the engine.
    "@/lib/workflows": `
      import { executeWorkflow } from "${engineUrl}";
      export async function listWorkflows() { return globalThis.__WFS; }
      export async function triggerWorkflow(id, input, user) {
        globalThis.__INFLIGHT++;
        try {
          globalThis.__STARTED.push({ id, input });
          return await executeWorkflow(globalThis.__WFS.find((w) => w.id === id), input, user);
        } finally { globalThis.__INFLIGHT--; }
      }`,
    "../data-engine": `
      export const scopeForTable = async () => null;
      export const sealSensitive = async () => ({});
      export const _snapshotForAudit = (_n, r) => r;`,
    "../audit": "export const auditOn = () => false; export const recordAudit = async () => {}; export const actorOf = (u) => u;",
    "../sensitive-columns": "export const sensitiveColumnsFor = () => ({});",
    "../embeddings": "export const embedWrittenRow = async (_t, r) => r;",
    "@/lib/rules": "export const evaluateRuleSetForTable = async () => ({ errors: [], patches: {} });",
    "@/lib/error_reporter": "export const reportFromError = () => {};",
    "../fk-roles": "export const FK_ROLES = {}; export const fkRole = () => null; export const isDomainFk = () => false;",
    "./ai": "export const registerAIActions = () => {};",
    "./ocr": "export const registerOcrActions = () => {};",
    fs: "export const promises = {}; export default { promises };",
    path: "export default { join: (...a) => a.join('/'), resolve: (...a) => a.join('/') }; export const join = (...a) => a.join('/');",
  },
});

const triggers: any = await import("../events/triggers.ts");
const engine: any = await import("../workflows/engine.ts");
const wf: any = await import("../workflows/index.ts");
wf.registerDefaultActions();

const step = (key: string, config: Record<string, unknown>) =>
  ({ id: key, type: "action", data: { label: key, config } });
/** A process: started by `event` (or by hand), doing `steps` in order. */
function process(id: string, event: string | null, steps: Array<[string, Record<string, unknown>]>) {
  const nodes = [{ id: "start", type: "trigger", data: { label: "Start", config: {} } },
                 ...steps.map(([k, c]) => step(k, c)),
                 { id: "end", type: "end", data: { label: "Done", config: {} } }];
  const ids = nodes.map((n) => n.id);
  return {
    id, name: id,
    ...(event ? { trigger: { kind: "event", event } } : {}),
    definition: { trigger: { type: event ? "db_change" : "manual" }, nodes,
                  edges: ids.slice(1).map((t, i) => ({ id: `e${i}`, source: ids[i], target: t })) },
  };
}

/** Wait until nothing is left on the bus and no run is still going. */
async function settled(): Promise<void> {
  let quiet = 0;
  for (let i = 0; i < 400 && quiet < 5; i++) {
    await new Promise((r) => setTimeout(r, 5));
    quiet = g.__EVENTS.some((e: any) => !e.processed) || g.__INFLIGHT > 0 ? 0 : quiet + 1;
  }
}

function reset(wfs: any[], tables: Record<string, any[]>) {
  g.__WFS = wfs; g.__T = structuredClone(tables); g.__EVENTS = []; g.__STARTED = [];
}
const starts = (id: string) => g.__STARTED.filter((s: any) => s.id === id).length;
const person = { id: "u-1", role: "Recruiter" };

console.log("the name a change goes by is the one the Blueprint listens for");
// _trigger_contract: the table's export name, lowercased (vendor_accounts →
// vendorAccounts → vendoraccounts.created; test_a_record_change_starts_…py).
eqJson(triggers.recordEventType("vendor_accounts", "created"), "vendoraccounts.created", "a two-word table");
eqJson(triggers.recordEventType("applications", "updated"), "applications.updated", "a one-word table");

console.log("a record a process updates starts the process that watches it, once");
reset([
  process("move-stage", null, [["save", { actionType: "db_update", table: "applications",
    values: { stage: "{{stage}}" }, where: { id: "{{application}}" } }]]),
  process("record-stage-event", "applications.updated", [["write", { actionType: "db_insert", table: "stage_events",
    values: { applicationId: "{{entity.id}}", stage: "{{entity.stage}}", fromStage: "{{previousEntity.stage}}" } }]]),
  process("ask-stage-survey", "stageevents.created", [["ask", { actionType: "db_insert", table: "surveys",
    values: { stageEventId: "{{entity.id}}" } }]]),
], { applications: [{ id: "a-1", stage: "Applied" }] });
const moved = await engine.executeWorkflow(g.__WFS[0], { application: "a-1", stage: "Interview" }, person);
eqJson(moved.status, "completed", "the person's process moved the application");
await settled();
eqJson(g.__EVENTS.map((e: any) => e.type), ["applications.updated", "stageevents.created", "surveys.created"],
       "each write is on the bus, named from its table");
eqJson([starts("record-stage-event"), starts("ask-stage-survey")], [1, 1], "each watching process ran once");
eqJson(g.__T.stage_events.map((r: any) => [r.applicationId, r.fromStage, r.stage]), [["a-1", "Applied", "Interview"]],
       "the stage event says which application, from which stage, to which");
eqJson(g.__T.surveys.length, 1, "and the process watching stage events asked for its survey");
const first = g.__EVENTS[0].payload;
eqJson([first.entity?.stage, first.previousEntity?.stage, first.user?.id], ["Interview", "Applied", "u-1"],
       "the event carries the record, the record before, and who acted");
eqJson(g.__EVENTS[0].entity_id, "a-1", "and the record's id");
eqJson(g.__EVENTS.map((e: any) => e.error), [null, null, null], "nothing was held back");

console.log("a record a process creates or deletes is a change too");
reset([
  process("add-and-remove", null, [
    ["add", { actionType: "db_insert", table: "candidates", values: { status: "new" } }],
    ["drop", { actionType: "db_delete", table: "candidates", where: { id: "{{add.id}}" } }],
  ]),
  process("on-delete", "candidates.deleted", []),
], { candidates: [] });
await engine.executeWorkflow(g.__WFS[0], {}, person);
await settled();
eqJson(g.__EVENTS.map((e: any) => e.type), ["candidates.created", "candidates.deleted"], "created, then deleted");
eqJson(starts("on-delete"), 1, "the process watching deletions ran");

console.log("a process that updates the record it watches runs once per change, not for ever");
reset([
  process("record-fee", "applications.updated", [["fee", { actionType: "db_update", table: "applications",
    values: { fee: "100" }, where: { id: "{{entity.id}}" } }]]),
], { applications: [{ id: "a-1", stage: "Offer" }] });
await engine.executeWorkflow(process("place", null, [["save", { actionType: "db_update", table: "applications",
  values: { stage: "Placed" }, where: { id: "{{application}}" } }]]), { application: "a-1" }, person);
await settled();
eqJson(starts("record-fee"), 1, "it ran for the person's change, once");
eqJson(g.__T.applications[0].fee, "100", "and did its work");
eqJson(g.__EVENTS.length, 2, "its own change is on the bus, as any change is");
ok(String(g.__EVENTS[1].error ?? "").includes("record-fee was not started: this change came from its own run"),
   "and the event says why it started nothing");
eqJson(g.__EVENTS[1].payload.__eventChain, ["place", "record-fee"], "the chain behind that change");

console.log("two processes that change each other's records stop when the chain comes back round");
reset([
  process("sync-candidate", "applications.updated", [["c", { actionType: "db_update", table: "candidates",
    values: { status: "{{entity.stage}}" }, where: { applicationId: "{{entity.id}}" } }]]),
  process("sync-application", "candidates.updated", [["a", { actionType: "db_update", table: "applications",
    values: { stage: "{{entity.status}}" }, where: { id: "{{entity.applicationId}}" } }]]),
], { applications: [{ id: "a-1", stage: "Applied" }], candidates: [{ id: "c-1", applicationId: "a-1", status: "Applied" }] });
await engine.executeWorkflow(process("move", null, [["save", { actionType: "db_update", table: "applications",
  values: { stage: "Hired" }, where: { id: "{{application}}" } }]]), { application: "a-1" }, person);
await settled();
eqJson([starts("sync-candidate"), starts("sync-application")], [1, 1], "each ran once");
eqJson([g.__T.applications[0].stage, g.__T.candidates[0].status], ["Hired", "Hired"], "and both records agree");

console.log("a long chain of different processes stops at its limit");
eqJson(triggers.eventChainRefusal(["a"], "b"), null, "a process after another starts");
ok(triggers.eventChainRefusal(Array.from({ length: triggers.MAX_EVENT_CHAIN }, (_, i) => `p${i}`), "next") !== null,
   `the ${triggers.MAX_EVENT_CHAIN + 1}th in a row does not`);
eqJson(triggers.eventChainAfter({}, "w"), ["w"], "a run nothing started begins a chain");
eqJson(triggers.eventChainAfter({ __eventChain: ["a"] }, "b"), ["a", "b"], "a started run adds itself");

console.log("an event a process emits carries its chain, so a process emitting what it listens for stops");
reset([
  process("echo", "ping.sent", [["emit", { actionType: "emit_event", event: "ping.sent" }]]),
], {});
await engine.executeWorkflow(process("start-ping", null, [["emit", { actionType: "emit_event", event: "ping.sent" }]]), {}, person);
await settled();
eqJson(starts("echo"), 1, "echo ran once");
eqJson(g.__EVENTS.length, 2, "and emitted once");

done("a process write starts the process that watches it");
