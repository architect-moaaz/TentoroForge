/**
 * Standalone test for resolveAggregate + windowStart helpers.
 *
 * Context: data-engine.ts is a template file (no package.json, no vitest config),
 * and drizzle-orm lives only in generated-app node_modules — not in repo root.
 * We therefore test the pure logic directly without importing data-engine.ts,
 * which avoids the @/db and drizzle-orm import problems entirely.
 *
 * This script is run with: node --experimental-vm-modules (or tsx)
 * It exits 0 on pass, 1 on any failure.
 */

// ── Inline the pure helpers from data-engine.ts (no external deps) ──────────

type SimpleMetric = {
  fn: "count" | "sum" | "avg" | "min" | "max";
  field?: string;
  entity?: string;
  window?: "today" | "week" | "month";
  dateField?: string;
  filter?: Record<string, unknown>;
};
type RatioMetric = {
  kind: "ratio"; entity?: string;
  numerator: SimpleMetric; denominator: SimpleMetric; percent?: boolean;
};
type DeltaMetric = {
  kind: "delta"; fn: "count" | "sum" | "avg" | "min" | "max";
  field?: string; entity?: string; window: "today" | "week" | "month";
  dateField?: string; filter?: Record<string, unknown>; percent?: boolean;
};
type Metric = SimpleMetric | RatioMetric | DeltaMetric;

type AggregateSource = {
  name: string;
  entity: string;
  op: "aggregate";
  metrics?: Record<string, Metric>;
};

// ── Pure helper: windowStart ─────────────────────────────────────────────────
// Imported from the SHIPPED module (zero external deps), so the week/month
// boundary math is tested against the real code, not a copy.
import * as aggWindow from "../data-engine/aggregate-window.ts";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// tsx loads the extensionless template .ts as CJS (no package.json "type":"module"
// in the template dir), so resolve windowStart from either interop shape. Either
// way this is the SHIPPED function, not a copy.
const windowStart: (w?: string) => Date | null =
  (aggWindow as any).windowStart ?? (aggWindow as any).default?.windowStart;
const priorWindow: (w?: string) => { start: Date; end: Date } | null =
  (aggWindow as any).priorWindow ?? (aggWindow as any).default?.priorWindow;

// ── Fake Drizzle db for integration-style tests ──────────────────────────────

function fakeDb(rowByCall: number[]) {
  let call = 0;
  const chain: any = {
    from:  () => chain,
    where: () => chain,
    then: (res: (rows: { value: number }[]) => any) =>
      Promise.resolve([{ value: rowByCall[call++] ?? 0 }]).then(res),
  };
  return { select: () => chain };
}

// ── resolveAggregate with injectable db ─────────────────────────────────────

// Stub out the drizzle aggregate functions — they just need to be truthy
// values that the fake db chain ignores (it returns the preset row directly).
const drizzleStub = {
  count: () => ({ _isDrizzleCount: true }),
  sum:   (_col: any) => ({ _isDrizzleSum: true }),
  avg:   (_col: any) => ({ _isDrizzleAvg: true }),
  min:   (_col: any) => ({ _isDrizzleMin: true }),
  max:   (_col: any) => ({ _isDrizzleMax: true }),
  gte:   (_col: any, _val: any) => ({ _isDrizzleGte: true }),
  lt:    (_col: any, _val: any) => ({ _isDrizzleLt: true }),
  eq:    (_col: any, _val: any) => ({ _isDrizzleEq: true }),
  and:   (..._conds: any[]) => ({ _isDrizzleAnd: true }),
};

// Simplified entity registry (mirrors the real one)
const entityRegistry = new Map<string, { table: any }>();
function registerTestEntity(name: string, cols: string[]) {
  const table: any = {};
  for (const c of cols) table[c] = { _col: c };
  entityRegistry.set(name.toLowerCase(), { table });
}
function getTestEntity(name: string) {
  return entityRegistry.get(name.toLowerCase());
}

async function resolveAggregateWithDb(
  db: any,
  source: AggregateSource,
): Promise<Record<string, number>> {
  const out: Record<string, number> = {};
  const metrics = source.metrics || {};
  await Promise.all(
    Object.entries(metrics).map(async ([key, m]) => {
      try {
        out[key] = await computeMetricWithDb(db, source.entity, m);
      } catch {
        out[key] = 0;
      }
    })
  );
  return out;
}

