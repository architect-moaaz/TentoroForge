/**
 * A formula written as a workflow value is worked out.
 *
 * `{{x = "y" or z}}` or `{{if a = "b" then "c" else "d"}}` in a db_insert /
 * db_update `values` map was kept as its own text: only `{{path}}` and
 * `{{a ?? b}}` were resolved, so the column got the braces or nothing. CARES
 * (kkb5mzo3, 2026-11-10) moved every such value into a set_variable step,
 * which does evaluate. A template that is not a formula is left as before.
 *
 * Runs the SHIPPED workflows/index.ts with the SHIPPED feel-lite.
 * (Stubs shared with today-is-a-calendar-date.test.mts.)
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
(globalThis as any).__secrets = {};
(globalThis as any).__connected = {};
(globalThis as any).__persisted = [] as any[];
(globalThis as any).__mailed = [];

installHarness({
  stubs: {
    "@/db": "export const db = { insert: (t) => ({ values: (v) => { globalThis.__persisted.push(v); const r = Promise.resolve([v]); r.returning = async () => [{ ...v, id: 'n-1' }]; return r; } }), execute: async () => ({ rows: [] }) };",
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": "export const forgeNotifications = (globalThis.__ntf = { __name: 'forge_notifications' });",
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'x'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = (c, v) => ({ op: 'eq', col: c && c.__col, v }); export const and = (...p) => ({ op: 'and', parts: p }); export const sql = (...a) => ({ __sql: a }); export const ne = (c, v) => ({ op: 'ne', col: c && c.__col, v }); export const gt = (c, v) => ({ op: 'gt', col: c && c.__col, v }); export const gte = (c, v) => ({ op: 'gte', col: c && c.__col, v }); export const lt = (c, v) => ({ op: 'lt', col: c && c.__col, v }); export const lte = (c, v) => ({ op: 'lte', col: c && c.__col, v }); export const inArray = (c, v) => ({ op: 'inArray', col: c && c.__col, v }); export const notInArray = (c, v) => ({ op: 'notInArray', col: c && c.__col, v });",
    "@/lib/error_reporter": "export const reportFromError = () => {};",
    "../fk-roles": "export const FK_ROLES = {}; export const fkRole = () => null; export const isDomainFk = () => false;",
    "@/lib/rules": "export const evaluateRuleSetForTable = async () => ({ errors: [], patches: {} });",
    "@/lib/integrations/resolver": "export const getSecret = async (_p, k) => globalThis.__secrets[k]; export const clearSecretCache = () => {};",
    "@/lib/integrations/connected": "export const connectedService = (a) => globalThis.__connected[a]; export const CONNECTED_SERVICES = globalThis.__connected;",
    // nodemailer is CommonJS: Node's interop gives the shipped code a named
    // `createTransport` as well as a default, and it calls the named one.
    nodemailer: "export const createTransport = () => ({ sendMail: async (m) => { globalThis.__mailed.push(m); return { messageId: 'mid-1' }; } }); export default { createTransport };",
    "./engine": "globalThis.__handlers = {}; export const getActionHandler = (n) => globalThis.__handlers[n]; export const registerActionHandler = (n, h) => { globalThis.__handlers[n] = h; }; export const registerStepHandler = () => {}; export const executeWorkflow = async () => ({}); export const WorkflowEngine = class {}; export const getEngine = () => ({}); export const registerTriggerHandler = () => {}; export const runWorkflow = async () => ({});",
    "./ai": "export const registerAIActions = () => {};",
    "./ocr": "export const registerOcrActions = () => {};",
    "../events/emit-node": "export const makeEmitEventHandler = () => async () => ({});",
    "./types": noop,
    fs: "export const promises = {}; export default { promises };",
    path: "export default { join: (...a) => a.join('/'), resolve: (...a) => a.join('/') }; export const join = (...a) => a.join('/');",
  },
});

const mod: any = await import("../workflows/index.ts");
const ctx: any = { input: {}, variables: {
  severity: "Severe", escalated: false, tier: "A", totalCents: 1250,
  position: { budgetedHeadcount: 5, filledHeadcount: 3 }, case: { id: "c-1" },
}, log: [] };

eqJson(mod._resolveRef('{{severity = "Severe" or escalated}}', ctx), true, "a comparison with or is worked out");
eqJson(mod._resolveRef('{{if tier = "A" then "GeneralManager" else "Ops"}}', ctx), "GeneralManager", "an if is worked out");
eqJson(mod._resolveRef("{{totalCents / 100}}", ctx), 12.5, "arithmetic is a number, not text");
eqJson(mod._resolveRef("{{ position.budgetedHeadcount - position.filledHeadcount }}", ctx), 2, "arithmetic on paths");

// What was already worked out is unchanged.
eqJson(mod._resolveRef("{{case.id}}", ctx), "c-1", "a path is still its value");
eqJson(mod._resolveRef('{{missing ?? "none"}}', ctx), "none", "?? is still a value or else another");
eqJson(mod._resolveRef("Tier {{tier}}", ctx), "Tier A", "a template inside text is still text");
eqJson(mod._resolveRef("{{item.sentAt|date:en}}", ctx), "{{item.sentAt|date:en}}", "a template that is not a formula is left as written");

// Through the write path: what a db_insert/db_update stores.
const row = mod._resolveValueMap({
  isUrgent: '{{severity = "Severe" or escalated}}',
  approver: '{{if tier = "A" then "GeneralManager" else "Ops"}}',
  status: "Open",
}, ctx);
eqJson(row, { isUrgent: true, approver: "GeneralManager", status: "Open" }, "a write stores the worked-out values");
ok(!JSON.stringify(row).includes("{{"), "no braces reach the row");

// The engine's own copy, which an end's reply and a set_variable's value use.
const { interpolateValue } = await import("../workflows/engine.ts");
const vars = { ...ctx.variables, "node-3": { output: "kept" }, rows: [{ id: "r-1" }] };
eqJson(interpolateValue("{{totalCents / 100}}", vars), 12.5, "the engine works a whole-value formula out too");
eqJson(interpolateValue('{{if tier = "A" then "GeneralManager" else "Ops"}}', vars), "GeneralManager", "an if, in the engine");
eqJson(interpolateValue("{{node-3.output}}", vars), "kept", "a hyphenated name is still a name, not subtraction");
eqJson(interpolateValue("{{rows[0].id}}", vars), "r-1", "a path with an index is still a path");
eqJson(interpolateValue('{{missing ?? "none"}}', vars), "none", "?? in the engine as before");
eqJson(interpolateValue("Tier {{tier}}", vars), "Tier A", "a template inside text as before");
eqJson(mod._resolveRef("{{node-3.output}}", { ...ctx, variables: vars }), "{{node-3.output}}",
       "the workflow module leaves a hyphenated name as it did, never subtraction");

done("write-value formula");
