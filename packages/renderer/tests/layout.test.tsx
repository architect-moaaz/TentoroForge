import { describe, it, expect } from "vitest";
import { renderNode } from "../src/runtime/dispatch";
import { renderToString } from "react-dom/server";

const ctx = { data: {}, slots: {}, layouts: {} } as any;

describe("Stack renderer", () => {
  it("renders a flex column with gap variable", () => {
    const html = renderToString(
      renderNode(
        {
          id: "s",
          type: "Stack",
          props: { direction: "vertical", gap: "spacing.4", align: "stretch", justify: "start" },
          children: [],
        } as any,
        ctx
      )
    );
    // Layout is now className-driven (responsive Tailwind utilities) so
    // gap and direction are emitted as Tailwind class names, not inline styles.
    // "spacing.4" is not in the GAP_CLASS map, so it falls back to "gap-4".
    expect(html).toContain('class="flex flex-col');
    expect(html).toContain("gap-4");
  });
});

describe("Spacer renderer", () => {
  it("renders an empty div with height/width set", () => {
    const html = renderToString(
      renderNode({ id: "sp", type: "Spacer", props: { size: "spacing.6" } } as any, ctx)
    );
    // The var() now carries a literal fallback so the Spacer still has a size
    // on a page whose token stylesheet has not loaded — see Spacer.tsx.
    expect(html).toContain("var(--token-spacing-6,");
  });
});

describe("Grid renderer — responsive columns", () => {
  it("columns:3 emits grid-cols-1 sm:grid-cols-2 lg:grid-cols-3", () => {
    const html = renderToString(
      renderNode(
        { id: "g", type: "Grid", props: { columns: 3 }, children: [] } as any,
        ctx
      )
    );
    expect(html).toContain("grid-cols-1");
    expect(html).toContain("sm:grid-cols-2");
    expect(html).toContain("lg:grid-cols-3");
  });

  it("columns:2 emits grid-cols-1 md:grid-cols-2", () => {
    const html = renderToString(
      renderNode(
        { id: "g", type: "Grid", props: { columns: 2 }, children: [] } as any,
        ctx
      )
    );
    expect(html).toContain("grid-cols-1");
    expect(html).toContain("md:grid-cols-2");
    // should NOT have sm or lg variant for the column count
    expect(html).not.toContain("lg:grid-cols-2");
  });

  it("columns:4 emits grid-cols-1 sm:grid-cols-2 lg:grid-cols-4", () => {
    const html = renderToString(
      renderNode(
        { id: "g", type: "Grid", props: { columns: 4 }, children: [] } as any,
        ctx
      )
    );
    expect(html).toContain("grid-cols-1");
    expect(html).toContain("sm:grid-cols-2");
    expect(html).toContain("lg:grid-cols-4");
  });

  it("columns:1 emits only grid-cols-1", () => {
    const html = renderToString(
      renderNode(
        { id: "g", type: "Grid", props: { columns: 1 }, children: [] } as any,
        ctx
      )
    );
    expect(html).toContain("grid-cols-1");
    expect(html).not.toContain("sm:grid-cols");
    expect(html).not.toContain("lg:grid-cols");
  });
});

