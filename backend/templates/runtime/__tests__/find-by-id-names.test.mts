/**
 * One record carries the same name labels a list does.
 *
 * A list row has always come back with `<fkProp>Label` beside each foreign-key id
 * (customerId + customerIdLabel "Alice Moreau"); a single record did not, so an
 * assistant that fetched one order could say only "customer 0ebf51c6-…". `findById`
 * now attaches them too, best-effort, and a label that cannot be found never fails
 * the read.
 *
 * Runs the SHIPPED data-engine.ts against a small fake db. Via __tests__/run-query-tests.sh.
 */
import { installHarness, eqJson, ok, done } from "./_harness.mts";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// The engine reads src/lib/fk-labels.json from the working directory.
const cwd = mkdtempSync(join(tmpdir(), "fk-labels-"));
mkdirSync(join(cwd, "src", "lib"), { recursive: true });
writeFileSync(
  join(cwd, "src", "lib", "fk-labels.json"),
  JSON.stringify({
    Ticket: { customerId: { labelField: "name", targetEntity: "Customer" }, assignedToId: { labelField: "name", targetEntity: "Customer" } },
    tickets: { customerId: { labelField: "name", targetEntity: "Customer" }, assignedToId: { labelField: "name", targetEntity: "Customer" } },
  }),
);
process.chdir(cwd);

type Cond = { op: "eq"; col: string; val: unknown } | { op: "in"; col: string; vals: unknown[] } | { op: "and"; conds: Cond[] };
const matches = (row: any, c?: Cond): boolean => {
  if (!c) return true;
  if (c.op === "eq") return row[c.col] === c.val;
  if (c.op === "in") return c.vals.includes(row[c.col]);
  return c.conds.every((x) => matches(row, x));
};

const table = (name: string, cols: string[]) => {
  const t: any = {};
  for (const c of cols) t[c] = { __col: c };
  Object.defineProperty(t, "__name", { value: name, enumerable: false });
  return t;
};
const tickets = table("tickets", ["id", "subject", "customerId", "assignedToId", "createdAt"]);
const customers = table("customers", ["id", "name"]);

let ROWS: Record<string, any[]> = {};
function builder(shape: any) {
  const st: any = { shape, table: null, where: undefined, limit: null };
  const run = () => {
    let rows = (ROWS[st.table.__name] ?? []).filter((r) => matches(r, st.where));
    if (st.shape) rows = rows.map((r) => Object.fromEntries(Object.entries(st.shape).map(([k, c]: any) => [k, r[c.__col]])));
    return st.limit != null ? rows.slice(0, st.limit) : rows;
  };
  const b: any = {
    from(t: any) { st.table = t; return b; },
    where(c: Cond) { st.where = c; return b; },
    orderBy() { return b; },
    limit(n: number) { st.limit = n; return b; },
    then(res: any, rej: any) { return Promise.resolve(run()).then(res, rej); },
  };
  return b;
}
(globalThis as any).__FAKE_DB__ = { select: (shape?: any) => builder(shape) };

const DRIZZLE = `
export const eq = (col, val) => ({ op: "eq", col: col.__col, val });
export const ne = eq, gt = eq, gte = eq, lt = eq, lte = eq;
export const ilike = (col, pat) => ({ op: "ilike", col: col.__col, pat });
export const isNull = (col) => ({ op: "isNull", col: col.__col });
export const isNotNull = (col) => ({ op: "isNotNull", col: col.__col });
export const not = (cond) => ({ op: "not", cond });
export const and = (...conds) => ({ op: "and", conds: conds.filter(Boolean) });
export const or = (...conds) => ({ op: "or", conds: conds.filter(Boolean) });
export const desc = (c) => ({ __order: "desc", c });
export const asc = (c) => ({ __order: "asc", c });
export const count = (c) => ({ __agg: "count", c });
export const countDistinct = count, sum = count, avg = count, min = count, max = count;
export const inArray = (col, vals) => ({ op: "in", col: col.__col, vals });
export const getTableName = (t) => t.__name;
export const getTableColumns = (t) => ({ ...t });
export function sql(strings, ...values) { return { op: "raw", text: strings.raw.join("?"), values }; }
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
    "./ownership-rules": "export const ownershipRulesFor = () => [];\n",
  },
});

const engine = await import("../data-engine.ts");
engine.registerEntity("tickets", tickets, { slug: "tickets" });
engine.registerEntity("Customer", customers, { slug: "customers", aliases: ["customers"] });

const user = { user: { id: "u1", role: "agent" } };

console.log("one record carries the name beside each id");
{
  ROWS = { tickets: [{ id: "t1", subject: "Late", customerId: "c1", assignedToId: "c2" }],
           customers: [{ id: "c1", name: "Alice Moreau" }, { id: "c2", name: "Ben Carter" }] };
  const t = await engine.findById("tickets", "t1", user);
  eqJson(t.customerIdLabel, "Alice Moreau", "the customer's name is beside the customer id");
  eqJson(t.assignedToIdLabel, "Ben Carter", "and so is every other reference");
  eqJson(t.customerId, "c1", "the real id stays, for anything that acts on the row");
}

console.log("what is missing never fails the read");
{
  ROWS = { tickets: [{ id: "t2", subject: "No one", customerId: null, assignedToId: "gone" }], customers: [] };
  const t = await engine.findById("tickets", "t2", user);
  ok(!("customerIdLabel" in t), "an empty reference gets no label");
  eqJson(t.assignedToIdLabel, "", "a reference to a row that is gone gets an empty label, not an error");
  eqJson(t.subject, "No one", "and the record itself is untouched");
}

console.log("a record that is not there is still not there");
{
  ROWS = { tickets: [], customers: [] };
  let err: any = null;
  try { await engine.findById("tickets", "nope", user); } catch (e) { err = e; }
  ok(err && /not.?found|nope/i.test(String(err.message ?? err)), "a missing record is still NotFound");
}

console.log("the opt-out reaches a single record too");
{
  process.env.FORGE_FK_LABELS = "false";
  ROWS = { tickets: [{ id: "t3", subject: "Raw", customerId: "c1" }], customers: [{ id: "c1", name: "Alice Moreau" }] };
  const t = await engine.findById("tickets", "t3", user);
  ok(!("customerIdLabel" in t), "FORGE_FK_LABELS=false leaves raw ids only");
  delete process.env.FORGE_FK_LABELS;
}

done("single-record names");
