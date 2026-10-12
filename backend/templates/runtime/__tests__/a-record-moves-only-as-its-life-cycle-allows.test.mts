/**
 * A status field moves only as the definition's life cycle allows: a new
 * record starts in the initial state, an update that is not an allowed move
 * is refused in words, and a move reserved for a role is refused to others.
 * Runs the SHIPPED workflows/index.ts with its app-only imports stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
installHarness({
  stubs: {
    "@/db": `
      globalThis.__db = { rows: [{ id: 'o-1', status: 'processing' }], writes: [] };
      export const db = {
        select: () => ({ from: () => ({ where: async () => globalThis.__db.rows, }) }),
        update: () => ({ set: (v) => ({ where: (w) => ({ returning: async () => { globalThis.__db.writes.push(v); return globalThis.__db.rows.map((r) => ({ ...r, ...v })); } }) }) }),
        insert: () => ({ values: (v) => ({ returning: async () => [{ id: 'row-1', ...v }] }) }),
      };`,
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": "export const orders = { __name: 'orders', id: { __col: 'id', columnType: 'PgUUID', dataType: 'string' }, status: { __col: 'status', columnType: 'PgText', dataType: 'string' }, total: { columnType: 'PgNumeric', dataType: 'string' } };",
    "../ownership-rules": "export const ownershipRulesFor = () => [];",
    "drizzle-orm": "export const getTableName = (t) => t.__name; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = (c, v) => ({ op: 'eq', col: c && c.__col, v }); export const and = (...a) => ({ op: 'and', a }); export const sql = () => ({}); export const ne = () => ({}); export const gt = () => ({}); export const gte = () => ({}); export const lt = () => ({}); export const lte = () => ({}); export const inArray = () => ({}); export const notInArray = () => ({});",
    "@/lib/error_reporter": "export const reportFromError = () => {};",
    "../fk-roles": "export const FK_ROLES = {}; export const fkRole = () => null; export const isDomainFk = () => false;",
    "@/lib/rules": "export const evaluateRuleSetForTable = async () => ({ errors: [], patches: {} });",
    "./engine": "globalThis.__handlers = {}; export const getActionHandler = (n) => globalThis.__handlers[n]; export const registerActionHandler = (n, h) => { globalThis.__handlers[n] = h; }; export const registerStepHandler = () => {}; export const executeWorkflow = async () => ({}); export const WorkflowEngine = class {}; export const getEngine = () => ({}); export const registerTriggerHandler = () => {}; export const runWorkflow = async () => ({});",
    "./ai": "export const registerAIActions = () => {};",
    "./ocr": "export const registerOcrActions = () => {};",
    "../events/emit-node": "export const makeEmitEventHandler = () => async () => ({});",
    "../feel-lite": "export const evaluateExpression = () => null;",
    "./types": noop,
    "fs": "export const promises = {}; export default { promises };",
    "path": "export default { join: (...a) => a.join('/'), resolve: (...a) => a.join('/') }; export const join = (...a) => a.join('/');",
  },
});

const g: any = globalThis;
g.__forgePolicies = { lifecycles: [{ table: "orders", entity: "Order", field: "status", initial: "pending",
  moves: [{ from: "pending", to: "processing" }, { from: "processing", to: "shipped", by: ["Merchant"] },
          { from: "shipped", to: "delivered" }] }] };

const mod: any = await import("../workflows/index.ts");
mod.registerDefaultActions();
const update = g.__handlers.db_update;
const orders = { __name: "orders", id: { __col: "id" }, status: { __col: "status", columnType: "PgText", dataType: "string" }, total: { columnType: "PgNumeric", dataType: "string" } };

const started = mod._finalizeInsert(orders, { total: "10" }, { variables: {}, log: [] });
eqJson(started.status, "pending", "a new record starts in the life cycle's initial state");
eqJson(mod._finalizeInsert(orders, { total: "10", status: "processing" }, { variables: {}, log: [] }).status, "processing",
       "unless the steps say otherwise");

const asMerchant: any = { user: { id: "u-1", role: "Merchant" }, input: {}, variables: {}, log: [] };
const asCustomer: any = { user: { id: "u-2", role: "Customer" }, input: {}, variables: {}, log: [] };
const step = (status: string) => ({ table: "orders", where: { id: "o-1" }, values: { status } });

let out = await update(step("delivered"), asMerchant);
eqJson([out.refused, out.message], [true, "Order cannot go from processing to delivered."], "a move the decision does not allow is refused in words");
eqJson(g.__db.writes, [], "and nothing is written");

out = await update(step("shipped"), asCustomer);
eqJson([out.refused, out.message], [true, "Only Merchant may move Order from processing to shipped."], "a move reserved for a role is refused to others");

out = await update(step("shipped"), asMerchant);
ok(!out.refused && out.count === 1, "the allowed move, by the right person, goes through");
eqJson(g.__db.writes, [{ status: "shipped" }], "and is written");

eqJson(mod.lifecycleRefusal("orders", "status", "shipped", "shipped", undefined), null, "staying put is no move");
eqJson(mod.lifecycleRefusal("customers", "status", "a", "b", undefined), null, "a record with no life cycle is free");
done();
