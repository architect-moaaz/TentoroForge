/**
 * A sealed number is read by its readers and totalled by the engine.
 *
 * Personal Finance sealed a transaction's amount (encrypted at rest, readable
 * by the Consumer). Every page that showed an amount printed ₹NaN: the value
 * was decrypted only when a request also asked for it with `?unmask=`, and no
 * page ever asks. Every chart and tile over amounts read 0: SUM(amount) ran in
 * the database over the plain column, which a sealed field leaves empty
 * (pcn4owv7, 2026-10-14).
 *
 * Runs the SHIPPED data-engine.ts against a fake db that really groups and
 * folds the select shape the engine builds, as resolve-query.test.mts does.
 *
 * Run via __tests__/run-sealed-tests.sh. Exits non-zero on any failure.
 */

import { installHarness, eqJson, ok, done } from "./_harness.mts";

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

const COLS = ["id", "ownerId", "category", "amount", "amount_encrypted", "amount_mask", "spentOn", "createdAt"];
const transactions: any = {};
for (const c of COLS) transactions[c] = { __col: c };
Object.defineProperty(transactions, "__name", { value: "transactions", enumerable: false });

// Sealed as the engine seals: the plain column empty, the value in the seal.
const seal = (v: number) => `sealed:${v}`;
const d = (m: number, day: number) => new Date(Date.UTC(2026, m - 1, day));
const tx = (id: string, ownerId: string, category: string, amount: number, spentOn: Date) =>
  ({ id, ownerId, category, amount: null, amount_encrypted: seal(amount), amount_mask: "••••••••", spentOn, createdAt: spentOn });
const ROWS: Record<string, any[]> = {
  transactions: [
    tx("t1", "asha", "Food", 1200, d(9, 3)),
    tx("t2", "asha", "Food", 300, d(9, 18)),
    tx("t3", "asha", "Transport", 450.5, d(10, 2)),
    tx("t4", "ravi", "Food", 9999, d(10, 4)),
  ],
};

function evalExpr(expr: any, row: any): unknown {
  if (expr?.__col) return row[expr.__col];
  if (expr?.op === "raw" && /date_trunc/.test(expr.text)) {
    const bucket = expr.values[0].__raw as string;
    const v: Date = row[expr.values[1].__col];
    if (bucket === "month") return new Date(Date.UTC(v.getUTCFullYear(), v.getUTCMonth(), 1));
    return new Date(Date.UTC(v.getUTCFullYear(), v.getUTCMonth(), v.getUTCDate()));
  }
  throw new Error(`fake db cannot evaluate ${JSON.stringify(expr)}`);
}

function aggregate(agg: any, rows: any[]): number | string | null {
  const vals = agg.c ? rows.map((r) => r[agg.c.__col]).filter((v) => v !== null && v !== undefined) : rows;
  switch (agg.__agg) {
    case "count": return vals.length;
    case "countDistinct": return new Set(vals).size;
    case "sum": return vals.length ? String(vals.reduce((a: number, v: number) => a + v, 0)) : null;
    case "avg": return vals.length ? String(vals.reduce((a: number, v: number) => a + v, 0) / vals.length) : null;
    case "min": return vals.length ? Math.min(...vals) : null;
    case "max": return vals.length ? Math.max(...vals) : null;
  }
  return null;
}

function runQuery(state: any): any[] {
  const rows = (ROWS[state.table.__name] ?? []).filter((r) => matches(r, state.where));
  if (!state.shape) {
    const all = rows.map((r) => ({ ...r }));
    return all.slice(state.offset ?? 0, state.limit != null ? (state.offset ?? 0) + state.limit : undefined);
  }
  const shape = state.shape as Record<string, any>;
  const dimKeys = Object.keys(shape).filter((k) => !shape[k].__agg);
  const aggKeys = Object.keys(shape).filter((k) => shape[k].__agg);
  if (!aggKeys.length) {
    // No aggregate in the shape: one row out per row in — what the engine
    // reads when it folds sealed values itself.
    const out = rows.map((r) => Object.fromEntries(dimKeys.map((k) => [k, evalExpr(shape[k], r)])));
    return state.limit != null ? out.slice(0, state.limit) : out;
  }
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
  const state: any = { shape, table: null, where: undefined, limit: null, offset: 0 };
  const b: any = {
    from(t: any) { state.table = t; return b; },
    where(c: Cond) { state.where = c; return b; },
    groupBy() { return b; },
    orderBy() { return b; },
    limit(n: number) { state.limit = n; return b; },
    offset(n: number) { state.offset = n; return b; },
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
    // The amount is sealed; the Consumer reads it, nobody else does.
    "./sensitive-columns":
      "export const sensitiveColumnsFor = (e) => e === 'transactions' ? " +
      "{ amount: { mask: 'full', readers: ['Consumer'] } } : {};\n",
    "./searchable-columns": "export const searchableColumnsFor = () => [];\n",
    "./sensitive-crypto":
      "export const encryptSensitive = async (v) => 'sealed:' + v;\n" +
      "export const decryptSensitive = async (v) => String(v).replace(/^sealed:/, '');\n" +
      "export const mask = () => '••••••••';\nexport const looksMasked = (v) => /^•+$/.test(String(v));\n",
    "@/lib/rules":
      "export const filterFields = async (_e, r) => r;\n" +
      "export const validateEntity = async () => ({ valid: true, errors: [] });\n" +
      "export const evaluateRuleSet = async () => ({ errors: [], patches: {}, sideEffects: [] });\n" +
      "export const rowAccessRulesFor = async () => [];\n",
    "./events/bus": "export const emitEventAndProcess = async () => {};\n",
    // A person's transactions are their own; the Admin reads every one.
    "./ownership-rules":
      "export const ownershipRulesFor = (e) => e === 'transactions' ? " +
      "[{ column: 'ownerId', kind: 'scope', scope: 'user', unscopedRoles: ['Admin'] }] : [];\n",
  },
});

