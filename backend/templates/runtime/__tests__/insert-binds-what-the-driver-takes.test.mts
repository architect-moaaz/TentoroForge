/**
 * `_finalizeInsert` shapes a value map to what drizzle's driver mapping will
 * bind: a Date for a `timestamp()` column (dataType "date"), text for a
 * string-mode `date()` column (dataType "string"). Runs the SHIPPED
 * workflows/index.ts with its app-only imports stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
installHarness({
  stubs: {
    "@/db": "export const db = { insert: () => ({ values: (v) => ({ returning: async () => [{ id: 'row-1', ...v }] }) }) };",
    "@/db/schema": "export const cases = { __name: 'cases', id: { columnType: 'PgUUID', dataType: 'string' }, title: { columnType: 'PgText', dataType: 'string' }, caseNumber: { columnType: 'PgText', dataType: 'string' } };",
    "drizzle-orm": "export const getTableName = (t) => t.__name || 'cases'; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = () => ({}); export const and = () => ({}); export const sql = () => ({});",
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

const mod: any = await import("../workflows/index.ts");
const _finalizeInsert = mod._finalizeInsert;
ok(typeof _finalizeInsert === "function", "the helper is exported for the test");

const table = {
  __name: "cases",
  title: { columnType: "PgText", dataType: "string" },
  dueDate: { columnType: "PgDateString", dataType: "string" },
  openedAt: { columnType: "PgDateString", dataType: "string" },
  createdAt: { columnType: "PgTimestamp", dataType: "date" },
};
const ctx: any = { user: undefined, variables: {} };

const out = _finalizeInsert(table, {
  title: "Late checkout fee disputed",
  dueDate: "2026-09-12",
  openedAt: new Date("2026-09-05T10:00:00.000Z"),
  createdAt: "2026-09-05T10:00:00.000Z",
}, ctx);

eqJson(out.dueDate, "2026-09-12", "a form's date string stays text for a string-mode date column");
eqJson(out.openedAt, "2026-09-05", "$now on a string-mode date column becomes the calendar date as text");
ok(out.createdAt instanceof Date, "a timestamp column receives a Date");
eqJson(out.title, "Late checkout fee disputed", "text is untouched");
const resolve = mod._resolveRef;
const a = resolve("$uuid", ctx), b = resolve("$uuid", ctx);
ok(typeof a === "string" && /^[0-9a-f-]{36}$/.test(a), "$uuid is a fresh identifier");
ok(a !== b, "each $uuid is its own");
ok(resolve("$now", ctx) instanceof Date, "$now is still a Date");

// The registered handler, against a stubbed database: the step's output is
// the row, so `{{insert_case.id}}` resolves, and `inserted` still does.
mod.registerDefaultActions();
const handlers: any = (globalThis as any).__handlers;
ok(typeof handlers.db_insert === "function", "db_insert is registered");
const ictx: any = { variables: { title: "Late checkout fee disputed" }, user: { id: "user-1" } };
const result = await handlers.db_insert(
  { table: "cases", values: { title: "{{title}}", caseNumber: "$uuid" }, __nodeId: "insert_case" }, ictx,
);
eqJson(result.id, "row-1", "the step's output carries the row's id at the top");
eqJson(result.inserted.id, "row-1", "`inserted` still carries the row");
eqJson(resolve("{{insert_case.id}}", { variables: { insert_case: result } }), "row-1", "{{insert_case.id}} walks into it");
done("insert-binding");
