import { describe, it, expect } from "vitest";
import { resolvePreviewSources } from "./preview-resolve";

const fixtures = {
  // Entity fixtures keyed like the /api/_debug/preview-data endpoint emits them.
  Dispatch: [
    { id: "1", status: "active", createdAt: "2025-01-06T00:00:00Z" },
    { id: "2", status: "active", createdAt: "2025-01-07T00:00:00Z" },
    { id: "3", status: "closed", createdAt: "2025-01-20T00:00:00Z" },
  ],
  MaintenanceOrder: [
    { id: "a", priority: "High", cost: 100 },
    { id: "b", priority: "High", cost: 200 },
    { id: "c", priority: "Low", cost: 50 },
  ],
};

describe("resolvePreviewSources", () => {
  it("resolves op:aggregate metrics keyed by source name", () => {
    const out = resolvePreviewSources(
      [{
        name: "dashboardStats", entity: "Dispatch", op: "aggregate",
        metrics: {
          total: { fn: "count" },
          active: { fn: "count", filter: { status: "active" } },
          spend: { fn: "sum", field: "cost", entity: "MaintenanceOrder" },
        },
      }],
      fixtures,
    );
    expect(out.dashboardStats).toEqual({ total: 3, active: 2, spend: 350 });
  });

  it("resolves op:series category grouping sorted by value", () => {
    const out = resolvePreviewSources(
      [{ name: "byPriority", entity: "MaintenanceOrder", op: "series",
         groupBy: "priority", agg: { fn: "count" }, sort: "value" }],
      fixtures,
    );
    expect(out.byPriority).toEqual([
      { label: "High", value: 2 },
      { label: "Low", value: 1 },
    ]);
  });

  it("resolves op:series time bucket chronologically", () => {
    const out = resolvePreviewSources(
      [{ name: "byWeek", entity: "Dispatch", op: "series",
         groupBy: "createdAt", bucket: "week", agg: { fn: "count" } }],
      fixtures,
    ) as any;
    const series = out.byWeek as Array<{ label: string; value: number }>;
    // Jan 6 & 7 fall in one week (2), Jan 20 in a later week (1); chronological order.
    expect(series.map((r) => r.value)).toEqual([2, 1]);
    expect(series.length).toBe(2);
  });

  it("resolves op:list to the entity rows under the source name", () => {
    const out = resolvePreviewSources(
      [{ name: "dispatches", entity: "Dispatch", op: "list", limit: 2 }],
      fixtures,
    );
    expect(Array.isArray(out.dispatches)).toBe(true);
    expect((out.dispatches as any[]).length).toBe(2);
  });

  it("finds entity rows across key aliases (plural / case)", () => {
    const out = resolvePreviewSources(
      [{ name: "orders", entity: "MaintenanceOrder", op: "list" }],
      { maintenanceOrders: fixtures.MaintenanceOrder } as any,
    );
    expect((out.orders as any[]).length).toBe(3);
  });

  it("keeps original entity keys and passes through when no sources", () => {
    const out = resolvePreviewSources(undefined, fixtures);
    expect(out).toBe(fixtures);
  });

  it("degrades a missing entity to [] without throwing", () => {
    const out = resolvePreviewSources(
      [{ name: "ghosts", entity: "Nonexistent", op: "series", groupBy: "x" }],
      fixtures,
    );
    expect(out.ghosts).toEqual([]);
  });
});

/**
 * B13 — the `expression` metric dialect.
 *
 * `output/gh0mlpbp/app/src/schemas/items.json` declared its KPI metrics as
 * `{"expression": "sum(quantity * price)", "format": "currency"}` while this
 * resolver (and the generated app's data engine) reads `{fn, field}`. Nothing
 * parsed the other form, so a correctly-NAMED aggregate source still resolved
 * to a row count or nothing at all, and the three Inventory KPI tiles were
 * blank. The generator now normalises the dialect away, but every project
 * already on disk still carries it — so the resolver has to speak both.
 */
const inventory = {
  Item: [
    { id: "1", name: "Bolt", quantity: 10, price: 2.5, category: "Parts" },
    { id: "2", name: "Nut", quantity: 3, price: 1.0, category: "Parts" },
    { id: "3", name: "Washer", quantity: 4, price: 0.5, category: "Parts" },
  ],
};

