/**
 * Row-level scoping in the data engine — the predicate that keeps one signed-in
 * user out of another's rows, on every path that reads them.
 *
 * These run the SHIPPED data-engine.ts, not a transcription of it. The module
 * imports `@/db`, `drizzle-orm` and the per-app manifests, none of which exist
 * in this repo, so a module resolve hook supplies them: a fake `db` that really
 * evaluates the WHERE tree it is handed against in-memory rows, and a drizzle
 * stub that builds that tree. `./ownership-rules` resolves to the file the real
 * projection just rendered from ownership-fixture.blueprint.json (argv[2]), so
 * the manifest, its lookup and the engine's use of it are all under test at once.
 *
 * The fake `.where()` REPLACES a previous call, exactly as Drizzle's does. That
 * is what makes the search+filter case below a real regression test rather than
 * a description of one.
 *
 * Run via __tests__/run-ownership-tests.sh. Exits non-zero on any failure.
 */

import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve as resolvePath } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const MANIFEST = process.argv[2];
if (!MANIFEST) {
  console.error("usage: ownership-scope.test.mts <path to generated ownership-rules.ts>");
  process.exit(1);
}
const FIXTURE = JSON.parse(
  readFileSync(join(HERE, "ownership-fixture.blueprint.json"), "utf8"),
);

// ── Condition tree ─────────────────────────────────────────────────────────
// The drizzle stubs build this; the fake db evaluates it. Keeping it a plain
// data structure is what lets one assertion cover "the predicate was applied"
// and "it was applied correctly" at the same time.

type Cond =
  | { op: "eq"; col: string; val: unknown }
  | { op: "ilike"; col: string; pat: string }
  | { op: "and"; conds: Cond[] }
  | { op: "or"; conds: Cond[] }
  | { op: "gte"; col: string; val: unknown }
  | { op: "lt"; col: string; val: unknown }
  | { op: "raw"; text: string };

function matches(row: any, c: Cond | undefined): boolean {
  if (!c) return true;
  switch (c.op) {
    case "eq": return row[c.col] === c.val;
    case "gte": return row[c.col] >= (c.val as any);
    case "lt": return row[c.col] < (c.val as any);
    case "ilike": {
      const needle = c.pat.replace(/%/g, "").toLowerCase();
      return String(row[c.col] ?? "").toLowerCase().includes(needle);
    }
    case "and": return c.conds.every((x) => matches(row, x));
    case "or": return c.conds.some((x) => matches(row, x));
    // `sql\`false\`` is how scopeConditions fails closed; everything else a
    // template emits (date_trunc, tsquery) is not exercised here.
    case "raw": return c.text.trim() !== "false";
  }
}

// ── Fixture tables + rows ──────────────────────────────────────────────────

const ALICE = "user-alice";
const BOB = "user-bob";

function makeTable(name: string, cols: string[]) {
  const t: any = {};
  for (const c of cols) t[c] = { __col: c, __table: name };
  // Non-enumerable so Object.keys(table) sees columns only, as drizzle does.
  Object.defineProperty(t, "__name", { value: name, enumerable: false });
  return t;
}

const entities = FIXTURE.data.entities as Array<{ name: string; table: string; fields: Array<{ name: string }> }>;
const fieldsOf = (n: string) =>
  entities.find((e) => e.name === n)!.fields.map((f) => f.name);
const tableOf = (n: string) => entities.find((e) => e.name === n)!.table;

const invoices = makeTable(tableOf("Invoice"), fieldsOf("Invoice"));
const announcements = makeTable(tableOf("Announcement"), fieldsOf("Announcement"));
// Ticket's rule names ownerId; the table deliberately does not carry it.
const tickets = makeTable(tableOf("Ticket"), fieldsOf("Ticket"));

const d = (n: number) => new Date(2026, 0, n);
const ROWS: Record<string, any[]> = {
  [invoices.__name]: [
    { id: "i1", ownerId: ALICE, title: "Alice roofing", status: "paid", createdAt: d(1) },
    { id: "i2", ownerId: ALICE, title: "Alice plumbing", status: "open", createdAt: d(2) },
    { id: "i3", ownerId: BOB, title: "Bob roofing", status: "open", createdAt: d(3) },
  ],
  [announcements.__name]: [
    { id: "a1", postedByUserId: ALICE, title: "Office closed Monday", createdAt: d(1) },
    { id: "a2", postedByUserId: BOB, title: "New expenses policy", createdAt: d(2) },
  ],
  [tickets.__name]: [
    { id: "t1", title: "Printer jammed", createdAt: d(1) },
  ],
};

