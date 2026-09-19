/**
 * resolveQuery — measures by dimensions, the query every chart and KPI reads.
 *
 * Runs the SHIPPED data-engine.ts. `@/db` is a fake that really groups: it
 * evaluates the select shape the engine builds (columns, `date_trunc` buckets,
 * count/sum/avg/min/max/countDistinct) over in-memory rows, under the WHERE tree
 * the drizzle stub builds. So what is asserted is what the engine asked for,
 * computed — not a transcription of it.
 *
 * Run via __tests__/run-query-tests.sh. Exits non-zero on any failure.
 */

import { installHarness, eqJson, ok, done } from "./_harness.mts";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

type Cond =
  | { op: "eq" | "gte" | "lt"; col: string; val: unknown }
  | { op: "in"; col: string; vals: unknown[] }
  | { op: "and"; conds: Cond[] }
  | { op: "raw"; text: string };

function matches(row: any, c: Cond | undefined): boolean {
  if (!c) return true;
  switch (c.op) {
    case "eq": return row[c.col] === c.val;
    case "gte": return row[c.col] >= (c.val as any);
    case "lt": return row[c.col] < (c.val as any);
    case "in": return c.vals.includes(row[c.col]);
    case "and": return c.conds.every((x) => matches(row, x));
    case "raw": return c.text.trim() !== "false";
  }
}

function makeTable(name: string, cols: string[]) {
  const t: any = {};
  for (const c of cols) t[c] = { __col: c };
  Object.defineProperty(t, "__name", { value: name, enumerable: false });
  return t;
}

const orders = makeTable("orders", ["id", "ownerId", "region", "status", "total", "customerId", "placedAt", "createdAt"]);

const d = (m: number, day: number) => new Date(Date.UTC(2026, m - 1, day));
const ROWS: Record<string, any[]> = {
  orders: [
    { id: "o1", ownerId: "alice", region: "EU", status: "PAID", total: 100, customerId: "c1", placedAt: d(1, 5) },
    { id: "o2", ownerId: "alice", region: "EU", status: "OPEN", total: 50, customerId: "c1", placedAt: d(1, 20) },
    { id: "o3", ownerId: "alice", region: "US", status: "PAID", total: 300, customerId: "c2", placedAt: d(2, 3) },
    { id: "o4", ownerId: "bob", region: "US", status: "PAID", total: 999, customerId: "c3", placedAt: d(2, 9) },
    { id: "o5", ownerId: "alice", region: "APAC", status: "PAID", total: 20, customerId: "c2", placedAt: d(3, 1) },
  ],
};

// ── The fake db evaluates the shape the engine selects ─────────────────────

function evalExpr(expr: any, row: any): unknown {
  if (expr?.__col) return row[expr.__col];
  if (expr?.op === "raw" && /date_trunc/.test(expr.text)) {
    const bucket = expr.values[0].__raw as string;
    const v: Date = row[expr.values[1].__col];
    const y = v.getUTCFullYear(), m = v.getUTCMonth();
    if (bucket === "year") return new Date(Date.UTC(y, 0, 1));
    if (bucket === "quarter") return new Date(Date.UTC(y, m - (m % 3), 1));
    if (bucket === "month") return new Date(Date.UTC(y, m, 1));
    return new Date(Date.UTC(y, m, v.getUTCDate()));
  }
  // CASE WHEN <col> >= a AND <col> < b THEN k … END — a banded number.
  if (expr?.op === "raw" && /^CASE /.test(expr.text)) {
    const cond = (c: any) => {
      const v = row[c.values[0].__col], n = Number(c.values[1].__raw);
      return v !== null && v !== undefined && (/>=/.test(c.text) ? v >= n : v < n);
    };
    for (const when of expr.values[0].parts) {
      if (when.values[0].parts.every(cond)) return Number(when.values[1].__raw);
    }
    return null;
  }
  throw new Error(`fake db cannot evaluate ${JSON.stringify(expr)}`);
}