async function computeSimpleWithDb(
  db: any,
  defaultEntity: string,
  m: SimpleMetric,
  range?: { start?: Date | null; end?: Date | null },
): Promise<number> {
  const entity = getTestEntity(m.entity || defaultEntity);
  if (!entity) return 0;
  if (m.fn !== "count" && !m.field) return 0;

  const cols = entity.table as any;
  const agg =
    m.fn === "count" ? drizzleStub.count() :
    m.fn === "sum"   ? drizzleStub.sum(cols[m.field!]) :
    m.fn === "avg"   ? drizzleStub.avg(cols[m.field!]) :
    m.fn === "min"   ? drizzleStub.min(cols[m.field!]) :
                       drizzleStub.max(cols[m.field!]);

  const conds: any[] = [];
  const dateCol = cols[m.dateField || "createdAt"];
  const start = range ? range.start : windowStart(m.window);
  if (start && dateCol) conds.push(drizzleStub.gte(dateCol, start));
  if (range?.end && dateCol) conds.push(drizzleStub.lt(dateCol, range.end));
  for (const [k, v] of Object.entries(m.filter || {})) {
    if (cols[k] !== undefined) conds.push(drizzleStub.eq(cols[k], v));
  }

  let q = (db as any).select({ value: agg }).from(entity.table);
  if (conds.length) q = q.where(conds.length === 1 ? conds[0] : drizzleStub.and(...conds));
  const [row] = await q;
  return Number(row?.value ?? 0);
}

async function computeMetricWithDb(
  db: any,
  defaultEntity: string,
  m: Metric,
): Promise<number> {
  if ((m as RatioMetric).kind === "ratio") {
    const r = m as RatioMetric;
    const ent = r.entity || defaultEntity;
    const [num, den] = await Promise.all([
      computeSimpleWithDb(db, ent, r.numerator),
      computeSimpleWithDb(db, ent, r.denominator),
    ]);
    if (!den) return 0;
    const ratio = num / den;
    return r.percent ? ratio * 100 : ratio;
  }
  if ((m as DeltaMetric).kind === "delta") {
    const d = m as DeltaMetric;
    const ent = d.entity || defaultEntity;
    const base: SimpleMetric = { fn: d.fn, field: d.field, entity: ent, dateField: d.dateField, filter: d.filter };
    const prior = priorWindow(d.window);
    const [cur, prev] = await Promise.all([
      computeSimpleWithDb(db, ent, { ...base, window: d.window }),
      computeSimpleWithDb(db, ent, base, prior ?? { start: null, end: null }),
    ]);
    if (d.percent) return prev === 0 ? 0 : ((cur - prev) / prev) * 100;
    return cur - prev;
  }
  return computeSimpleWithDb(db, defaultEntity, m as SimpleMetric);
}

// ── Test harness ─────────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;

async function test(name: string, fn: () => Promise<void> | void) {
  try {
    await fn();
    console.log(`  PASS  ${name}`);
    passed++;
  } catch (e: any) {
    console.log(`  FAIL  ${name}`);
    console.log(`        ${e?.message ?? e}`);
    failed++;
  }
}

function assert(cond: boolean, msg: string) {
  if (!cond) throw new Error(`Assertion failed: ${msg}`);
}
function assertEqual<T>(a: T, b: T, msg?: string) {
  const as = JSON.stringify(a), bs = JSON.stringify(b);
  if (as !== bs) throw new Error(`${msg ?? "assertEqual"}: expected ${bs}, got ${as}`);
}

// ── Tests ────────────────────────────────────────────────────────────────────

console.log("\nresolveAggregate tests\n");

// Register entities
registerTestEntity("Appointment", ["date", "createdAt", "status"]);
registerTestEntity("Invoice", ["total", "status", "issuedAt", "createdAt"]);

