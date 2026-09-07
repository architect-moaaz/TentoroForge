import { describe, it, expect } from "vitest";
import { NodeV2 } from "../src/page";

/**
 * Grid's props object is `.strict()`, so an undeclared prop does not fall
 * through — it makes the WHOLE page fail to parse. `rows` therefore had to be
 * added to both GridNode (nodes/layout.ts) and V2GridNode (page.ts), and this
 * is the test that catches it if one of them is ever dropped: the editor's
 * symptom would be a save that is rejected with no visible cause.
 */
describe("fixed R x C grids in the page schema", () => {
  it("a Grid with rows, holding GridCell children, parses", () => {
    const r = NodeV2.safeParse({
      id: "g1",
      type: "Grid",
      props: { columns: 3, rows: 2 },
      children: [
        {
          id: "c1",
          type: "GridCell",
          props: {},
          children: [{ id: "t1", type: "Text", props: { content: "a" } }],
        },
        { id: "c2", type: "GridCell", props: {}, children: [] },
      ],
    });
    expect(r.success, JSON.stringify((r as any).error?.issues?.slice(0, 3))).toBe(true);
  });

  it("a legacy Grid with no rows prop still parses — rows is additive", () => {
    expect(
      NodeV2.safeParse({ id: "g2", type: "Grid", props: { columns: 2 }, children: [] }).success,
    ).toBe(true);
  });

  it("rows: 0 — the registry default, meaning auto — parses", () => {
    expect(
      NodeV2.safeParse({ id: "g4", type: "Grid", props: { columns: 2, rows: 0 }, children: [] })
        .success,
    ).toBe(true);
  });

  it("rejects a row count past the 12 tracks Tailwind's grid-cols-N stops at", () => {
    expect(
      NodeV2.safeParse({ id: "g3", type: "Grid", props: { columns: 2, rows: 99 }, children: [] })
        .success,
    ).toBe(false);
  });
});
