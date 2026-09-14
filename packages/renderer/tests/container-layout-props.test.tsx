// @vitest-environment jsdom
/**
 * Container's six registry-declared layout props, which the component ignored.
 *
 * The last two tests are the important ones: they pin the no-regression
 * guarantee. Blast radius was measured before this change — 0 of 26 Container
 * nodes on disk carry any of these props — and these tests keep it that way by
 * asserting a propless Container still renders exactly as the page wrapper it
 * has always been.
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Container } from "../src/nodes/layout/Container";

const mk = (props: Record<string, unknown>) => ({ id: "c1", type: "Container", props });
const cls = (props: Record<string, unknown>) => {
  const { container } = render(<Container node={mk(props)}>{[]}</Container>);
  return (container.firstElementChild as HTMLElement)?.className ?? "";
};

describe("Container — layout props are honoured", () => {
  it("direction=horizontal lays out as a row", () => {
    expect(cls({ direction: "horizontal" })).toContain("flex-row");
  });

  it("direction=vertical lays out as a column", () => {
    expect(cls({ direction: "vertical" })).toContain("flex-col");
  });

  it("gap maps onto the same scale Stack uses", () => {
    expect(cls({ gap: "none" })).toContain("gap-0");
    expect(cls({ gap: "sm" })).toContain("gap-2");
    expect(cls({ gap: "xl" })).toContain("gap-8");
  });

  it("align and justify map to flex utilities", () => {
    expect(cls({ align: "center" })).toContain("items-center");
    expect(cls({ justify: "between" })).toContain("justify-between");
    expect(cls({ justify: "evenly" })).toContain("justify-evenly");
  });

  it("wrap only when true", () => {
    expect(cls({ direction: "horizontal", wrap: true })).toContain("flex-wrap");
    expect(cls({ direction: "horizontal", wrap: false })).not.toContain("flex-wrap");
  });

  it("explicit padding REPLACES the responsive page padding", () => {
    const c = cls({ padding: "none" });
    expect(c).toContain("p-0");
    // otherwise `padding: none` would still render px-4 and read as broken
    expect(c).not.toContain("px-4");
  });

  it("distinct values produce distinct classes (no silent collapse)", () => {
    const seen = new Set(["none", "xs", "sm", "md", "lg", "xl"].map((g) => cls({ gap: g })));
    expect(seen.size).toBe(6);
  });

  // ---- no-regression guarantees -------------------------------------------
  it("a Container with NO layout props renders exactly as before", () => {
    const c = cls({});
    expect(c).toContain("mx-auto");
    expect(c).toContain("w-full");
    expect(c).toContain("px-4");
    expect(c).toContain("max-w-screen-lg");
    expect(c).not.toContain("flex");
  });

  it("maxWidth still works and is unaffected", () => {
    expect(cls({ maxWidth: "sm" })).toContain("max-w-screen-sm");
    expect(cls({ maxWidth: "full" })).not.toContain("max-w-screen");
  });
});
