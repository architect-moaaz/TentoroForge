/**
 * Drop sizing — a node dropped from the palette must arrive at a size derived
 * from the container it landed in, for EVERY component type.
 *
 * Two failures are locked down here:
 *
 *  1. buildDroppedNode emitted no `style` at all, so an empty Card rendered as
 *     `width:auto` (= the parent's full width) with `height:auto` and no content
 *     (= padding only) — a full-bleed hairline strip that reads as a broken
 *     render. See deriveDropStyle / SHAPE_BY_NAME in useDrop.ts.
 *  2. A dropped Sidebar was "a single solid block": Sidebar.tsx maps over its
 *     children to build its panes, and `children: []` produced zero panes in an
 *     empty grid. See scaffoldPanes.
 */
import { describe, it, expect } from "vitest";
import { starterRegistry } from "@forge/registry";
import {
  deriveDropStyle,
  measureParentBox,
  buildDroppedNode,
  validateDrop,
} from "@/components/canvas/hooks/useDrop";

const PARENT = { width: 1200, height: 800 };
const ALL_NAMES = Object.keys(starterRegistry as Record<string, unknown>);

/**
 * The types that are deliberately NOT sized, in four justified groups (see the
 * UNSIZED comment in useDrop.ts): anchored/viewport overlays, zero-box
 * wrappers, fixed-geometry controls, and inline text runs. Duplicated here on
 * purpose — the coverage test below is only meaningful if adding a name to the
 * source set also has to be argued for here.
 */
const EXPECTED_UNSIZED = [
  // 1. anchored / viewport overlays
  "Dialog", "Drawer", "Popover", "Tooltip", "HoverCard", "Lightbox",
  "CommandPalette", "DropdownMenu", "ContextMenu", "TourOverlay",
  "UndoManager", "InspectorPanel",
  // 2. zero-box wrappers
  "Repeat", "Conditional", "DataBoundary", "Slot", "FadeIn", "Stagger",
  "OptimisticProvider", "FocusTrap", "FocusRing", "AutoFocus", "Redirect",
  // 3. intrinsically-sized controls. RadioGroup joined this group: it was in
  //    FIELD_BOX, whose 96px minHeight floor was pure dead space around a
  //    group that has no options yet — the "they take the complete size, it
  //    should be exactly what is required" report.
  "Checkbox", "Switch", "RadioGroup", "IconButton", "Rating", "InputOTP",
  "ThemeToggle", "Spinner", "Avatar", "QRCode", "PresenceIndicator", "CartBadge",
  // 4. inline text runs
  "MoneyDisplay", "Badge", "Tag", "Link", "NavLink", "SkipLink",
  // 5. grid-track residents — a GridCell's box IS its grid track, and the track
  //    changes width at every breakpoint, so any px width would be wrong
  //    everywhere except the viewport it was measured at.
  "GridCell",
];