// Verbatim from the failing artifact, before the generator-side repair.
const itemsSources = [
  { name: "items", entity: "Item", op: "list", limit: 500 },
  {
    name: "totalInventoryValue", entity: "Item", op: "aggregate",
    metrics: {
      itemCount: { expression: "count(id)", format: "number" },
      totalValue: { expression: "sum(quantity * price)", format: "currency" },
    },
  },
] as any;

describe("aggregate metric dialects", () => {
  it("resolves the shipped items.json `expression` metrics to real numbers", () => {
    const out = resolvePreviewSources(itemsSources, inventory);
    // 10*2.5 + 3*1 + 4*0.5 = 25 + 3 + 2 = 30
    expect(out.totalInventoryValue).toEqual({ itemCount: 3, totalValue: 30 });
  });

  it("resolves the normalised `expr` form the generator now emits", () => {
    const out = resolvePreviewSources(
      [{ name: "kpi", entity: "Item", op: "aggregate", metrics: {
        totalValue: { fn: "sum", expr: "quantity * price" },
      } }] as any,
      inventory,
    );
    expect(out.kpi).toEqual({ totalValue: 30 });
  });

  it("reads count(id) as a row count, not a sum of ids", () => {
    const out = resolvePreviewSources(
      [{ name: "kpi", entity: "Item", op: "aggregate", metrics: {
        n: { expression: "count(id)" },
      } }] as any,
      inventory,
    );
    expect(out.kpi).toEqual({ n: 3 });
  });

  it("translates a single-column expression, aliases included", () => {
    const out = resolvePreviewSources(
      [{ name: "kpi", entity: "Item", op: "aggregate", metrics: {
        stock: { expression: "sum(quantity)" },
        typical: { expression: "average(price)" },
        cheapest: { expression: "min(price)" },
        dearest: { expression: "max(price)" },
      } }] as any,
      inventory,
    );
    expect(out.kpi).toEqual({ stock: 17, typical: 1.33, cheapest: 0.5, dearest: 2.5 });
  });

  it("honours operator precedence and parentheses inside an expression", () => {
    const out = resolvePreviewSources(
      [{ name: "kpi", entity: "Item", op: "aggregate", metrics: {
        a: { fn: "sum", expr: "quantity + price * 2" },
        b: { fn: "sum", expr: "(quantity + price) * 2" },
      } }] as any,
      inventory,
    );
    // a: 10+5 + 3+2 + 4+1 = 25 ; b: 2*(12.5 + 4 + 4.5) = 42
    expect(out.kpi).toEqual({ a: 25, b: 42 });
  });

  it("prefers a machine-readable fn over the expression beside it", () => {
    const out = resolvePreviewSources(
      [{ name: "kpi", entity: "Item", op: "aggregate", metrics: {
        stock: { fn: "sum", field: "quantity", expression: "count(id)" },
      } }] as any,
      inventory,
    );
    expect(out.kpi).toEqual({ stock: 17 });
  });

  it("degrades an unparseable expression to a count instead of throwing", () => {
    const out = resolvePreviewSources(
      [{ name: "kpi", entity: "Item", op: "aggregate", metrics: {
        weird: { expression: "percentile(0.9, latency)" },
        injected: { fn: "sum", expr: "quantity); drop table items --" },
      } }] as any,
      inventory,
    );
    // `percentile(...)` is not an aggregate call we can vouch for, so the
    // metric keeps its (absent) fn and falls back to the row count. The
    // injected `expr` IS on an explicit sum, and every row evaluates to NaN →
    // 0. Both degrade; neither throws, and nothing from either string is ever
    // evaluated as code.
    expect(out.kpi).toEqual({ weird: 3, injected: 0 });
  });

  it("treats division by zero as 0 rather than Infinity", () => {
    const out = resolvePreviewSources(
      [{ name: "kpi", entity: "Item", op: "aggregate", metrics: {
        ratio: { fn: "sum", expr: "quantity / missing" },
      } }] as any,
      inventory,
    );
    expect(out.kpi).toEqual({ ratio: 0 });
  });
});
