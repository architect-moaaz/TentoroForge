// @vitest-environment jsdom
/**
 * Grid's rowGap / columnGap / padding / align — declared by the registry with
 * live editor controls, read by nothing.
 *
 * Unlike Container, this change IS visible to existing work: 5 of the 12 Grid
 * nodes on disk already carry these values. The last tests pin the parts that
 * must not move for everyone else.
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Grid } from "../src/nodes/layout/Grid";

const cls = (props: Record<string, unknown>) => {
  const { container } = render(<Grid node={{ id: "g1", type: "Grid", props }}>{[]}</Grid>);
  return (container.firstElementChild as HTMLElement)?.className ?? "";
};

describe("Grid — axis gaps, padding and align are honoured", () => {
  it("rowGap emits a y-axis gap", () => {
    expect(cls({ rowGap: "lg" })).toContain("gap-y-6");
  });

  it("columnGap emits an x-axis gap", () => {
    expect(cls({ columnGap: "sm" })).toContain("gap-x-2");
  });

  it("axis gaps derive from the same scale as `gap` (md means md everywhere)", () => {
    // gap-4 is what gapClass("md") yields; the axis forms must agree.
    expect(cls({ gap: "md" })).toContain("gap-4");
    expect(cls({ rowGap: "md" })).toContain("gap-y-4");
    expect(cls({ columnGap: "md" })).toContain("gap-x-4");
  });

  it("padding maps onto the spacing scale", () => {
    expect(cls({ padding: "none" })).toContain("p-0");
    expect(cls({ padding: "xl" })).toContain("p-8");
  });

  it("align maps to flex/grid item alignment", () => {
    expect(cls({ align: "center" })).toContain("items-center");
    expect(cls({ align: "end" })).toContain("items-end");
  });

  it("distinct values produce distinct classes (no silent collapse)", () => {
    const seen = new Set(["none", "xs", "sm", "md", "lg", "xl"].map((g) => cls({ rowGap: g })));
    expect(seen.size).toBe(6);
  });

  // ---- what must not move --------------------------------------------------
  it("a Grid with none of these props renders as before", () => {
    const c = cls({ columns: 2 });
    expect(c).toContain("grid");
    expect(c).toContain("gap-4");          // the long-standing default
    expect(c).not.toContain("gap-y-");
    expect(c).not.toContain("gap-x-");
    expect(c).not.toMatch(/\bp-\d/);
    expect(c).not.toContain("items-");
  });

  it("the combined gap still applies when no axis gap is given", () => {
    expect(cls({ gap: "xl" })).toContain("gap-8");
  });

  it("a caller-supplied grid-cols spec still suppresses the responsive ladder", () => {
    const c = cls({ columns: 4, className: "grid-cols-[100px_100px]" });
    expect(c).toContain("grid-cols-[100px_100px]");
  });
});