function aggregate(agg: any, rows: any[]): number | string | null {
  const vals = agg.c ? rows.map((r) => r[agg.c.__col]).filter((v) => v !== null && v !== undefined) : rows;
  switch (agg.__agg) {
    case "count": return vals.length;
    case "countDistinct": return new Set(vals).size;
    // The driver returns numeric aggregates as strings; the engine must coerce.
    case "sum": return String(vals.reduce((a: number, v: number) => a + v, 0));
    case "avg": return vals.length ? String(vals.reduce((a: number, v: number) => a + v, 0) / vals.length) : null;
    case "min": return vals.length ? Math.min(...vals) : null;
    case "max": return vals.length ? Math.max(...vals) : null;
  }
  return null;
}

let lastQuery: any = null;

function runQuery(state: any): any[] {
  lastQuery = state;
  const rows = (ROWS[state.table.__name] ?? []).filter((r) => matches(r, state.where));
  const shape = state.shape as Record<string, any>;
  const dimKeys = Object.keys(shape).filter((k) => !shape[k].__agg);
  const aggKeys = Object.keys(shape).filter((k) => shape[k].__agg);
  const groups = new Map<string, { key: Record<string, unknown>; rows: any[] }>();
  for (const r of rows) {
    const key: Record<string, unknown> = {};
    for (const k of dimKeys) key[k] = evalExpr(shape[k], r);
    const id = JSON.stringify(key);
    (groups.get(id) ?? groups.set(id, { key, rows: [] }).get(id)!).rows.push(r);
  }
  if (!dimKeys.length && !groups.size) groups.set("{}", { key: {}, rows: [] });
  const out = [...groups.values()].map((g) => {
    const o: any = { ...g.key };
    for (const k of aggKeys) o[k] = aggregate(shape[k], g.rows);
    return o;
  });
  return state.limit != null ? out.slice(0, state.limit) : out;
}

function builder(shape: any) {
  const state: any = { shape, table: null, where: undefined, limit: null, groupBy: [] };
  const b: any = {
    from(t: any) { state.table = t; return b; },
    where(c: Cond) { state.where = c; return b; },
    groupBy(...e: any[]) { state.groupBy = e; return b; },
    orderBy(...o: any[]) { state.orderBy = o; return b; },
    limit(n: number) { state.limit = n; return b; },
    then(res: any, rej: any) { return Promise.resolve(runQuery(state)).then(res, rej); },
  };
  return b;
}

(globalThis as any).__FAKE_DB__ = { select: (shape?: any) => builder(shape) };

const DRIZZLE = `
export const eq = (col, val) => ({ op: "eq", col: col.__col, val });
export const ne = eq, gt = eq, lte = eq;
export const gte = (col, val) => ({ op: "gte", col: col.__col, val });
export const lt = (col, val) => ({ op: "lt", col: col.__col, val });
export const ilike = (col, pat) => ({ op: "ilike", col: col.__col, pat });
export const isNull = (col) => ({ op: "isNull", col: col.__col });
export const isNotNull = (col) => ({ op: "isNotNull", col: col.__col });
export const not = (cond) => ({ op: "not", cond });
export const and = (...conds) => ({ op: "and", conds: conds.filter(Boolean) });
export const or = (...conds) => ({ op: "or", conds: conds.filter(Boolean) });
export const desc = (c) => ({ __order: "desc", c });
export const asc = (c) => ({ __order: "asc", c });
export const count = (c) => ({ __agg: "count", c });
export const countDistinct = (c) => ({ __agg: "countDistinct", c });
export const sum = (c) => ({ __agg: "sum", c });
export const avg = (c) => ({ __agg: "avg", c });
export const min = (c) => ({ __agg: "min", c });
export const max = (c) => ({ __agg: "max", c });
export const inArray = (col, vals) => ({ op: "in", col: col.__col, vals });
export const getTableName = (t) => t.__name;
export const getTableColumns = (t) => ({ ...t });
export function sql(strings, ...values) {
  return { op: "raw", text: strings.raw.join("?"), values };
}
sql.raw = (s) => ({ __raw: s });
sql.join = (parts) => ({ op: "raw", text: "join", parts });
`;

