import { describe, it, expect } from "vitest";
import { applyAction } from "../src/apply";
import type { Artifacts } from "../src/types";

function art(): Artifacts {
  return {
    pageSchemas: {
      "/customers": {
        schemaVersion: "2",
        id: "/customers",
        root: { type: "Stack", id: "root" },
        dataSources: [],
      },
    },
    navFlow: { initialPage: "/customers", pages: [], transitions: [], guards: {} } as any,
    tokens: {} as any,
  };
}

const src = {
  name: "customersByStatus",
  entity: "Customer",
  op: "series",
  groupBy: "status",
  agg: { fn: "count" },
};

describe("addDataSource / removeDataSource", () => {
  it("appends a series source and inverts to removeDataSource", () => {
    const { next, inverse } = applyAction(art(), {
      type: "addDataSource",
      pageId: "/customers",
      source: src,
    } as any);
    expect(next.pageSchemas["/customers"].dataSources).toEqual([src]);
    expect(inverse).toEqual({ type: "removeDataSource", pageId: "/customers", name: "customersByStatus" });
  });

  it("round-trips (add → undo restores empty)", () => {
    const r1 = applyAction(art(), { type: "addDataSource", pageId: "/customers", source: src } as any);
    const r2 = applyAction(r1.next, r1.inverse);
    expect(r2.next.pageSchemas["/customers"].dataSources).toEqual([]);
  });

  it("initialises dataSources when absent", () => {
    const a = art();
    delete (a.pageSchemas["/customers"] as any).dataSources;
    const { next } = applyAction(a, { type: "addDataSource", pageId: "/customers", source: src } as any);
    expect(next.pageSchemas["/customers"].dataSources).toEqual([src]);
  });

  it("rejects a duplicate source name", () => {
    const r1 = applyAction(art(), { type: "addDataSource", pageId: "/customers", source: src } as any);
    expect(() =>
      applyAction(r1.next, { type: "addDataSource", pageId: "/customers", source: src } as any),
    ).toThrow(/already exists/);
  });

  it("removeDataSource inverts to addDataSource with the removed source", () => {
    const withSrc = applyAction(art(), { type: "addDataSource", pageId: "/customers", source: src } as any).next;
    const { next, inverse } = applyAction(withSrc, {
      type: "removeDataSource",
      pageId: "/customers",
      name: "customersByStatus",
    } as any);
    expect(next.pageSchemas["/customers"].dataSources).toEqual([]);
    expect(inverse).toEqual({ type: "addDataSource", pageId: "/customers", source: src });
  });
});