describe("Grid renderer — equalRows / equalCols (v4 spike fix)", () => {
  // These props codify the iteration-3 v4 spike CSS fix into schema-driven
  // behaviour so future generations don't depend on hand-injected
  // globals.css. equalRows emits `grid-auto-rows: 1fr` (equal-height rows);
  // equalCols swaps the Tailwind class-driven `repeat(N, 1fr)` template for
  // an inline `repeat(N, minmax(0, 1fr))` so wide children can't expand
  // their column past the equal share.
  it("emits grid-auto-rows: 1fr when equalRows is true", () => {
    const html = renderToString(
      renderNode(
        { id: "g", type: "Grid", props: { columns: 4, equalRows: true }, children: [] } as any,
        ctx
      )
    );
    expect(html).toContain("grid-auto-rows:1fr");
  });

  it("does NOT pin columns inline when equalCols is true", () => {
    const html = renderToString(
      renderNode(
        { id: "g", type: "Grid", props: { columns: 4, equalCols: true }, children: [] } as any,
        ctx
      )
    );
    // This test previously asserted the opposite. The inline style beat every
    // media query, so `lg:grid-cols-4` never applied and the grid stayed 4
    // columns on a phone. Tailwind's `grid-cols-4` already IS
    // `repeat(4, minmax(0, 1fr))`, so the classes deliver equalCols' intent
    // at every breakpoint and the inline rule only cost responsiveness.
    expect(html).not.toContain("grid-template-columns");
    expect(html).toContain("grid-cols-1");
    expect(html).toContain("lg:grid-cols-4");
  });

  it("emits neither style when both props are omitted (backward-compat)", () => {
    const html = renderToString(
      renderNode(
        { id: "g", type: "Grid", props: { columns: 4 }, children: [] } as any,
        ctx
      )
    );
    expect(html).not.toContain("grid-auto-rows");
    expect(html).not.toContain("minmax");
  });

  it("clamps the column count to the schema max (12) in the classes", () => {
    const html = renderToString(
      renderNode(
        { id: "g", type: "Grid", props: { columns: 12, equalCols: true }, children: [] } as any,
        ctx
      )
    );
    // The clamp still matters — it just lives in the class ladder now, which
    // is the only place that can express "12 wide, but not on a phone".
    expect(html).toContain("lg:grid-cols-12");
    expect(html).toContain("grid-cols-2");
  });
});

describe("Row renderer — default cross-axis alignment", () => {
  it("uses items-center by default on regular rows", () => {
    const html = renderToString(
      renderNode(
        { id: "r", type: "Row", props: { className: "w-full" }, children: [] } as any,
        ctx
      )
    );
    expect(html).toContain("items-center");
    expect(html).not.toContain("items-stretch");
  });

  it("switches to items-stretch when className declares full viewport height", () => {
    // h-screen / h-full / min-h-screen rows are page shells where vertical
    // centring leaves a visible gap above + below the children. The default
    // flips to stretch so a 247px sidebar + flex-1 main both fill the row.
    const html = renderToString(
      renderNode(
        {
          id: "r",
          type: "Row",
          props: { className: "h-screen w-full" },
          children: [],
        } as any,
        ctx
      )
    );
    expect(html).toContain("items-stretch");
    expect(html).not.toContain("items-center");
  });

  it("caller items-* still wins over the default", () => {
    const html = renderToString(
      renderNode(
        {
          id: "r",
          type: "Row",
          props: { className: "h-screen items-end" },
          children: [],
        } as any,
        ctx
      )
    );
    expect(html).toContain("items-end");
    // The hasFullHeight default is dropped because the caller already set items-*.
    expect(html).not.toContain("items-stretch");
  });
});

describe("layout nodes — className + data-* passthrough", () => {
  // Schema-supplied data-* props mark nodes for app-level CSS/JS hooks
  // (e.g. data-dashboard-toolbar). Grid/Row/Stack already appended
  // props.className; data-* was silently dropped.
  it("Grid spreads data-* and appends className", () => {
    const html = renderToString(
      renderNode(
        {
          id: "g",
          type: "Grid",
          props: { columns: 2, className: "dashboard-grid", "data-dashboard-grid": "" },
          children: [],
        } as any,
        ctx
      )
    );
    expect(html).toContain("dashboard-grid");
    expect(html).toContain("data-dashboard-grid");
  });

  it("Row spreads data-* and appends className", () => {
    const html = renderToString(
      renderNode(
        {
          id: "r",
          type: "Row",
          props: { className: "toolbar-row", "data-toolbar": "main" },
          children: [],
        } as any,
        ctx
      )
    );
    expect(html).toContain("toolbar-row");
    expect(html).toContain('data-toolbar="main"');
  });

  it("Stack spreads data-* and appends className", () => {
    const html = renderToString(
      renderNode(
        {
          id: "st",
          type: "Stack",
          props: { direction: "vertical", className: "side-stack", "data-side-stack": "" },
          children: [],
        } as any,
        ctx
      )
    );
    expect(html).toContain("side-stack");
    expect(html).toContain("data-side-stack");
  });
});