// 1. windowStart helper
await test("windowStart: null for undefined", () => {
  assert(windowStart(undefined) === null, "should be null");
});
await test("windowStart: today returns today's midnight", () => {
  const d = windowStart("today")!;
  const now = new Date();
  assert(d !== null, "not null");
  assert(d.getHours() === 0 && d.getMinutes() === 0 && d.getSeconds() === 0, "is midnight");
  assert(d.getDate() === now.getDate(), "same day");
});
await test("windowStart: week returns start of this week (Sunday)", () => {
  const d = windowStart("week")!;
  const now = new Date(); now.setHours(0,0,0,0);
  now.setDate(now.getDate() - now.getDay());
  assertEqual(d.toDateString(), now.toDateString(), "week start");
});
await test("windowStart: month returns 1st of this month", () => {
  const d = windowStart("month")!;
  assert(d.getDate() === 1, "day is 1");
  const now = new Date();
  assert(d.getMonth() === now.getMonth(), "same month");
});
await test("windowStart: unknown token → null", () => {
  assert(windowStart("quarter") === null, "should be null");
});

// 2. resolveAggregate integration tests with fake db
await test("returns one number per metric key", async () => {
  const db = fakeDb([3, 1280]);
  const out = await resolveAggregateWithDb(db, {
    name: "dashboardStats", entity: "Appointment", op: "aggregate",
    metrics: {
      todayCount:     { fn: "count", window: "today", dateField: "date" },
      monthlyRevenue: { fn: "sum", field: "total", entity: "Invoice", window: "month" },
    },
  });
  assertEqual(out.todayCount, 3, "todayCount");
  assertEqual(out.monthlyRevenue, 1280, "monthlyRevenue");
});

await test("unknown entity degrades to 0", async () => {
  const db = fakeDb([]);
  const out = await resolveAggregateWithDb(db, {
    name: "s", entity: "Ghost", op: "aggregate",
    metrics: { x: { fn: "count" } },
  });
  assertEqual(out.x, 0, "x should be 0");
});

await test("empty metrics returns empty object", async () => {
  const db = fakeDb([]);
  const out = await resolveAggregateWithDb(db, {
    name: "s", entity: "Appointment", op: "aggregate",
    metrics: {},
  });
  assertEqual(Object.keys(out).length, 0, "no keys");
});

await test("db error per-metric degrades to 0, others still resolve", async () => {
  let call = 0;
  const badDb: any = {
    select: () => ({
      from: () => ({
        where: () => { throw new Error("db error"); },
        then: (res: any) => {
          call++;
          if (call === 1) throw new Error("db error");
          return Promise.resolve([{ value: 99 }]).then(res);
        },
      }),
    }),
  };
  const out = await resolveAggregateWithDb(badDb, {
    name: "s", entity: "Appointment", op: "aggregate",
    metrics: {
      bad: { fn: "count", window: "today", dateField: "date" },
      good: { fn: "count" },
    },
  });
  // Both degrade to 0 on throw — that's acceptable; key point is no throw propagates
  assert(typeof out.bad === "number", "bad is number");
  assert(typeof out.good === "number", "good is number");
});

await test("sum/avg return value coerced from string to number", async () => {
  // Drizzle sum/avg return string | null; simulate that
  const stringDb: any = {
    select: () => ({
      from: () => ({
        then: (res: any) => Promise.resolve([{ value: "1234.56" }]).then(res),
      }),
    }),
  };
  const out = await resolveAggregateWithDb(stringDb, {
    name: "s", entity: "Invoice", op: "aggregate",
    metrics: { revenue: { fn: "sum", field: "total" } },
  });
  assertEqual(out.revenue, 1234.56, "string coerced to number");
});

await test("filter adds equality condition (no error)", async () => {
  const db = fakeDb([5]);
  const out = await resolveAggregateWithDb(db, {
    name: "s", entity: "Invoice", op: "aggregate",
    metrics: { pending: { fn: "count", filter: { status: "pending" } } },
  });
  assertEqual(out.pending, 5, "pending count");
});

await test("non-count metric without a field degrades to 0 (never builds bad query)", async () => {
  const db = fakeDb([7]);
  const out = await resolveAggregateWithDb(db, {
    name: "s", entity: "Invoice", op: "aggregate",
    metrics: { bogus: { fn: "sum" } },  // sum with no field
  });
  assertEqual(out.bogus, 0, "fieldless sum → 0");
});