// ── Fake db ────────────────────────────────────────────────────────────────

type Shape = Record<string, any> | undefined;

function runQuery(state: any): any[] {
  const rows = (ROWS[state.table.__name] ?? []).filter((r) => matches(r, state.where));
  const shape: Shape = state.shape;

  // select({ total: count() }) — the count query.
  if (shape && Object.values(shape).some((v: any) => v?.__agg === "count") && !shape.label) {
    const key = Object.keys(shape).find((k) => (shape as any)[k]?.__agg === "count")!;
    return [{ [key]: rows.length }];
  }
  // select({ label, value }) — a grouped series.
  if (shape && shape.label && shape.value) {
    const groups = new Map<string, number>();
    for (const r of rows) {
      const k = String(r[shape.label.__col]);
      groups.set(k, (groups.get(k) ?? 0) + 1);
    }
    return [...groups].map(([label, value]) => ({ label, value }));
  }
  // Plain row select.
  let out = rows.map((r) => ({ ...r }));
  if (state.offset) out = out.slice(state.offset);
  if (state.limit != null) out = out.slice(0, state.limit);
  return out;
}

function insertBuilder() {
  const state: any = { table: null, values: null };
  const b: any = {
    values(v: any) { state.values = v; return b; },
    returning() { return b; },
    then(res: any, rej: any) {
      const row = { id: `new-${(ROWS[state.table.__name] ?? []).length + 1}`, ...state.values };
      (ROWS[state.table.__name] ??= []).push(row);
      return Promise.resolve([{ ...row }]).then(res, rej);
    },
  };
  return { into: (t: any) => { state.table = t; return b; }, _b: b, _state: state };
}

function builder(shape: Shape) {
  const state: any = { shape, table: null, where: undefined, limit: null, offset: 0 };
  const b: any = {
    from(t: any) { state.table = t; return b; },
    // REPLACES, exactly like drizzle. A second .where() drops the first.
    where(c: Cond) { state.where = c; return b; },
    orderBy() { return b; },
    groupBy() { return b; },
    limit(n: number) { state.limit = n; return b; },
    offset(n: number) { state.offset = n; return b; },
    returning() { return b; },
    then(res: any, rej: any) { return Promise.resolve(runQuery(state)).then(res, rej); },
  };
  return b;
}

function writeBuilder(kind: "update" | "delete", table: any) {
  const state: any = { table, patch: null, where: undefined };
  const apply = () => {
    const rows = ROWS[state.table.__name] ?? [];
    const hit = rows.filter((r) => matches(r, state.where));
    if (kind === "delete") {
      ROWS[state.table.__name] = rows.filter((r) => !hit.includes(r));
    } else {
      for (const r of hit) Object.assign(r, state.patch);
    }
    return hit.map((r) => ({ ...r }));
  };
  const b: any = {
    set(p: any) { state.patch = p; return b; },
    where(c: Cond) { state.where = c; return b; },
    returning() { return b; },
    then(res: any, rej: any) { return Promise.resolve(apply()).then(res, rej); },
  };
  return b;
}

const fakeDb = {
  select: (shape?: Shape) => builder(shape),
  insert: (t: any) => { const i = insertBuilder(); i._state.table = t; return i._b; },
  update: (t: any) => writeBuilder("update", t),
  delete: (t: any) => writeBuilder("delete", t),
};

// ── Stub modules the engine imports ────────────────────────────────────────

const DRIZZLE = `
export const eq = (col, val) => ({ op: "eq", col: col.__col, val });
export const gte = (col, val) => ({ op: "gte", col: col.__col, val });
export const lt = (col, val) => ({ op: "lt", col: col.__col, val });
export const ilike = (col, pat) => ({ op: "ilike", col: col.__col, pat });
export const and = (...conds) => ({ op: "and", conds: conds.filter(Boolean) });
export const or = (...conds) => ({ op: "or", conds: conds.filter(Boolean) });
export const desc = (c) => c;
export const asc = (c) => c;
export const count = () => ({ __agg: "count" });
export const sum = (c) => ({ __agg: "sum", c });
export const avg = (c) => ({ __agg: "avg", c });
export const min = (c) => ({ __agg: "min", c });
export const max = (c) => ({ __agg: "max", c });
export const inArray = (col, vals) => ({ op: "in", col: col.__col, vals });
export const getTableName = (t) => t.__name;
export function sql(strings, ...values) {
  return { op: "raw", text: strings.raw.join("?"), values };
}
sql.join = (parts) => ({ op: "raw", text: "join", parts });
`;

