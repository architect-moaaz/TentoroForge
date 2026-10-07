/**
 * A query's WHERE makes a comparison, not only an equality.
 *
 * ToroCommerce's Edit Profile asked "is this email someone ELSE's?" with
 * `where: {email: "{{email}}", id: {ne: "{{customer.id}}"}}`; the object
 * reached Postgres as the text "[object Object]" and every save failed
 * (forge-v3, 2026-10-07).
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
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'x'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = (c, v) => ({ eq: [c.name, v] }); export const and = (...c) => ({ and: c }); export const sql = (s, ...v) => ({ sql: s.join('?'), args: v.map((x) => (x && x.name) || x) });",
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
const table = { id: { name: "id" }, email: { name: "email" }, stock: { name: "stock" } };
const ctx: any = { input: { email: "maria@example.com" }, variables: { email: "maria@example.com", customer: { id: "c-1" } }, log: [] };

const w = mod._buildWhere(table, { email: "{{email}}", id: { ne: "{{customer.id}}" } }, ctx);
const parts = w.and ?? [w];
eqJson(parts[0], { eq: ["email", "maria@example.com"] }, "equality stays the plain form");
eqJson(parts[1], { sql: "? <> ?", args: ["id", "c-1"] }, "`ne` is a not-equal on the resolved value");

const g = mod._buildWhere(table, { stock: { gte: 2 } }, ctx);
eqJson(g, { sql: "? >= ?", args: ["stock", 2] }, "`gte` compares");

let refused = "";
try { mod._buildWhere(table, { id: { near: "x" } }, ctx); } catch (e: any) { refused = String(e.message); }
ok(refused.includes("one comparison of"), "an unknown comparison is refused by name, not sent as text");

let empty = "";
try { mod._buildWhere(table, { id: { ne: "{{nobody.id}}" } }, { input: {}, variables: {}, log: [] }); } catch (e: any) { empty = String(e.message); }
ok(empty.length > 0, "a comparison with nothing to compare to is refused like an empty lookup");
done("WHERE comparison");