// =============================================================================
describe("coverage — no component silently falls through to no style", () => {
  it("sizes every registry component except the named, justified exclusions", () => {
    const unstyled = ALL_NAMES.filter((n) => deriveDropStyle(n, PARENT) === null);
    expect(unstyled.sort()).toEqual([...EXPECTED_UNSIZED].sort());
  });

  it("covers the whole registry — sized + unsized accounts for every entry", () => {
    const sized = ALL_NAMES.filter((n) => deriveDropStyle(n, PARENT) !== null);
    expect(sized.length + EXPECTED_UNSIZED.length).toBe(ALL_NAMES.length);
    expect(ALL_NAMES.length).toBeGreaterThanOrEqual(133);
  });

  it("every sized component gets at least one real dimension, in raw CSS px", () => {
    const bad: string[] = [];
    for (const name of ALL_NAMES) {
      const s = deriveDropStyle(name, PARENT);
      if (!s) continue;
      // The px dimensions are the CEILING and the height floor. `width` is the
      // fluid "100%" that lets a node shrink with its parent, so it is not a
      // raw-px value and is checked separately below.
      const dims = [s.maxWidth, s.minHeight].filter(Boolean) as string[];
      if (!dims.length) bad.push(`${name}: no dimension`);
      for (const v of dims) if (!/^\d+px$/.test(v)) bad.push(`${name}: "${v}" is not raw px`);
      // A sized width is always fluid with a px ceiling — never a frozen px
      // width, which is what stopped the device preview reflowing anything.
      if (s.width && s.width !== "100%") bad.push(`${name}: width "${s.width}" is not fluid`);
      if (s.width && !s.maxWidth) bad.push(`${name}: fluid width without a maxWidth ceiling`);
    }
    expect(bad).toEqual([]);
  });

  it("never produces a child wider than the parent's content box", () => {
    const bad: string[] = [];
    for (const name of ALL_NAMES) {
      // A 90px rail is narrower than every `min` guard rail in the table.
      // The CEILING is what carries the px value now — `width` is the fluid
      // "100%" that lets the node shrink with its parent, so a check against it
      // would be comparing 100 (from "100%") against a pixel count.
      const s = deriveDropStyle(name, { width: 90, height: 400 });
      if (s?.maxWidth && s.maxWidth.endsWith("px") && parseInt(s.maxWidth, 10) > 90) {
        bad.push(`${name}: ${s.maxWidth} > 90px`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("never produces a child taller than a parent with a definite height", () => {
    const bad: string[] = [];
    for (const name of ALL_NAMES) {
      const s = deriveDropStyle(name, { width: 1200, height: 70 });
      if (s?.minHeight && parseInt(s.minHeight, 10) > 70) bad.push(`${name}: ${s.minHeight} > 70px`);
    }
    expect(bad).toEqual([]);
  });

  it("emits minHeight, never a hard height that would clip content", () => {
    for (const name of ALL_NAMES) {
      expect(deriveDropStyle(name, PARENT) ?? {}).not.toHaveProperty("height");
    }
  });
});

// =============================================================================
describe("the per-type proportion table", () => {
  it("REGION — layout primitives span the parent and get a height floor", () => {
    // 1.0 x 1200 wide; 0.25 x 800 = 200 tall.
    for (const name of ["Container", "Grid", "Stack", "Row", "Section", "Form", "Hero"]) {
      expect(deriveDropStyle(name, PARENT)).toEqual({
        width: "100%", maxWidth: "1200px", minHeight: "200px",
      });
    }
  });

  it("PANEL — data surfaces get a taller floor (a 96px Chart shows nothing)", () => {
    // 0.45 x 800 = 360.
    for (const name of ["Chart", "Table", "DataGrid", "Kanban", "Calendar"]) {
      expect(deriveDropStyle(name, PARENT)).toEqual({
        width: "100%", maxWidth: "1200px", minHeight: "360px",
      });
    }
  });

  it("SURFACE — a card lands ~2-across and card-shaped, not full bleed", () => {
    // 0.42 x 1200 = 504 -> capped at 420; 420 / 1.6 = 263.
    for (const name of ["Card", "MetricTile", "FeatureCard", "Stat"]) {
      expect(deriveDropStyle(name, PARENT)).toEqual({
        width: "100%", maxWidth: "420px", minHeight: "263px",
      });
    }
  });

  it("BAND — thin full-width strips", () => {
    // 0.06 x 800 = 48.
    for (const name of ["Alert", "Progress", "Sparkline", "Breadcrumb", "Spacer"]) {
      expect(deriveDropStyle(name, PARENT)).toEqual({
        width: "100%", maxWidth: "1200px", minHeight: "48px",
      });
    }
  });

  it("RULE — a Divider is sized on WIDTH ONLY; a hairline's thinness is its identity", () => {
    expect(deriveDropStyle("Divider", PARENT)).toEqual({
      width: "100%", maxWidth: "1200px",
    });
    // And it really does scale with the parent rather than using a constant.
    expect(deriveDropStyle("Divider", { width: 640, height: 400 })).toEqual({
      width: "100%", maxWidth: "640px",
    });
  });

  it("FIELD — a control gets a proportional width but keeps its constant height", () => {
    // 0.6 x 1200 = 720 -> capped at 520. No minHeight: a 200px-tall <select>
    // is a broken select, not a big one.
    for (const name of ["Input", "Select", "Slider", "DatePicker", "SearchInput"]) {
      expect(deriveDropStyle(name, PARENT)).toEqual({ width: "100%", maxWidth: "520px" });
    }
  });

  it("FIELD_BOX — controls that ARE boxes also get a floor", () => {
    // 0.18 x 800 = 144.
    // RadioGroup is deliberately NOT here any more — see the UNSIZED test
    // below and the user report about controls taking the full width.
    for (const name of ["Textarea", "FileUpload", "KeyValueInput"]) {
      expect(deriveDropStyle(name, PARENT)).toEqual({
        width: "100%", maxWidth: "520px", minHeight: "144px",
      });
    }
  });

  it("ACTION / TEXT — a button is button-width, a heading gets a readable measure", () => {
    // 0.16 x 1200 = 192; 0.7 x 1200 = 840 -> capped at 720.
    expect(deriveDropStyle("Button", PARENT)).toEqual({ width: "100%", maxWidth: "192px" });
    expect(deriveDropStyle("Heading", PARENT)).toEqual({ width: "100%", maxWidth: "720px" });
  });
});

// =============================================================================
describe("derivation, not constants", () => {
  it("a Card scales down with a mid-size parent", () => {
    // 0.42 x 600 = 252, inside [240, 420] -> used as-is.
    expect(deriveDropStyle("Card", { width: 600, height: 400 })).toEqual({
      width: "100%", maxWidth: "252px", minHeight: "158px",
    });
  });

  it("a Grid shrinks to a narrow rail instead of overflowing it", () => {
    expect(deriveDropStyle("Grid", { width: 200, height: 400 })).toEqual({
      width: "100%", maxWidth: "200px", minHeight: "100px",
    });
  });

  it("falls back to the parent WIDTH when the parent measures 0 tall", () => {
    // An empty auto-height parent (a fresh page root) has no height signal.
    // REGION fromWidth 0.15 x 1200 = 180.
    expect(deriveDropStyle("Stack", { width: 1200, height: 0 })).toEqual({
      width: "100%", maxWidth: "1200px", minHeight: "180px",
    });
  });

  it("returns null rather than guessing when the parent can't be measured", () => {
    expect(deriveDropStyle("Card", null)).toBeNull();
    expect(deriveDropStyle("Card", { width: 0, height: 0 })).toBeNull();
    expect(deriveDropStyle("Grid", { width: 0, height: 500 })).toBeNull();
    expect(deriveDropStyle("Divider", null)).toBeNull();
  });

  it("returns null for a type that isn't in the registry", () => {
    expect(deriveDropStyle("NotAComponent", PARENT)).toBeNull();
  });
});

// =============================================================================
describe("fixed-pane scaffolding — a dropped Sidebar must be two-sided", () => {
  it.each(["Sidebar", "Split", "SplitView"])(
    "%s arrives with exactly its two required panes",
    (name) => {
      const node = buildDroppedNode(name, PARENT);
      expect(node.children).toHaveLength(2);
      for (const pane of node.children as any[]) {
        expect(pane.type).toBe("Card");
        expect(pane.children).toEqual([]);
        // Panes are sized on HEIGHT ONLY — the parent layout's own responsive
        // grid track owns the width (Sidebar is 1fr below 768px, `<width> 1fr`
        // at md+), so a px width here would fight that grid.
        expect(pane.style).toEqual({ minHeight: "200px" });
      }
      // Distinct ids, or validateForCommit rejects the whole insert.
      const ids = (node.children as any[]).map((c) => c.id);
      expect(new Set(ids).size).toBe(2);
    },
  );

  it("the scaffolded panes satisfy the parent's own drop contract", () => {
    for (const name of ["Sidebar", "Split", "SplitView"]) {
      expect(validateDrop(name, "Card", 0).ok).toBe(true);
      expect(validateDrop(name, "Card", 1).ok).toBe(true);
    }
  });

  it("Sidebar and Split really do cap at 2 children (the maxChildren comment is accurate)", () => {
    // dist/starter.json is a props-only snapshot with no `slots` for ANY
    // component; the real registry does declare the cap.
    expect(validateDrop("Sidebar", "Card", 2).ok).toBe(false);
    expect(validateDrop("Split", "Card", 2).ok).toBe(false);
    // Contrast: an uncapped list container keeps accepting.
    expect(validateDrop("Stack", "Card", 9).ok).toBe(true);
  });

  it("a GridCell takes any component, and any number of them", () => {
    // "Inside each box I should be able to add anything" — so no accepts list
    // and no maxChildren. This is the contract the auto-fill redirect in
    // resolveAcceptingParent checks before it retargets a drop into a cell.
    for (const kid of ["Image", "Text", "Card", "Chart", "Button", "Grid"]) {
      expect(validateDrop("GridCell", kid, 0).ok).toBe(true);
      expect(validateDrop("GridCell", kid, 4).ok).toBe(true);
    }
    // Except another cell: a cell inside a cell has no track of its own and
    // would make the row-major addressing ambiguous.
    expect(validateDrop("GridCell", "GridCell", 0).ok).toBe(false);
  });

  it("does NOT scaffold prop-region or prop-indexed layouts", () => {
    // AppShell takes sidebar/topbar/actions/rightRail as PROPS; Tabs renders
    // one panel per entry of its `tabs` PROP. Neither is an empty-children bug.
    expect(buildDroppedNode("AppShell", PARENT).children).toEqual([]);
    expect(buildDroppedNode("Tabs", PARENT).children).toEqual([]);
  });

  it("scaffolds a dropped Grid as a real 2x2 of cells", () => {
    // Grid used to be in the list above — an empty Grid dropped as an invisible
    // box with nothing to aim at, which is the complaint the fixed-grid feature
    // answers. It is scaffolded with GridCells rather than the Cards used for
    // Sidebar/Split panes because a cell must leave no trace in the shipped app.
    const node = buildDroppedNode("Grid", PARENT);
    expect(node.props.rows).toBe(2);
    expect(node.props.columns).toBe(2);
    expect(node.children).toHaveLength(4);
    expect(node.children!.every((c: any) => c.type === "GridCell")).toBe(true);
    expect(node.children!.every((c: any) => c.children.length === 0)).toBe(true);
    // Cells carry no style of their own — see the UNSIZED comment.
    expect(node.children!.every((c: any) => c.style === undefined)).toBe(true);
    // Unique ids, or validateForCommit rejects the whole insert silently.
    expect(new Set(node.children!.map((c: any) => c.id)).size).toBe(4);
  });

  it("still scaffolds the panes when the parent can't be measured (just unstyled)", () => {
    const node = buildDroppedNode("Sidebar", null);
    expect(node.children).toHaveLength(2);
    expect(node).not.toHaveProperty("style");
    expect((node.children as any[])[0]).not.toHaveProperty("style");
  });
});

// =============================================================================

/** A div with a known layout box, since jsdom never lays anything out. */
function stubBox(opts: {
  /** Post-transform (screen) size, i.e. what getBoundingClientRect returns. */
  rect: { width: number; height: number };
  /** Intrinsic CSS size, i.e. what offsetWidth/offsetHeight return. */
  offset: { width: number; height: number };
  padding?: number;
  border?: number;
}): HTMLElement {
  const el = document.createElement("div");
  const pad = opts.padding ?? 0;
  const bor = opts.border ?? 0;
  for (const side of ["Top", "Right", "Bottom", "Left"]) {
    (el.style as any)[`padding${side}`] = `${pad}px`;
    (el.style as any)[`border${side}Width`] = `${bor}px`;
    (el.style as any)[`border${side}Style`] = "solid";
  }
  Object.defineProperty(el, "offsetWidth", { value: opts.offset.width, configurable: true });
  Object.defineProperty(el, "offsetHeight", { value: opts.offset.height, configurable: true });
  el.getBoundingClientRect = () =>
    ({ width: opts.rect.width, height: opts.rect.height, top: 0, left: 0, right: 0, bottom: 0, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
  document.body.appendChild(el);
  return el;
}

describe("measureParentBox — zoom and the content box", () => {
  it("divides the canvas zoom back out of a screen-pixel rect", () => {
    // Canvas at 50%: the rect is half the intrinsic size. Storing the raw rect
    // would halve every dropped node, and the stored px would mean double once
    // the user zoomed back to 100%. Same convention as SelectionOverlay's
    // startResize: scale = rect.width / offsetWidth.
    const el = stubBox({ rect: { width: 600, height: 400 }, offset: { width: 1200, height: 800 } });
    expect(measureParentBox(el)).toEqual({ width: 1200, height: 800 });
  });

  it("is a no-op at 100% zoom", () => {
    const el = stubBox({ rect: { width: 1200, height: 800 }, offset: { width: 1200, height: 800 } });
    expect(measureParentBox(el)).toEqual({ width: 1200, height: 800 });
  });

  it("subtracts padding and border so the result is the CONTENT box", () => {
    const el = stubBox({
      rect: { width: 1200, height: 800 },
      offset: { width: 1200, height: 800 },
      padding: 24,
      border: 1,
    });
    expect(measureParentBox(el)).toEqual({ width: 1200 - 50, height: 800 - 50 });
  });

  it("zoom correction and the content box compose (50% zoom + padding)", () => {
    const el = stubBox({
      rect: { width: 600, height: 400 },
      offset: { width: 1200, height: 800 },
      padding: 16,
    });
    expect(measureParentBox(el)).toEqual({ width: 1168, height: 768 });
  });

  it("returns null for an element that isn't laid out", () => {
    const el = stubBox({ rect: { width: 0, height: 0 }, offset: { width: 0, height: 0 } });
    expect(measureParentBox(el)).toBeNull();
    expect(measureParentBox(null)).toBeNull();
  });

  it("walks through a display:contents wrapper to the real layout box", () => {
    // Every library component is wrapped in one by LibraryDispatcher; it
    // generates no box, so measuring it directly yields nothing usable.
    const wrapper = document.createElement("span");
    wrapper.style.display = "contents";
    document.body.appendChild(wrapper);
    const inner = stubBox({ rect: { width: 500, height: 300 }, offset: { width: 500, height: 300 } });
    wrapper.appendChild(inner);
    expect(measureParentBox(wrapper)).toEqual({ width: 500, height: 300 });
  });
});

// =============================================================================
describe("buildDroppedNode — the factory the palette drop actually calls", () => {
  it("attaches the derived style when a parent box is supplied", () => {
    const node = buildDroppedNode("Card", PARENT);
    expect(node.type).toBe("Card");
    expect(node.style).toEqual({ width: "100%", maxWidth: "420px", minHeight: "263px" });
    expect(node.children).toEqual([]);
  });

  it("sizes a leaf too — Divider on the axis that means something", () => {
    const node = buildDroppedNode("Divider", PARENT);
    expect(node.style).toEqual({ width: "100%", maxWidth: "1200px" });
    expect(node).not.toHaveProperty("children");
  });

  it("omits style entirely when the parent could not be measured", () => {
    expect(buildDroppedNode("Card", null)).not.toHaveProperty("style");
    // Back-compat: the old one-arg call site keeps the pre-fix behaviour.
    expect(buildDroppedNode("Card")).not.toHaveProperty("style");
    expect(buildDroppedNode("Divider", null)).not.toHaveProperty("style");
  });

  it("leaves an explicitly-excluded type alone even with a measured parent", () => {
    expect(buildDroppedNode("Checkbox", PARENT)).not.toHaveProperty("style");
    expect(buildDroppedNode("Dialog", PARENT)).not.toHaveProperty("style");
  });
});