const STUBS: Record<string, string> = {
  "@/db": "export const db = globalThis.__FAKE_DB__;",
  "drizzle-orm": DRIZZLE,
  "./fk-roles":
    "export const FK_ROLES = {};\n" +
    "export const fkRole = () => undefined;\n" +
    "export const isDomainFk = () => false;\n",
  "./sensitive-columns": "export const sensitiveColumnsFor = () => ({});\n",
  "./searchable-columns": "export const searchableColumnsFor = () => [];\n",
  "./sensitive-crypto":
    "export const encryptSensitive = async (v) => v;\n" +
    "export const decryptSensitive = async (v) => v;\n" +
    "export const mask = (v) => v;\n" +
    "export const looksMasked = () => false;\n",
  // Field-level ACLs and business rules are separate controls; pass everything
  // through untouched so a row that comes back proves the ROW filter let it
  // through, and a write that lands proves nothing else rejected it.
  "@/lib/rules":
    "export const filterFields = async (_e, r) => r;\n" +
    "export const validateEntity = async () => ({ valid: true, errors: [] });\n" +
    "export const evaluateRuleSet = async () => ({ errors: [], patches: {}, sideEffects: [] });\n",
  "./events/bus": "export const emitEventAndProcess = async () => {};\n",
};

(globalThis as any).__FAKE_DB__ = fakeDb;

registerHooks({
  resolve(spec: string, ctx: any, next: any) {
    if (spec in STUBS) return { url: "stub:" + spec, shortCircuit: true };
    // The generated manifest, rendered by the real projection.
    if (spec === "./ownership-rules") {
      return { url: pathToFileURL(resolvePath(MANIFEST)).href, shortCircuit: true };
    }
    // Extensionless relative imports the engine makes into files that do exist.
    if (spec === "./data-engine/aggregate-window") {
      return { url: pathToFileURL(join(HERE, "..", "data-engine", "aggregate-window.ts")).href, shortCircuit: true };
    }
    return next(spec, ctx);
  },
  load(url: string, ctx: any, next: any) {
    if (url.startsWith("stub:")) {
      return { format: "module", source: STUBS[url.slice(5)], shortCircuit: true };
    }
    return next(url, ctx);
  },
});

const engine = await import("../data-engine.ts");

engine.registerEntity(invoices.__name, invoices, { slug: invoices.__name });
engine.registerEntity(announcements.__name, announcements, { slug: announcements.__name });
engine.registerEntity(tickets.__name, tickets, { slug: tickets.__name });

// ── Assertions ─────────────────────────────────────────────────────────────

let failed = 0;
function ok(cond: unknown, name: string): void {
  if (cond) { console.log(`  ✓ ${name}`); return; }
  console.error(`  ✗ ${name}`); failed++;
}
function eqJson(actual: unknown, expected: unknown, name: string): void {
  const same = JSON.stringify(actual) === JSON.stringify(expected);
  if (same) { console.log(`  ✓ ${name}`); return; }
  console.error(`  ✗ ${name}\n      expected: ${JSON.stringify(expected)}\n      actual:   ${JSON.stringify(actual)}`);
  failed++;
}
async function throwsNotFound(fn: () => Promise<unknown>, name: string): Promise<void> {
  try { await fn(); console.error(`  ✗ ${name} (expected NotFoundError)`); failed++; }
  catch (e: any) {
    if (e?.name === "NotFoundError") console.log(`  ✓ ${name}`);
    else { console.error(`  ✗ ${name} — got ${e?.name}: ${e?.message}`); failed++; }
  }
}

const asAlice = { user: { id: ALICE, role: "member" } };
const asBob = { user: { id: BOB, role: "member" } };
const asAdmin = { user: { id: "user-admin", role: "admin" } };

const ids = (rows: any[]) => rows.map((r) => r.id).sort();

