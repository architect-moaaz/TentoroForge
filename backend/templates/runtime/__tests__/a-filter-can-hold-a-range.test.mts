/**
 * A filter may hold several comparisons on one field, ANDed: a range. The
 * export by date applied its start and dropped its end because the engine
 * took one comparison per field (60v142ju, 2026-10-12). Runs the SHIPPED
 * workflows/index.ts `_buildWhere`.
 *
 * (Stubs shared with notification-reaches-the-person-it-names.test.mts.)
 *
 * Tool Share's step authors wrote `recipient: "{{tool.ownerId}}"` and
 * `"{{fetch_tool_owner.ownerId}}"` over a db_query step. The handler read only
 * `to`/`userId`, and a query's output is `{rows, count}`, so both stored the
 * notification for nobody — "Maya is notified" was never true.
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
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'x'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = () => ({}); export const and = (...p) => ({ op: 'and', parts: p }); export const sql = (...a) => ({ __sql: a }); export const ne = (c, v) => ({ op: 'ne', col: c && c.__col, v }); export const gt = (c, v) => ({ op: 'gt', col: c && c.__col, v }); export const gte = (c, v) => ({ op: 'gte', col: c && c.__col, v }); export const lt = (c, v) => ({ op: 'lt', col: c && c.__col, v }); export const lte = (c, v) => ({ op: 'lte', col: c && c.__col, v }); export const inArray = (c, v) => ({ op: 'inArray', col: c && c.__col, v }); export const notInArray = (c, v) => ({ op: 'notInArray', col: c && c.__col, v });",
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
const col = (n: string) => ({ __col: n, dataType: n === "submittedAt" ? "date" : "string", columnType: n === "submittedAt" ? "PgTimestamp" : "PgText" });
const table: any = { submittedAt: col("submittedAt"), status: col("status") };
const ctx = (v: Record<string, unknown>) => ({ input: {}, variables: v, log: [] });

const range = mod._buildWhere(table, { submittedAt: { gte: "{{dateFrom}}", lte: "{{dateTo}}" } }, ctx({ dateFrom: "2026-01-01", dateTo: "2026-02-01" }));
ok(range && range.op === "and" && range.parts.length === 2, "two comparisons on one field are ANDed");
eqJson(range.parts.map((p: any) => p.op), ["gte", "lte"], "a range is from and to");

const open = mod._buildWhere(table, { submittedAt: { gte: "{{dateFrom}}", lte: "{{dateTo}}" } }, ctx({ dateFrom: "2026-01-01", dateTo: "" }));
eqJson(open && open.op, "gte", "a bound left blank is no bound, not a fault");

const one = mod._buildWhere(table, { status: { ne: "Archived" } }, ctx({}));
eqJson(one && one.op, "ne", "a single comparison is unchanged");
eqJson(mod._comparisons({ gte: 1, lte: 2 })?.map((c: any) => c.name), ["gte", "lte"], "every comparison is read");
eqJson(mod._comparisons({ gte: 1, bogus: 2 }), null, "an unknown key is not a comparison");
done();