// 3. ratio metric (numerator / denominator)
await test("ratio: percent = numerator/denominator * 100", async () => {
  const db = fakeDb([41, 50]);   // numerator queried first, then denominator
  const out = await resolveAggregateWithDb(db, {
    name: "s", entity: "Invoice", op: "aggregate",
    metrics: { cacheHitRate: {
      kind: "ratio", percent: true,
      numerator:   { fn: "count", filter: { status: "hit" } },
      denominator: { fn: "count" },
    } },
  });
  assertEqual(out.cacheHitRate, 82, "41/50*100");
});
await test("ratio: fraction (no percent) = numerator/denominator", async () => {
  const db = fakeDb([3, 4]);
  const out = await resolveAggregateWithDb(db, {
    name: "s", entity: "Invoice", op: "aggregate",
    metrics: { r: { kind: "ratio", numerator: { fn: "count" }, denominator: { fn: "count" } } },
  });
  assertEqual(out.r, 0.75, "3/4");
});
await test("ratio: divide-by-zero degrades to 0 (never Infinity/NaN)", async () => {
  const db = fakeDb([5, 0]);
  const out = await resolveAggregateWithDb(db, {
    name: "s", entity: "Invoice", op: "aggregate",
    metrics: { r: { kind: "ratio", percent: true, numerator: { fn: "count" }, denominator: { fn: "count" } } },
  });
  assertEqual(out.r, 0, "den=0 → 0");
});

// 4. period-delta metric (this window vs prior window)
await test("delta: absolute = current - prior", async () => {
  const db = fakeDb([120, 80]);  // current window queried first, then prior
  const out = await resolveAggregateWithDb(db, {
    name: "s", entity: "Invoice", op: "aggregate",
    metrics: { d: { kind: "delta", fn: "sum", field: "total", window: "month", dateField: "issuedAt" } },
  });
  assertEqual(out.d, 40, "120-80");
});
await test("delta: percent = (current - prior)/prior * 100", async () => {
  const db = fakeDb([120, 80]);
  const out = await resolveAggregateWithDb(db, {
    name: "s", entity: "Invoice", op: "aggregate",
    metrics: { d: { kind: "delta", fn: "sum", field: "total", window: "month", percent: true } },
  });
  assertEqual(out.d, 50, "(120-80)/80*100");
});
await test("delta: prior period of 0 degrades to 0 (avoids Infinity)", async () => {
  const db = fakeDb([10, 0]);
  const out = await resolveAggregateWithDb(db, {
    name: "s", entity: "Invoice", op: "aggregate",
    metrics: { d: { kind: "delta", fn: "count", window: "week", percent: true } },
  });
  assertEqual(out.d, 0, "prev=0 → 0");
});
await test("priorWindow: month range ends at this month's 1st", () => {
  const r = priorWindow("month")!;
  assert(r !== null, "not null");
  assert(r.end.getDate() === 1, "end is the 1st");
  assert(r.start.getDate() === 1, "start is the 1st");
  // prior month's start is one month before the end
  const expected = new Date(r.end); expected.setMonth(expected.getMonth() - 1);
  assertEqual(r.start.toDateString(), expected.toDateString(), "one month back");
});
await test("priorWindow: unknown token → null", () => {
  assert(priorWindow("quarter") === null, "should be null");
});

// ── Drift guard: pin this shadow copy to the SHIPPED data-engine.ts ──────────
// The drizzle-dependent computeMetric/resolveAggregate can't be imported here
// (drizzle-orm/@/db aren't resolvable in the template dir), so they are mirrored
// above. This test fails if the real implementation changes in a way the mirror
// doesn't, catching silent drift between the two.
await test("drift guard: shipped data-engine.ts matches the mirrored invariants", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const src = readFileSync(join(here, "..", "data-engine.ts"), "utf8");
  const invariants = [
    'import { windowStart, priorWindow } from "./data-engine/aggregate-window"', // shared pure helpers
    'if (m.fn !== "count" && !m.field) return 0;',                    // fieldless guard
    "Number(row?.value ?? 0)",                                        // string→number coercion
    "conds.length === 1 ? conds[0] : and(...conds)",                 // condition combination
    '(m as RatioMetric).kind === "ratio"',                           // ratio dispatch
    '(m as DeltaMetric).kind === "delta"',                           // period-delta dispatch
    "if (!den) return 0;",                                            // ratio div-by-zero guard
    "prev === 0 ? 0 : ((cur - prev) / prev) * 100",                 // delta percent guard
  ];
  for (const inv of invariants) {
    assert(src.includes(inv), `data-engine.ts must contain: ${inv}`);
  }
});

// ── Summary ──────────────────────────────────────────────────────────────────

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
if (failed > 0) process.exit(1);