console.log("query(): a second user cannot list the first user's rows");
{
  const alice = await engine.query(invoices.__name, {}, asAlice);
  const bob = await engine.query(invoices.__name, {}, asBob);
  eqJson(ids(alice.data), ["i1", "i2"], "Alice sees only her invoices");
  eqJson(ids(bob.data), ["i3"], "Bob sees only his invoice");
  eqJson(alice.total, 2, "total counts the scoped rows, not the table");
  eqJson(bob.total, 1, "Bob's total is his own row count");
}

console.log("query(): the entity name spelling does not change the scope");
{
  // The SSR path names entities as the Blueprint spells them; the API route
  // uses the schema export. Both must land on the same rule.
  const alice = await engine.query("Invoice", {}, asAlice);
  eqJson(ids(alice.data), ["i1", "i2"], "singular Pascal name resolves the same rule");
}

console.log("query(): an attribution column never narrows a read");
{
  // a1 is Alice's, a2 is Bob's. Both must see both — this is the exact
  // guarantee the live ATS blueprint states and has a test for, and the reason
  // `kind` exists instead of scoping every actor-shaped column.
  const alice = await engine.query(announcements.__name, {}, asAlice);
  const bob = await engine.query(announcements.__name, {}, asBob);
  eqJson(ids(alice.data), ["a1", "a2"], "Alice reads Bob's announcement too");
  eqJson(ids(bob.data), ["a1", "a2"], "Bob reads Alice's announcement too");
  eqJson(alice.total, 2, "and the total is not narrowed either");
  eqJson(await engine.stats(announcements.__name, asBob), { total: 2 },
    "nor is the count");
  const series = await engine.resolveSeries(
    { name: "byPoster", entity: announcements.__name, op: "series", groupBy: "postedByUserId" },
    asAlice,
  );
  eqJson(series.length, 2, "an attribution column can still be grouped ON, across all rows");
}

console.log("query(): a role the rule exempts reads every row");
{
  const admin = await engine.query(invoices.__name, {}, asAdmin);
  eqJson(ids(admin.data), ["i1", "i2", "i3"], "admin is unscoped, as declared");
}

console.log("query(): a scoped entity with no actor returns nothing");
{
  const anon = await engine.query(invoices.__name, {}, {});
  eqJson(ids(anon.data), [], "no actor on the context → no rows");
  eqJson(anon.total, 0, "and a total that agrees");
}

console.log("query(): a rule naming a column the table lacks fails closed");
{
  const alice = await engine.query(tickets.__name, {}, asAlice);
  eqJson(ids(alice.data), [], "Blueprint/schema drift returns no rows, not every row");
}

console.log("findById(): another user's row is Not Found, not Forbidden");
{
  const own = await engine.findById(invoices.__name, "i1", asAlice);
  ok(own?.id === "i1", "Alice reads her own invoice by id");
  await throwsNotFound(
    () => engine.findById(invoices.__name, "i3", asAlice),
    "Alice cannot read Bob's invoice by id",
  );
}

console.log("update()/remove(): another user's row cannot be written either");
{
  await throwsNotFound(
    () => engine.update(invoices.__name, "i3", { title: "hijacked" }, asAlice),
    "Alice cannot update Bob's invoice",
  );
  await throwsNotFound(
    () => engine.remove(invoices.__name, "i3", asAlice),
    "Alice cannot delete Bob's invoice",
  );
  ok(ROWS[invoices.__name].some((r) => r.id === "i3" && r.title === "Bob roofing"),
    "Bob's row is untouched");
  const own = await engine.update(invoices.__name, "i1", { title: "Alice roofing v2" }, asAlice);
  eqJson(own.data.title, "Alice roofing v2", "Alice can still update her own row");
  ROWS[invoices.__name].find((r) => r.id === "i1")!.title = "Alice roofing";
}

console.log("stats(): the count is scoped like the list it summarises");
{
  eqJson(await engine.stats(invoices.__name, asAlice), { total: 2 }, "Alice's stats count her rows");
  eqJson(await engine.stats(invoices.__name, asBob), { total: 1 }, "Bob's stats count his row");
  eqJson(await engine.stats(invoices.__name, asAdmin), { total: 3 }, "admin's stats count everything");
}