installHarness({
  stubs: {
    "@/db": "export const db = globalThis.__FAKE_DB__;",
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "drizzle-orm": DRIZZLE,
    "./fk-roles": "export const FK_ROLES = {};\nexport const fkRole = () => undefined;\nexport const isDomainFk = () => false;\n",
    "./sensitive-columns": "export const sensitiveColumnsFor = () => ({});\n",
    "./searchable-columns": "export const searchableColumnsFor = () => [];\n",
    "./sensitive-crypto":
      "export const encryptSensitive = async (v) => v;\nexport const decryptSensitive = async (v) => v;\n" +
      "export const mask = (v) => v;\nexport const looksMasked = () => false;\n",
    "@/lib/rules":
      "export const filterFields = async (_e, r) => r;\n" +
      "export const validateEntity = async () => ({ valid: true, errors: [] });\n" +
      "export const evaluateRuleSet = async () => ({ errors: [], patches: {}, sideEffects: [] });\n" +
      "export const rowAccessRulesFor = async () => [];\n",
    "./events/bus": "export const emitEventAndProcess = async () => {};\n",
    // Orders are scoped to their owner; an admin reads every order.
    "./ownership-rules":
      "export const ownershipRulesFor = (e) => e === 'orders' ? " +
      "[{ column: 'ownerId', kind: 'scope', scope: 'user', unscopedRoles: ['admin'] }] : [];\n",
  },
  redirect: {
    "@/lib/rules/row-access-sql": join(HERE, "..", "rules", "row-access-sql.ts"),
  },
});

const engine = await import("../data-engine.ts");
engine.registerEntity("orders", orders, { slug: "orders" });

const alice = { user: { id: "alice", role: "member" } };
const admin = { user: { id: "root", role: "admin" } };
const count = { key: "orders", aggregation: "count" as const };
const revenue = { key: "revenue", aggregation: "sum" as const, field: "total" };

console.log("a metric: no dimension, one row, one number");
{
  const rows = await engine.resolveQuery({ entity: "orders", op: "query", measures: [count, revenue] }, alice);
  eqJson(rows, [{ orders: 4, revenue: 470 }], "Alice's four orders and their total — never Bob's");
}

console.log("a breakdown: ranked by the first measure, largest first");
{
  const rows = await engine.resolveQuery(
    { entity: "orders", op: "query", measures: [revenue], dimensions: [{ field: "region" }] }, admin);
  eqJson(rows, [
    { region: "US", revenue: 1299 }, { region: "EU", revenue: 150 }, { region: "APAC", revenue: 20 },
  ], "revenue by region, as numbers, in rank order");
  eqJson(lastQuery.groupBy.length, 1, "grouped by the one dimension");
}

console.log("a trend: a bucketed date reads as a sortable period, oldest first");
{
  const rows = await engine.resolveQuery(
    { entity: "orders", op: "query", measures: [count], dimensions: [{ field: "placedAt", bucket: "month" }] }, alice);
  eqJson(rows, [
    { placedAt: "2026-01", orders: 2 }, { placedAt: "2026-02", orders: 1 }, { placedAt: "2026-03", orders: 1 },
  ], "orders per month");
  const q = await engine.resolveQuery(
    { entity: "orders", op: "query", measures: [count], dimensions: [{ field: "placedAt", bucket: "quarter" }] }, alice);
  eqJson(q, [{ placedAt: "2026-Q1", orders: 4 }], "a quarter reads as 2026-Q1");
  ok(/date_trunc\('\?', \?\)/.test(lastQuery.shape.d0.text) || lastQuery.shape.d0.text.includes("date_trunc('"),
     "the bucket is inlined, so SELECT and GROUP BY are one expression");
}

