/**
 * The `send_notification` step reaches the person it names.
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
    "@/db/schema": "export const forgeNotifications = { __name: 'forge_notifications' };",
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'x'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = () => ({}); export const and = () => ({}); export const sql = (...a) => ({ __sql: a });",
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
mod.registerDefaultActions();
const notify = (globalThis as any).__handlers.send_notification;
ok(typeof notify === "function", "the shipped module registers send_notification");

const persisted = () => (globalThis as any).__persisted as any[];

(globalThis as any).__persisted = [];
await notify({ title: "Borrow request", message: "A neighbour asked", recipient: "{{tool.ownerId}}" },
             { input: {}, variables: { tool: { ownerId: "user-maya" } }, log: [] });
eqJson(persisted()[0]?.userId, "user-maya", "`recipient` names the person notified");

(globalThis as any).__persisted = [];
await notify({ title: "Dispute", message: "Opened", recipient: "{{fetch_tool_owner.ownerId}}" },
             { input: {}, variables: { fetch_tool_owner: { rows: [{ ownerId: "user-maya" }], count: 1 } }, log: [] });
eqJson(persisted()[0]?.userId, "user-maya", "a lookup step's field is read from its first row");

(globalThis as any).__persisted = [];
await notify({ title: "Queue", message: "New KYC", recipientRole: "Admin" }, { input: {}, variables: {}, log: [] });
eqJson([persisted()[0]?.userId, persisted()[0]?.role], [null, "Admin"], "a team is named by its role");

(globalThis as any).__persisted = [];
await notify({ title: "Legacy", to: "{{userId}}" }, { input: {}, variables: { userId: "u-1" }, log: [] });
eqJson(persisted()[0]?.userId, "u-1", "`to` still works");

done("send_notification recipient");