const engine = await import("../data-engine.ts");
engine.registerEntity("transactions", transactions, { slug: "transactions" });

const asha = { user: { id: "asha", role: "Consumer" } };
const admin = { user: { id: "root", role: "Admin" } };

console.log("a reader reads the value without asking for it");
{
  const { data } = await engine.query("transactions", {}, asha);
  eqJson(data.map((r: any) => r.amount).sort(), ["1200", "300", "450.5"],
         "Asha's own amounts, opened — as text, the way an unsealed money column reads");
  ok(data.every((r: any) => !("amount_encrypted" in r)), "the seal never leaves the engine");
  ok(data.every((r: any) => Number.isFinite(Number(r.amount))), "nothing a page formats as money is NaN");
}

console.log("a role the readers leave out reads the mask");
{
  const { data } = await engine.query("transactions", {}, admin);
  eqJson(data.map((r: any) => r.amount), ["••••••••", "••••••••", "••••••••", "••••••••"],
         "the Admin sees every row and none of the amounts");
}

console.log("a widget's total over a sealed amount is computed, for the reader's own rows");
{
  const spent = { key: "spent", aggregation: "sum" as const, field: "amount" };
  const n = { key: "n", aggregation: "count" as const, field: "amount" };
  eqJson(await engine.resolveQuery({ entity: "transactions", op: "query", measures: [spent, n] }, asha),
         [{ spent: 1950.5, n: 3 }], "1200 + 300 + 450.5 — never Ravi's 9999");
  eqJson(await engine.resolveQuery(
    { entity: "transactions", op: "query", measures: [spent], dimensions: [{ field: "category" }] }, asha),
    [{ category: "Food", spent: 1500 }, { category: "Transport", spent: 450.5 }], "by category, largest first");
  eqJson(await engine.resolveQuery(
    { entity: "transactions", op: "query", measures: [spent], dimensions: [{ field: "spentOn", bucket: "month" }] }, asha),
    [{ spentOn: "2026-09", spent: 1500 }, { spentOn: "2026-10", spent: 450.5 }], "by month, oldest first");
  eqJson(await engine.resolveQuery(
    { entity: "transactions", op: "query", measures: [{ key: "avg", aggregation: "avg" as const, field: "amount" }] }, asha),
    [{ avg: 1950.5 / 3 }], "an average too");
}

console.log("a role that may not read the amount gets no total of it, and still its count");
{
  const spent = { key: "spent", aggregation: "sum" as const, field: "amount" };
  const n = { key: "n", aggregation: "count" as const, field: "amount" };
  eqJson(await engine.resolveQuery({ entity: "transactions", op: "query", measures: [spent, n] }, admin),
         [{ spent: 0, n: 4 }], "a sum of values it may not see would say them; a count does not");
}

console.log("a tile and a series over a sealed amount");
{
  const tile = await engine.resolveAggregate(
    { name: "t", entity: "transactions", op: "aggregate", metrics: { spent: { fn: "sum", field: "amount" } } } as any, asha);
  eqJson(tile, { spent: 1950.5 }, "the KPI tile's sum");
  const byCat = await engine.resolveSeries(
    { name: "s", entity: "transactions", op: "series", groupBy: "category", agg: { fn: "sum", field: "amount" } } as any, asha);
  eqJson(byCat, [{ label: "Food", value: 1500 }, { label: "Transport", value: 450.5 }], "the chart's series");
  const running = await engine.resolveSeries(
    { name: "r", entity: "transactions", op: "series", orderByCol: "spentOn", agg: { fn: "running_sum", field: "amount" } } as any, asha);
  eqJson(running.map((r: any) => r.value), [1200, 1500, 1950.5], "a running balance");
}

console.log("a field kept in the clear is still summed by the database");
{
  ROWS.transactions.forEach((r) => { r.plain = 1; });
  const before = (globalThis as any).__FAKE_DB__.select;
  let rowReads = 0;
  (globalThis as any).__FAKE_DB__.select = (shape?: any) => {
    if (shape && !Object.values(shape).some((v: any) => v?.__agg)) rowReads++;
    return before(shape);
  };
  await engine.resolveQuery(
    { entity: "transactions", op: "query", measures: [{ key: "n", aggregation: "count" as const }] }, asha);
  (globalThis as any).__FAKE_DB__.select = before;
  eqJson(rowReads, 0, "no row is read back when nothing sealed is measured");
}

done();
