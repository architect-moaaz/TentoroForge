/**
 * A Grid must stay responsive at every viewport.
 *
 * `equalCols` used to emit an inline `grid-template-columns: repeat(N, ...)`.
 * An inline style beats every media query, so `lg:grid-cols-3` never applied
 * and a 3-column dashboard row stayed 3 columns at 375px — each column ~100px
 * wide, wrapping headings one letter per line. The responsive classes shipped;
 * they were simply never allowed to win.
 *
 * The inline style bought nothing: Tailwind's own `grid-cols-N` is already
 * defined as `repeat(N, minmax(0, 1fr))`, which is exactly what equalCols
 * wanted. So it paid for a duplicate with the entire responsive behaviour.
 */
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { Grid } from "../src/nodes/layout/Grid";

/** Render the Grid and read back its class + style attributes. */
const grid = (props: Record<string, unknown>) => {
  const html = renderToString(
    <Grid node={{ id: "g", props }}>{[<div key="a" />]}</Grid>,
  );
  const pick = (attr: string) =>
    new RegExp(`${attr}="([^"]*)"`).exec(html)?.[1] ?? "";
  return { className: pick("class"), style: pick("style"), html };
};

describe("Grid responsiveness", () => {
  it("never pins grid-template-columns inline, even with equalCols", () => {
    const el = grid({ columns: 3, equalCols: true });
    expect(el.style).not.toContain("grid-template-columns");
  });

  it("keeps the responsive step-down classes when equalCols is set", () => {
    const el = grid({ columns: 3, equalCols: true });
    expect(el.className).toContain("grid-cols-1");
    expect(el.className).toContain("sm:grid-cols-2");
    expect(el.className).toContain("lg:grid-cols-3");
  });

  it("still applies equalRows — a row rule is viewport-independent", () => {
    expect(grid({ columns: 3, equalRows: true }).style)
      .toContain("grid-auto-rows:1fr");
  });

  it("a caller's explicit style override is still honoured", () => {
    // The Figma/MCP path passes real authored CSS; that is a deliberate
    // instruction, not a default the component invented.
    const el = grid({ columns: 3, style: { gridTemplateColumns: "1fr 2fr" } });
    expect(el.style).toContain("grid-template-columns:1fr 2fr");
  });

  it.each([2, 3, 4, 5, 6])("columns=%i starts at one or two on phones", (n) => {
    const cls = grid({ columns: n, equalCols: true }).className;
    expect(cls).toMatch(/(^|\s)grid-cols-[12](\s|$)/);
  });

  // A page composed from a design frame carries Dev Mode's own track spec.
  // The ladder on top of it let `sm:grid-cols-2` fold a drawn four-column row
  // at every viewport under `lg`, under the charts positioned beneath it.
  it("does not fold a grid whose className already declares its columns", () => {
    const el = grid({
      columns: 4,
      className: "grid-cols-[___355.66px_355.66px_355.66px_355.66px] gap-x-[16px]",
    });
    expect(el.className).toContain("grid-cols-[___355.66px");
    expect(el.className).not.toContain("sm:grid-cols-2");
    expect(el.className).not.toContain("lg:grid-cols-4");
    expect(el.className).not.toContain("grid-cols-1");
  });

  it("keeps the ladder for a grid with no spec of its own", () => {
    const el = grid({ columns: 4, className: "rounded-lg" });
    expect(el.className).toContain("lg:grid-cols-4");
  });
});
