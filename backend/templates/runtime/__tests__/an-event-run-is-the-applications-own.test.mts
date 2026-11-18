/**
 * A run started by an EVENT is the application's own; a run started by a person is scoped to what that person may reach.
 * Runs the SHIPPED workflows/index.ts `_scoped`, with the data engine's scope stubbed to a marker.
 *
 * The bus marks an event's run `__byEvent`. Such a run reads and writes what the application does, whoever caused the event
 * (the customer who placed an order triggers "notify the restaurant", which must see the restaurant's rows). Anything else
 * with an acting person is held to that person's rows; with no person it is the application's own as before.
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
    "../data-engine": "globalThis.__scopeCalls = []; export const scopeForTable = async (t, u, op, via) => { globalThis.__scopeCalls.push({ op, via }); return { op: 'scope' }; };",
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
const calls = () => (globalThis as any).__scopeCalls as { op: string; via: string }[];
const where = { op: "eq" };
const run = (user: unknown, variables: Record<string, unknown>) => ({ user, input: {}, variables, log: [] });

const person = await mod._scoped({}, where, run({ id: "u1", role: "Customer" }, {}), "read");
eqJson(person.op, "and", "a run a person started is narrowed to what that person may reach");
eqJson(calls().length, 1, "the data engine's scope was asked for exactly once");
eqJson(calls()[0].via, "workflow", "and it knows the read comes from a workflow");

const byEvent = await mod._scoped({}, where, run({ id: "u1", role: "Customer" }, { __byEvent: "order.placed" }), "read");
ok(byEvent === where, "a run an event started is the application's own: its filter is left as it is");
eqJson(calls().length, 1, "and no scope was asked for");

const nobody = await mod._scoped({}, where, run(undefined, {}), "write");
ok(nobody === where, "a run with no acting person is the application's own, as before");
eqJson(calls().length, 1, "and no scope was asked for either");

done();
