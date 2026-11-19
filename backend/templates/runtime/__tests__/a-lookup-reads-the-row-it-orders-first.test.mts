/**
 * A lookup that says which row it means reads that row.
 *
 * `db_query` returned rows in whatever order Postgres kept them, and a step
 * reads the first. DITANS's "latest credit balance" (`credit_ledger_entries`
 * for the organisation) read a September row on every run, so every
 * invitation and contact request wrote the same balance (2026-11-19).
 * Writers already wrote `orderBy` and `limit` on their lookups; the engine
 * dropped both. Now `orderBy` reads as SQL does — a field, ascending unless
 * it says desc — and `limit` caps the rows. A field that is not a column is
 * refused rather than ignored.
 *
 * Runs the SHIPPED workflows/index.ts db_query over an in-memory table.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
(globalThis as any).__LEDGER = [
  { id: "l1", organisationId: "org-1", balanceAfter: 24, createdAt: "2026-09-06T10:00:00Z" },
  { id: "l2", organisationId: "org-1", balanceAfter: 23, createdAt: "2026-11-19T07:12:42Z" },
  { id: "l3", organisationId: "org-2", balanceAfter: 90, createdAt: "2026-11-20T09:00:00Z" },
  { id: "l4", organisationId: "org-1", balanceAfter: 22, createdAt: "2026-10-01T08:00:00Z" },
];
installHarness({
  stubs: {
    "@/db": `
      const pass = (r, p) => !p ? true : p.op === "and" ? p.parts.every((q) => pass(r, q)) : p.op === "eq" ? String(r[p.col]) === String(p.v) : true;
      const query = (rows) => {
        const q = Promise.resolve(rows);
        q.where = (p) => query(rows.filter((r) => pass(r, p)));
        // A bare column sorts ascending; sql\`\${col} desc\` (drizzle's desc) newest first.
        q.orderBy = (o) => { const col = o.__col ?? o.values?.[0]?.__col; const dir = o.__col ? "asc" : /desc/.test(o.strings.join("")) ? "desc" : "asc";
          globalThis.__ORDERED = { col, dir }; return query([...rows].sort((a, b) =>
          (a[col] < b[col] ? -1 : a[col] > b[col] ? 1 : 0) * (dir === "desc" ? -1 : 1))); };
        q.limit = (k) => { globalThis.__LIMIT = k; return query(rows.slice(0, k)); };
        return q;
      };
      export const db = { select: () => ({ from: () => query(globalThis.__LEDGER.map((r) => ({ ...r }))) }) };`,
    "@/db/schema": `
      const t = { __name: "credit_ledger_entries" };
      for (const c of ["id", "organisationId", "balanceAfter", "createdAt"]) t[c] = { __col: c, columnType: "PgText", dataType: "string" };
      export const creditLedgerEntries = t;`,
    "drizzle-orm": `
      export const getTableName = (t) => t.__name; export const is = (v) => !!(v && v.__name); export class Table {};
      const op = (o) => (c, v) => ({ op: o, col: c && c.__col, v });
      export const eq = op("eq"), ne = op("ne"), gt = op("gt"), gte = op("gte"), lt = op("lt"), lte = op("lte"), inArray = op("in"), notInArray = op("nin");
      export const and = (...parts) => ({ op: "and", parts: parts.filter(Boolean) });
      export const sql = (strings, ...values) => ({ strings: [...strings], values });`,
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "../ownership-rules": "export const ownershipRulesFor = () => [];",
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
mod.registerDefaultActions?.();
const query = (globalThis as any).__handlers["db_query"];
ok(typeof query === "function", "db_query is registered");
const g = globalThis as any;
const ctx: any = { user: undefined, variables: { org: "org-1" } };
const base = { actionType: "db_query", table: "credit_ledger_entries", where: { organisationId: "{{org}}" } };

const latest = await query({ ...base, orderBy: "createdAt desc", limit: 1 }, ctx);
eqJson([latest.balanceAfter, latest.count, g.__LIMIT], [23, 1, 1], "the latest balance is the newest row, and only it");

const oldest = await query({ ...base, orderBy: "createdAt" }, ctx);
eqJson(oldest.rows.map((r: any) => r.id), ["l1", "l4", "l2"], "a field alone orders ascending, as SQL does");
eqJson(oldest.balanceAfter, 24, "and the step reads the first of that order");

const upper = await query({ ...base, orderBy: "createdAt DESC" }, ctx);
eqJson(upper.rows[0].id, "l2", "desc in any case");

g.__ORDERED = undefined; g.__LIMIT = undefined;
const plain = await query(base, ctx);
eqJson([plain.count, g.__ORDERED, g.__LIMIT], [3, undefined, undefined], "a lookup that says nothing about order is left as it was");

const wrong = await query({ ...base, orderBy: "score desc" }, ctx);
ok(/orderBy "score desc" is not a column of credit_ledger_entries, optionally/.test(String(wrong.error)) && wrong.count === 0,
   "a field that is not a column is refused, not ignored");
const badLimit = await query({ ...base, limit: "a few" }, ctx);
ok(/limit "a few" is not a whole number/.test(String(badLimit.error)), "a limit that is not a number of rows is refused");
const strLimit = await query({ ...base, orderBy: "createdAt desc", limit: "2" }, ctx);
eqJson(strLimit.rows.map((r: any) => r.id), ["l2", "l4"], "a limit written as text is still that many rows");

done("ordered lookup");