console.log("resolveSeries(): a chart aggregates only the actor's rows");
{
  const alice = await engine.resolveSeries(
    { name: "byStatus", entity: invoices.__name, op: "series", groupBy: "status" },
    asAlice,
  );
  eqJson(alice, [{ label: "open", value: 1 }, { label: "paid", value: 1 }],
    "Alice's status breakdown covers her two invoices");
  const bob = await engine.resolveSeries(
    { name: "byStatus", entity: invoices.__name, op: "series", groupBy: "status" },
    asBob,
  );
  eqJson(bob, [{ label: "open", value: 1 }], "Bob's breakdown covers his one invoice");
  const anon = await engine.resolveSeries(
    { name: "byStatus", entity: invoices.__name, op: "series", groupBy: "status" },
    {},
  );
  eqJson(anon, [], "a chart resolved with no actor shows nothing");
}

console.log("resolveAggregate(): a KPI tile counts only the actor's rows");
{
  const alice = await engine.resolveAggregate(
    { name: "kpis", entity: invoices.__name, op: "aggregate", metrics: { total: { fn: "count" } } },
    asAlice,
  );
  eqJson(alice, { total: 2 }, "Alice's tile shows her own total");
  const bob = await engine.resolveAggregate(
    { name: "kpis", entity: invoices.__name, op: "aggregate", metrics: { total: { fn: "count" } } },
    asBob,
  );
  eqJson(bob, { total: 1 }, "Bob's tile shows his own total");
}

// ── The two defects that shipped alongside the missing scope ───────────────

console.log("create(): the scoping column is set from the session, not the body");
{
  // The read leak in reverse: a caller who can name someone else's id could
  // otherwise file a row into their account.
  const planted = await engine.create(
    invoices.__name,
    { title: "Planted", status: "open", ownerId: ALICE },
    asBob,
  );
  eqJson(planted.data.ownerId, BOB, "ownerId comes from the session, not the payload");
  const alice = await engine.query(invoices.__name, {}, asAlice);
  eqJson(ids(alice.data), ["i1", "i2"], "nothing landed in Alice's list");
  // Cleanup — later assertions count rows.
  ROWS[invoices.__name] = ROWS[invoices.__name].filter((r) => r.title !== "Planted");
}

console.log("create(): an attribution column is filled from the session too");
{
  // Fill without filter: the audit trail means nothing if the client picks the
  // signature, but recording it must not make the row private.
  const posted = await engine.create(
    announcements.__name,
    { title: "Fire drill Friday", postedByUserId: ALICE },
    asBob,
  );
  eqJson(posted.data.postedByUserId, BOB, "the body's postedByUserId is discarded");
  const alice = await engine.query(announcements.__name, {}, asAlice);
  eqJson(ids(alice.data), ["a1", "a2", posted.data.id].sort(),
    "and Alice still reads the row Bob just posted");
  ROWS[announcements.__name] = ROWS[announcements.__name].filter((r) => r.title !== "Fire drill Friday");
}

console.log("create(): an exempt role may still file on another's behalf");
{
  const onBehalf = await engine.create(
    invoices.__name,
    { title: "Raised by admin", status: "open", ownerId: ALICE },
    asAdmin,
  );
  eqJson(onBehalf.data.ownerId, ALICE, "admin's declared exemption is honoured");
  ROWS[invoices.__name] = ROWS[invoices.__name].filter((r) => r.title !== "Raised by admin");
}

console.log("query(): total reflects the WHERE, so pagination is not a lie");
{
  const r = await engine.query(announcements.__name, { filters: { title: "New expenses policy" } }, asAlice);
  eqJson(ids(r.data), ["a2"], "the filter selects one row");
  eqJson(r.total, 1, "and total says one, not the table size");
}

console.log("query(): search and filter apply together");
{
  // status=open alone selects i2 and i3; "roofing" alone selects i1 and i3.
  // Together they select i3 — and only i3, which is what distinguishes an
  // AND from a filter that quietly dropped the search. The two used to be
  // separate .where() calls, and drizzle's second call replaced the first.
  const r = await engine.query(
    invoices.__name,
    { search: "roofing", filters: { status: "open" } },
    asAdmin,
  );
  eqJson(ids(r.data), ["i3"], "search AND filter, not filter alone");
  eqJson(r.total, 1, "total agrees with the combined predicate");

  const scoped = await engine.query(
    invoices.__name,
    { search: "roofing", filters: { status: "open" } },
    asAlice,
  );
  eqJson(ids(scoped.data), [], "and both AND with the ownership predicate");
}

console.log(failed === 0 ? "\nAll ownership-scope tests passed." : `\n${failed} failure(s).`);
process.exit(failed === 0 ? 0 : 1);
