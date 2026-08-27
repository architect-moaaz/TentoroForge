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