console.log("number bands: a number grouped into ranges, in their own order");
{
  const bands = [{ to: 50, label: "small" }, { from: 50, to: 200 }, { from: 200 }];
  const rows = await engine.resolveQuery(
    { entity: "orders", op: "query", measures: [count], dimensions: [{ field: "total", ranges: bands }] }, alice);
  eqJson(rows, [
    { total: "small", orders: 1 }, { total: "50–200", orders: 2 }, { total: "200+", orders: 1 },
  ], "orders per band, the bands in the order declared, unlabelled ones named by their ends");
  ok(/^CASE /.test(lastQuery.shape.d0.text), "the band is one CASE, the same expression in SELECT and GROUP BY");
  ok(!JSON.stringify(lastQuery.shape.d0).includes("small"), "a label never reaches the SQL");
  const some = await engine.resolveQuery(
    { entity: "orders", op: "query", measures: [count], dimensions: [{ field: "total", ranges: [{ from: 50, to: 200 }] }] }, alice);
  eqJson(some, [{ total: "50–200", orders: 2 }], "a value in no band is left out");
  const grid = await engine.resolveQuery({
    entity: "orders", op: "query", measures: [count],
    dimensions: [{ field: "total", ranges: bands }, { field: "status" }],
  }, alice);
  eqJson(grid.map((r: any) => `${r.total}/${r.status}:${r.orders}`).sort(),
    ["200+/PAID:1", "50–200/OPEN:1", "50–200/PAID:1", "small/PAID:1"], "a heatmap's grid: band × status, one cell per pair");
  const order: Record<string, number> = { small: 0, "50–200": 1, "200+": 2 };
  ok(grid.every((r: any, i: number) => i === 0 || order[grid[i - 1].total as string] <= order[r.total as string]), "the grid reads band by band");
  const bad = await engine.resolveQuery(
    { entity: "orders", op: "query", measures: [count], dimensions: [{ field: "total", ranges: [{ from: 9, to: 1 }] }] }, alice);
  ok(bad.length === 4, "a band that cannot hold anything is ignored, not thrown");
}

console.log("a split: two dimensions give one row per pair");
{
  const rows = await engine.resolveQuery({
    entity: "orders", op: "query", measures: [count],
    dimensions: [{ field: "placedAt", bucket: "month" }, { field: "status" }],
  }, alice);
  eqJson(rows.length, 4, "Jan PAID, Jan OPEN, Feb PAID, Mar PAID");
  ok(rows.every((r: any) => typeof r.placedAt === "string" && typeof r.status === "string"), "both dimensions are on each row");
}

console.log("filters, a date range and top N");
{
  const paid = await engine.resolveQuery({
    entity: "orders", op: "query", measures: [count], filter: { status: ["PAID"], region: "EU" },
  }, admin);
  eqJson(paid, [{ orders: 1 }], "an array filter means any of");
  const feb = await engine.resolveQuery({
    entity: "orders", op: "query", measures: [revenue], timeField: "placedAt",
    range: { from: "2026-02-01", to: "2026-03-01" },
  }, admin);
  eqJson(feb, [{ revenue: 1299 }], "the range narrows the time field, half-open");
  const top = await engine.resolveQuery({
    entity: "orders", op: "query", measures: [revenue], dimensions: [{ field: "region" }], limit: 2,
  }, admin);
  eqJson(top.map((r: any) => r.region), ["US", "EU"], "limit keeps the top two");
  eqJson([lastQuery.orderBy[0].__order, lastQuery.orderBy[0].c.__agg, lastQuery.limit], ["desc", "sum", 2],
         "the database ranks by the measure before it cuts, so top N is the top N");
}

console.log("distinct counts and averages");
{
  const rows = await engine.resolveQuery({
    entity: "orders", op: "query",
    measures: [{ key: "customers", aggregation: "count_distinct", field: "customerId" },
               { key: "avgOrder", aggregation: "avg", field: "total" }],
  }, alice);
  eqJson(rows, [{ customers: 2, avgOrder: 117.5 }], "two customers; the average order");
}

console.log("what cannot be computed is dropped, not thrown");
{
  const none = await engine.resolveQuery({
    entity: "orders", op: "query", measures: [{ key: "x", aggregation: "sum", field: "nope" }],
  }, admin);
  eqJson(none, [], "a query left with no measure resolves to nothing");
  const unknownDim = await engine.resolveQuery({
    entity: "orders", op: "query", measures: [count], dimensions: [{ field: "nope" }],
  }, admin);
  eqJson(unknownDim, [{ orders: 5 }], "an unknown dimension is dropped");
  eqJson(await engine.resolveQuery({ entity: "nothing", op: "query", measures: [count] }, admin), [],
         "an unknown entity resolves to nothing");
  eqJson(await engine.resolveQuery({ entity: "orders", op: "query", measures: [count] }, {}), [{ orders: 0 }],
         "no actor on a scoped entity: nothing counted");
}

done("resolveQuery");
