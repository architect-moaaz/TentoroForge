/**
 * `$today` is a calendar date, and a date column kept as text by Drizzle
 * (`date()`'s string mode) is written text, whatever reaches it: a Date
 * crashed the driver, and AquaTrack's "Find Today's Summary" failed on every
 * run (m1dck85j, 2026-10-12). A timestamp column still takes a Date. Runs the
 * SHIPPED workflows/index.ts.
 *
 * (Stubs shared with a-filter-can-hold-a-range.test.mts.)
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
    "../feel-lite": "export const evaluateExpression = () => null;",
    "./types": noop,
    fs: "export const promises = {}; export default { promises };",
    path: "export default { join: (...a) => a.join('/'), resolve: (...a) => a.join('/') }; export const join = (...a) => a.join('/');",
  },
});

const mod: any = await import("../workflows/index.ts");
const ctx = { input: {}, variables: {}, log: [] };
const today = mod._resolveRef("$today", ctx);
ok(typeof today === "string" && /^\d{4}-\d{2}-\d{2}$/.test(today), "$today is YYYY-MM-DD");
eqJson(today, mod._calendarDate(new Date()), "on the server's own calendar");

const table: any = {
  date: { __col: "date", dataType: "string", columnType: "PgDateString" },
  loggedAt: { __col: "loggedAt", dataType: "date", columnType: "PgTimestamp" },
  stamp: { __col: "stamp", dataType: "string", columnType: "PgTimestampString" },
};
const w1 = mod._buildWhere(table, { date: "$today" }, ctx);
eqJson([w1.op, w1.v], ["eq", today], "a date column is filtered by text");
const w2 = mod._buildWhere(table, { date: "$now" }, ctx);
eqJson([w2.op, typeof w2.v, w2.v], ["eq", "string", today], "a moment reaching a date column is its calendar date");
const w3 = mod._buildWhere(table, { date: { gte: "2026-10-01T09:30:00.000Z" } }, ctx);
eqJson(w3.v, "2026-10-01", "an ISO moment is cut to its date");
const w4 = mod._buildWhere(table, { loggedAt: { gte: "$today" } }, ctx);
ok(w4.v instanceof Date, "a timestamp column still gets a Date");
const w5 = mod._buildWhere(table, { stamp: "$now" }, ctx);
ok(typeof w5.v === "string" && w5.v.endsWith("Z"), "a timestamp kept as text gets ISO text");
done();
