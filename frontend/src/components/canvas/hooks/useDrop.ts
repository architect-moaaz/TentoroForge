"use client";
import * as React from "react";
import { starterRegistry } from "@forge/registry";
import { useEditorStore } from "@/lib/editor-store";
import { getDraggingComponent } from "@/lib/palette-drag";
import {
  GRID_CELL_TYPE,
  gridCells,
  gridColumns,
  isEmptyCell,
} from "@/lib/grid-cells";

function findNode(
  artifacts: any,
  nodeId: string,
): { pageId: string; node: any } | null {
  for (const [pageId, page] of Object.entries(
    artifacts?.pageSchemas ?? {},
  )) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      if (n.id === nodeId) return { pageId, node: n };
      if (Array.isArray(n.children)) stack.push(...n.children);
      if (n.slots && typeof n.slots === "object") {
        for (const arr of Object.values(n.slots) as any[]) {
          if (Array.isArray(arr)) stack.push(...arr);
        }
      }
    }
  }
  return null;
}

export function validateDrop(
  parentType: string,
  childType: string,
  /** Current child count of the parent — enables maxChildren / single caps. */
  childCount = 0,
): { ok: true } | { ok: false; reason: string } {
  const parent = (starterRegistry as any)[parentType];
  if (!parent)
    return { ok: false, reason: `parent ${parentType} not in registry` };
  const slots = parent.slots ?? {};
  if (slots.type === "leaf") {
    return { ok: false, reason: `${parentType} is a leaf — cannot accept children` };
  }
  // `single` slots hold exactly one child.
  if (slots.type === "single" && childCount >= 1) {
    return { ok: false, reason: `${parentType} accepts a single child` };
  }
  if (slots.type === "list") {
    if (slots.accepts) {
      // A `["*"]` accepts-list is a wildcard (e.g. Dialog) — take any child.
      const accepts: string[] = slots.accepts;
      if (!accepts.includes("*") && !accepts.includes(childType)) {
        return { ok: false, reason: `${parentType} does not accept ${childType}` };
      }
    }
    if (Array.isArray(slots.rejects) && slots.rejects.includes(childType)) {
      return { ok: false, reason: `${parentType} does not allow ${childType}` };
    }
    // Enforce the fixed-slot cap (Split/Sidebar are 2-panel by contract).
    // This DOES fire: `slots: { type: "list", maxChildren: 2 }` is declared on
    // both in packages/registry/src/starter.ts (and survives into dist/starter.js).
    // Don't be misled by dist/starter.json — scripts/export.mjs writes a
    // deliberately props-only snapshot for the Python layer, so `slots` is
    // absent there for EVERY component, Card and Grid included.
    if (typeof slots.maxChildren === "number" && childCount >= slots.maxChildren) {
      return { ok: false, reason: `${parentType} is full (max ${slots.maxChildren})` };
    }
  }
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Seed normalisation — the editor must not be able to write page JSON that its
// own PageV2 schema rejects.
// ---------------------------------------------------------------------------
//
// Registry `default` values are hand-authored, and two shapes of seed are
// invalid the moment they land in a page:
//
//   • A NUMERIC prop declared with STRING literals. `Heading.level` is
//     `type: "enum", options: ["1"…"6"], default: "2"`, while both consumers
//     type it as a number — `HeadingProps.level: z.number()` in the library and
//     `HeadingNode.props` (which is `.strict()`) in packages/schema. Every
//     palette-dropped Heading therefore carried `level: "2"` and failed
//     `PageV2.safeParse`, while the New-page template — writing `level: 1` —
//     produced a valid node for the same component on the same page.
//
//   • A URL-shaped prop seeded `""`. `Avatar.photoUrl` / `Avatar.src` are
//     `z.string().min(1).optional()`: *absent* is valid, `""` is present-and-
//     too-short. An empty URL is not "no image", it is an invalid image.
//
// COERCE AT WRITE TIME rather than editing the seeds. `buildDroppedNode` is the
// one boundary every palette drop passes through, so a fix here cannot be
// bypassed; the registry table, by contrast, is also read by the Python export
// (`scripts/export.mjs`) and by the properties panel, and the next hand-edit of
// a `default:` line would silently reintroduce the bug. Both rules key off the
// DESCRIPTOR — its declared type / control — never off a component name, so a
// numeric-string enum or an empty image seed added tomorrow is normalised the
// day it appears rather than needing a per-component patch.
const NUMERIC_LITERAL = /^-?\d+(?:\.\d+)?$/;

/** A descriptor whose value domain is numeric, however it spells its options. */
function isNumericDomain(d: any): boolean {
  if (d?.type === "number") return true;
  return (
    d?.type === "enum" &&
    Array.isArray(d.options) &&
    d.options.length > 0 &&
    d.options.every(
      (o: unknown) =>
        typeof o === "number" ||
        (typeof o === "string" && NUMERIC_LITERAL.test(o)),
    )
  );
}

/** A descriptor holding a URL, for which the empty string is never a value. */
function isUrlDescriptor(d: any): boolean {
  return d?.control === "image" && d?.imageShape === "url";
}

/**
 * Normalise one registry seed to the type/shape the page schema declares.
 * Returning `undefined` means "omit this prop" — the correct outcome for an
 * optional prop whose only candidate value is invalid.
 */
export function normalizeSeed(descriptor: any, value: unknown): unknown {
  if (value === undefined) return undefined;
  if (
    isNumericDomain(descriptor) &&
    typeof value === "string" &&
    NUMERIC_LITERAL.test(value.trim())
  ) {
    return Number(value);
  }
  if (isUrlDescriptor(descriptor) && value === "") return undefined;
  return value;
}

export function defaultPropsFor(componentName: string): Record<string, unknown> {
  const entry = (starterRegistry as any)[componentName];
  if (!entry) return {};
  return Object.fromEntries(
    Object.entries(entry.props as Record<string, any>)
      .map(([n, d]) => [n, normalizeSeed(d, d.default)] as [string, unknown])
      .filter(([, v]) => v !== undefined),
  );
}

export function generateNodeId(componentName: string): string {
  const slug = componentName.toLowerCase();
  const rand = Math.random().toString(36).slice(2, 8);
  return `${slug}-${rand}`;
}

// ---------------------------------------------------------------------------
// Initial size for a dropped node
// ---------------------------------------------------------------------------
//
// The failure this exists to fix: a dropped node carried NO `style`, so an
// empty container rendered at its CSS default — `width: auto` inside a flex
// column (= the parent's full width) and `height: auto` with no content
// (= padding only). Dropping a Card therefore produced a full-bleed hairline
// strip that reads as a broken render, not a card. Giving the new node a
// measured, parent-relative `style` at drop time is what makes it arrive
// looking like the thing the user dragged.
//
// Sizes are RAW CSS strings ("420px") — the same shape the Style panel's
// SizeField writes, and what applyStyleSlot / resolveStyle / LibraryDispatcher's
// sizingFromStyle all emit verbatim.

/** A parent's CONTENT box in intrinsic CSS px (zoom already divided out). */
export interface ParentBox {
  width: number;
  /** 0 when the parent is height:auto and currently empty — treat as unknown. */
  height: number;
}

function clamp(v: number, lo: number, hi: number): number {
  // hi wins when the range inverts (lo > hi), which is how "never wider than
  // the parent" beats "at least this wide" in a very narrow container.
  return Math.min(Math.max(v, lo), hi);
}

/** Fraction of the parent's content WIDTH, with absolute px guard rails. */
interface WidthRule { frac: number; min: number; max: number }
/**
 * minHeight as a fraction of the parent's content HEIGHT. `fromWidth` is the
 * fallback fraction of the parent's WIDTH used when the parent measures 0 tall —
 * i.e. the parent is itself an empty auto-height container, which is exactly the
 * case on a fresh page, where its width is the only real signal available.
 */
interface HeightRule { frac: number; fromWidth: number; min: number; max: number }
/** minHeight derived from the node's OWN resolved width (card proportions). */
interface AspectRule { ratio: number; min: number; max: number }

/**
 * A per-type shape. An axis that is omitted is deliberately left alone —
 * "size the axis that is meaningful for this type" rather than forcing both.
 */
interface Shape { w?: WidthRule; h?: HeightRule; aspect?: AspectRule }

// --- The nine shapes -------------------------------------------------------
//
// Every one of them is a PROPORTION of the measured parent, never a constant;
// the min/max pairs are only guard rails so a 4000px-wide canvas or a 90px rail
// still yields something usable.

/** Layout regions + full-width blocks: span the parent, get a real height floor. */
const REGION: Shape = { w: { frac: 1, min: 120, max: Infinity }, h: { frac: 0.25, fromWidth: 0.15, min: 96, max: 320 } };
/** Data-heavy surfaces that are useless when short — a 96px Chart shows nothing. */
const PANEL: Shape = { w: { frac: 1, min: 200, max: Infinity }, h: { frac: 0.45, fromWidth: 0.28, min: 200, max: 520 } };
/**
 * A discrete card sitting ON the page. 0.42 lands two across a wide container
 * with room for a gap, and reads unmistakably as a card rather than the
 * full-bleed band that was the original bug report. 1.6 is the wider-than-tall
 * proportion a card is expected to have.
 */
const SURFACE: Shape = { w: { frac: 0.42, min: 240, max: 420 }, aspect: { ratio: 1.6, min: 120, max: 280 } };
/** Thin full-width strips — toolbars, alerts, progress, sparklines. */
const BAND: Shape = { w: { frac: 1, min: 120, max: Infinity }, h: { frac: 0.06, fromWidth: 0.035, min: 24, max: 72 } };
/**
 * Divider. Width is proportional; height deliberately is NOT — a hairline's
 * thinness is the component's whole identity, and a proportional height would
 * turn a rule into a filled bar.
 */
const RULE: Shape = { w: { frac: 1, min: 120, max: Infinity } };
/**
 * A form control. Width is proportional (a text input stretched across a
 * 1200px container is unusable, ~60% capped at 520 reads deliberate); height is
 * not, because a control's height is a fixed design constant — a 200px-tall
 * <select> is a broken select, not a big one.
 */
const FIELD: Shape = { w: { frac: 0.6, min: 180, max: 520 } };
/** Same width contract, but these ARE boxes and collapse without a floor. */
const FIELD_BOX: Shape = { w: { frac: 0.6, min: 180, max: 520 }, h: { frac: 0.18, fromWidth: 0.1, min: 96, max: 240 } };
/** A button. Proportional width, intrinsic height (same constant-height logic). */
const ACTION: Shape = { w: { frac: 0.16, min: 96, max: 220 } };
/** Prose. A measure, not a full bleed — 70% capped at 720px is a readable line. */
const TEXT: Shape = { w: { frac: 0.7, min: 240, max: 720 } };

function shapes(shape: Shape, names: string[]): Record<string, Shape> {
  return Object.fromEntries(names.map((n) => [n, shape]));
}

/**
 * The per-type proportion table. Every registry component appears here or in
 * UNSIZED — see the drop-sizing test, which fails if any type falls through.
 */
const SHAPE_BY_NAME: Record<string, Shape> = {
  ...shapes(REGION, [
    // Layout primitives — spanning the parent IS their contract, so the width
    // fraction is 1; the height floor is what makes a freshly-dropped empty one
    // visible and clickable (SelectionOverlay's own comment notes that a 0x0
    // empty Stack/Row/Grid is "invisible AND permanently unclickable").
    "Container", "Grid", "Stack", "Row", "Section", "Cluster", "Hero", "Form",
    "Sidebar", "Split", "SplitView", "AppShell", "Tabs", "TabPanel",
    "TabPanelWithDeepLink",
    // Full-width list/text blocks.
    "KeyValueList", "DescriptionList", "List", "ValidationChecklist", "CodeBlock",
    "EmptyState", "EmptyStateRich", "IllustratedEmpty", "LoadingState",
    "KeyboardShortcuts", "Wizard", "FilterBuilder",
  ]),
  ...shapes(PANEL, [
    "Table", "TableSortable", "DataGrid", "EditableLineGrid", "Chart",
    "Timeline", "ResourceTimeline", "Kanban", "Tree", "Heatmap", "Schematic",
    "ActivityFeed", "SearchResults", "Carousel", "CartPanel", "CartPage",
    "Transfer", "Calendar", "RichTextEditor",
    // Camera/scanner viewports are unreadable at band height.
    "BarcodeScanner", "CameraCapture", "Scanner",
  ]),
  ...shapes(SURFACE, [
    "Card", "MetricTile", "PersonCard", "FeatureCard", "Stat", "Gauge", "SplitArc",
  ]),
  ...shapes(BAND, [
    "Spacer", "Sparkline", "Alert", "Banner", "Progress", "Skeleton",
    "Stepper", "ApprovalStepper", "FilterBar", "BulkActionBar",
    "Breadcrumb", "Menubar",
  ]),
  ...shapes(RULE, ["Divider"]),
  ...shapes(FIELD, [
    "Input", "Select", "NumberInput", "MoneyInput", "Slider", "Combobox",
    "MultiSelect", "Cascader", "MaskedInput", "SegmentedControl",
    "DatePicker", "DateRangePicker", "TimePicker", "ColorPicker",
    "SearchInput", "GlobalSearch", "SavedViewsPicker",
  ]),
  ...shapes(FIELD_BOX, ["Textarea", "FileUpload", "KeyValueInput"]),
  ...shapes(ACTION, ["Button", "AddToCart"]),
  ...shapes(TEXT, ["Heading"]),
};

/**
 * The only types that deliberately get NO size, in four justified groups.
 * Every other component in the registry is sized against its parent.
 */
const UNSIZED = new Set([
  // 1. Anchored / viewport overlays. They do not lay out inside the parent at
  //    all — a Dialog is centred on the viewport, a Popover is anchored to a
  //    trigger, an InspectorPanel is `position: fixed` and in fact returns null
  //    entirely until its URL param is set. The parent's box is simply the
  //    wrong reference frame.
  "Dialog", "Drawer", "Popover", "Tooltip", "HoverCard", "Lightbox",
  "CommandPalette", "DropdownMenu", "ContextMenu", "TourOverlay",
  "UndoManager", "InspectorPanel",
  // 2. Zero-box wrappers. Control flow, animation, focus. They render their
  //    children (or nothing) and generate no box of their own, so a size here
  //    silently constrains content the user cannot see.
  "Repeat", "Conditional", "DataBoundary", "Slot", "FadeIn", "Stagger",
  "OptimisticProvider", "FocusTrap", "FocusRing", "AutoFocus", "Redirect",
  // 3. Intrinsically-sized controls. Their size is a design constant (a square
  //    icon button, a 16px switch, a fixed-count OTP, a circular avatar or
  //    spinner) or is dictated entirely by their content (a RadioGroup is as
  //    tall as it has options). A proportional width either distorts the control
  //    or wraps it in dead space, which also makes the selection outline lie
  //    about where the component actually is.
  //
  //    RadioGroup moved here out of FIELD_BOX: a 0.6-of-parent width plus a 96px
  //    minHeight floor is precisely the "they take the complete size, it should
  //    be exactly what is required" the user reported — the group has no options
  //    at drop time, so all 96px of that floor were empty. Leaving it unsized
  //    lets the component's own `w-fit` root (see library style/controlRow.ts)
  //    decide, which is the only thing that knows how many options there are.
  "Checkbox", "Switch", "RadioGroup", "IconButton", "Rating", "InputOTP",
  "ThemeToggle", "Spinner", "Avatar", "QRCode", "PresenceIndicator", "CartBadge",
  // 4. Inline text runs. They flow inside a line box with surrounding text; a
  //    block width breaks the line rather than sizing anything.
  "MoneyDisplay", "Badge", "Tag", "Link", "NavLink", "SkipLink",
  // 5. Grid-track residents. A GridCell's box IS its track: the column comes
  //    from the parent's `grid-cols-N` (which changes at every breakpoint) and
  //    the row height from the tallest cell in the row. A px width here would
  //    be wrong at every viewport except the one it was measured at, and it
  //    would fight the very responsive ladder the fixed-grid design preserves.
  //    Cells are never dragged from the palette anyway — the editor creates
  //    them — so this is belt-and-braces.
  "GridCell",
]);

/**
 * Choose the initial `style` for a node of `componentName` dropped into a
 * parent measuring `parent`. Pure — exported for unit tests.
 *
 * Returns `null` (emit no style, i.e. the pre-fix behaviour) only when sizing
 * would be a guess rather than a derivation: the parent could not be measured,
 * the type is in UNSIZED, or the type is not in the registry at all.
 */
export function deriveDropStyle(
  componentName: string,
  parent: ParentBox | null,
): { width?: string; maxWidth?: string; minHeight?: string } | null {
  if (!parent || !(parent.width > 0)) return null;
  if (!(starterRegistry as any)[componentName]) return null;
  if (UNSIZED.has(componentName)) return null;
  // A component absent from the table (a newly-added registry entry) gets
  // REGION: full parent width plus a height floor is the safe generalisation,
  // and it is never "no size at all".
  return shapeStyle(SHAPE_BY_NAME[componentName] ?? REGION, parent);
}

/** Apply a Shape to a measured parent box. Raw CSS px strings, SizeValue-valid. */
function shapeStyle(
  shape: Shape,
  parent: ParentBox,
): { width?: string; maxWidth?: string; minHeight?: string } {
  const pw = parent.width;
  const ph = parent.height > 0 ? parent.height : 0;
  const out: { width?: string; maxWidth?: string; minHeight?: string } = {};

  let width = 0;
  if (shape.w) {
    // Never wider than the parent's content box: the upper clamp is the
    // parent's own width, so a 240px-minimum card dropped into a 90px rail
    // shrinks to fit instead of overflowing it.
    width = clamp(
      Math.round(pw * shape.w.frac),
      shape.w.min,
      Math.min(shape.w.max, Math.floor(pw)),
    );
    // A CEILING, NOT A FIXED WIDTH.
    //
    // `width: 604px` froze every node at whatever the parent measured the moment
    // it was dropped, and `max-width: 100%` could not rescue it because the
    // PARENT was px-fixed too — 100% of 668px is 668px, so 604px still fit and
    // nothing reflowed. Switching the canvas to the phone frame (375px) left the
    // container at 668px and the grid at 604px with 294px columns, overflowing by
    // 229px: the device buttons changed the frame and not one thing inside it
    // moved.
    //
    // `max-width` in px with `width: 100%` keeps exactly the look the fixed width
    // gave — a Card dropped into a 1150px page is still 420px wide, because 420
    // is the ceiling and there is room for it — while letting the node shrink
    // with its parent when there is not. That is what "match the dimensions of
    // the parent" has to mean for a layout that is still responsive.
    out.width = "100%";
    out.maxWidth = `${width}px`;
  }

  const basis = shape.aspect
    ? width / shape.aspect.ratio
    : shape.h
      ? (ph > 0 ? ph * shape.h.frac : pw * shape.h.fromWidth)
      : null;
  if (basis !== null) {
    const bounds = shape.aspect ?? shape.h!;
    let minHeight = clamp(Math.round(basis), bounds.min, bounds.max);
    if (ph > 0) minHeight = Math.min(minHeight, Math.floor(ph));
    // `minHeight`, not `height`: a hard height looks identical while the node is
    // empty but starts clipping (Card carries `overflow-hidden`) or overflowing
    // its own border the moment the user drops a Heading + Text inside. A floor
    // gives the same immediate shape and then gets out of the way. Dragging a
    // SelectionOverlay resize handle still writes a hard `height`, which wins.
    out.minHeight = `${minHeight}px`;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Fixed-pane scaffolding
// ---------------------------------------------------------------------------
//
// A second reported failure: dropping a Sidebar produced "a single solid block"
// with no visible two-column layout. Sidebar.tsx maps over its children —
// `React.Children.map(children, (child, i) => <div data-sidebar-pane=…>)` — so
// `children: []` yields ZERO panes and an empty grid. The two-column CSS is
// correct; it simply has nothing to lay out. Split (`{children}` into a
// `grid-template-columns: 1fr 2fr`) and SplitView (`kids[0]` / `kids[1]`) have
// the same positional two-child contract, verified by reading their sources.
//
// NOT in this class, also verified by reading the sources:
//  - AppShell takes `sidebar`/`topbar`/`actions`/`rightRail` as PROPS, not
//    positional children, and renders `min-h-screen` regardless — nothing to
//    scaffold from a children array.
//  - Tabs renders one panel per entry of its `tabs` PROP (`tabs.map(…)`,
//    `panels[i]`), so adding TabPanel children to a Tabs whose `tabs` prop is
//    still the registry default (null) renders nothing extra. That is a props
//    problem, not an empty-children problem.
const FIXED_PANE_COUNT: Record<string, number> = {
  Sidebar: 2,
  Split: 2,
  SplitView: 2,
};

/**
 * What goes IN a scaffolded pane. Card rather than a bare Stack: two empty
 * Stacks are just as invisible as the empty Sidebar we are fixing, and the
 * complaint was specifically that the two sides could not be SEEN. A Card has
 * its own border and background, is a first-class droppable container so the
 * user keeps building inside it, and is one keystroke to delete.
 */
const PANE_COMPONENT = "Card";

/**
 * Panes are sized on HEIGHT ONLY. Their width is dictated by the parent
 * layout's own responsive grid track (Sidebar is `1fr` below 768px and
 * `<width> 1fr` at md+), so pinning a px width here would fight the very
 * layout the component exists to provide.
 */
const PANE_SHAPE: Shape = { h: REGION.h };

function scaffoldPanes(componentName: string, parent: ParentBox | null): unknown[] | null {
  const count = FIXED_PANE_COUNT[componentName];
  if (!count) return null;
  const style = parent && parent.width > 0 ? shapeStyle(PANE_SHAPE, parent) : null;
  return Array.from({ length: count }, () => ({
    id: generateNodeId(PANE_COMPONENT),
    type: PANE_COMPONENT,
    props: defaultPropsFor(PANE_COMPONENT),
    children: [] as unknown[],
    ...(style && Object.keys(style).length ? { style } : {}),
  }));
}

/** A brand-new, empty cell of a fixed grid. */
export function makeGridCellNode(children: unknown[] = []): any {
  return {
    id: generateNodeId(GRID_CELL_TYPE),
    type: GRID_CELL_TYPE,
    props: {},
    children,
  };
}

/**
 * The row count a Grid dropped from the palette starts life with.
 *
 * The registry default for `rows` is 0 ("auto"), deliberately, so that the
 * thousands of Grid nodes in existing schemas keep flowing their children as
 * they always have. But an auto Grid drops onto the canvas as an empty box with
 * nothing to aim at, which is the complaint this whole feature answers. So the
 * palette drop overrides it: a fresh Grid arrives as a real 2x2 with four
 * addressable, guide-outlined cells you can immediately drop into.
 */
const DROPPED_GRID_ROWS = 2;

/**
 * Walk through any `display:contents` wrapper (the LibraryDispatcher wraps every
 * library component in one) to the element that actually generates a layout box.
 * A contents element has no box, so measuring it yields nothing usable.
 * Mirrors SelectionOverlay's resolveBoxEl.
 */
function resolveLayoutBox(el: HTMLElement | null): HTMLElement | null {
  if (!el) return null;
  if (typeof getComputedStyle !== "function") return el;
  if (getComputedStyle(el).display !== "contents") return el;
  for (const child of Array.from(el.children) as HTMLElement[]) {
    const inner = resolveLayoutBox(child);
    if (inner) return inner;
  }
  return null;
}

/**
 * Measure a parent element's CONTENT box in intrinsic CSS px.
 *
 * Zoom: the canvas frame scales via a CSS transform, so getBoundingClientRect()
 * returns SCREEN px — at the 50% zoom step every dropped node would be sized to
 * half its logical size and the stored "420px" would mean 840px once zoomed back
 * to 100%. We divide it back out using the same convention SelectionOverlay's
 * startResize uses (scale = rect.width / offsetWidth, taken from the element
 * itself), so both call sites agree on what "canvas px" means and neither has to
 * know the zoom state exists.
 *
 * Returns null when the element cannot be measured — offsetWidth of 0 means
 * either not laid out or not a box we can trust, and a wrong absolute size is
 * worse than today's no-size behaviour.
 */
export function measureParentBox(el: HTMLElement | null): ParentBox | null {
  const box = resolveLayoutBox(el);
  if (!box) return null;
  const offW = box.offsetWidth;
  const offH = box.offsetHeight;
  if (!(offW > 0)) return null;
  const rect = box.getBoundingClientRect();
  if (!(rect.width > 0)) return null;
  const scaleX = rect.width / offW;
  const scaleY = offH > 0 ? rect.height / offH : 1;
  const cs = getComputedStyle(box);
  const px = (v: string) => {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : 0;
  };
  // Border box → content box. A dropped child lives inside the padding, so
  // "not wider than the parent" has to mean the parent's CONTENT width.
  // Approximate for components that pad on an INNER element rather than the
  // root (Card puts p-4/sm:p-6 on its `data-slot="body"`): we over-report by
  // that inner padding. It only loosens the "never wider than the parent"
  // clamp by a few dozen px, which the width fraction absorbs — not worth
  // hard-coding per-component slot knowledge here.
  const insetX = px(cs.paddingLeft) + px(cs.paddingRight)
    + px(cs.borderLeftWidth) + px(cs.borderRightWidth);
  const insetY = px(cs.paddingTop) + px(cs.paddingBottom)
    + px(cs.borderTopWidth) + px(cs.borderBottomWidth);
  return {
    width: Math.max(0, rect.width / (scaleX || 1) - insetX),
    height: Math.max(0, rect.height / (scaleY || 1) - insetY),
  };
}

/**
 * The single source of truth for a freshly-dropped node. Materialises the
 * registry's default props, gives containers a children array so the canvas can
 * accept nested drops immediately — pre-filled with the required panes for the
 * fixed-pane layouts — and, when the drop target could be measured, an initial
 * `style` derived from that parent's box. Exported so tests can exercise the
 * exact factory the palette drop uses (no drifting copy).
 */
export function buildDroppedNode(
  componentName: string,
  parent?: ParentBox | null,
): {
  id: string;
  type: string;
  props: Record<string, unknown>;
  children?: unknown[];
  style?: Record<string, string>;
} {
  const isContainer =
    (starterRegistry as any)[componentName]?.slots?.type !== "leaf";
  const id = generateNodeId(componentName);
  const style = deriveDropStyle(componentName, parent ?? null);
  const props = defaultPropsFor(componentName);
  // A FORM FIELD MUST ARRIVE WITH A `name`.
  //
  // Every input schema declares `name: z.string().min(1)` — required — and the
  // Properties panel exposed no control for it, so every input dropped from the
  // palette was invalid against its own schema the instant it landed. It
  // committed anyway, because `validateForCommit` checks only id uniqueness and
  // component-type closure and never runs the Zod prop shapes. Measured across
  // all eight core inputs: not one carried a `name`.
  //
  // Seeded from the id suffix rather than the label, so two "Email" fields on one
  // page do not collide and a rename in the panel is never fought by this. The
  // panel now exposes `name` too — this is the default, not a lock.
  if ("name" in ((starterRegistry as any)[componentName]?.props ?? {}) && !props.name) {
    props.name = id.replace(/-/g, "_");
  }
  let panes = scaffoldPanes(componentName, parent ?? null);
  if (componentName === "Grid") {
    // Same class of failure as the empty Sidebar above — the layout CSS is
    // correct and there is simply nothing to lay out — but fixed with cells
    // rather than Cards, because a cell must leave no trace in the shipped app.
    props.rows = DROPPED_GRID_ROWS;
    const cols = gridColumns({ id: "", type: "Grid", props });
    panes = Array.from({ length: DROPPED_GRID_ROWS * cols }, () => makeGridCellNode());
  }
  return {
    id,
    type: componentName,
    props,
    ...(isContainer ? { children: panes ?? [] } : {}),
    ...(style ? { style } : {}),
  };
}

/** Every node id currently in the tree (children + slots, all pages). */
function collectNodeIds(artifacts: any): Set<string> {
  const ids = new Set<string>();
  for (const page of Object.values(artifacts?.pageSchemas ?? {})) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      if (n.id) ids.add(n.id);
      if (Array.isArray(n.children)) stack.push(...n.children);
      if (n.slots) for (const arr of Object.values(n.slots) as any[]) if (Array.isArray(arr)) stack.push(...arr);
    }
  }
  return ids;
}

/**
 * Resolve the nearest ancestor of `targetEl` that ACCEPTS the component
 * (honoring accepts/rejects/maxChildren), falling back to a page root that
 * accepts it. Shared by onDragOver (so the indicator marks the real drop target,
 * not a leaf it would actually skip) and onDrop.
 *
 * Also returns the DOM element the chosen node was matched from, so onDrop can
 * measure the real parent box and size the new node against it. The root
 * fallback has no hovered element, so it is looked up by id instead.
 */
function resolveAcceptingParent(
  artifacts: any,
  componentName: string,
  targetEl: HTMLElement | null,
): { pageId: string; node: any; el: HTMLElement | null } | null {
  const chain: Array<{ id: string; el: HTMLElement }> = [];
  let el = targetEl?.closest("[data-node-id]") as HTMLElement | null;
  while (el) {
    const id = el.getAttribute("data-node-id");
    if (id && !chain.some((c) => c.id === id)) chain.push({ id, el });
    const parent = el.parentElement;
    el = parent ? (parent.closest("[data-node-id]") as HTMLElement | null) : null;
  }
  for (const { id, el: hitEl } of chain) {
    const hit = findNode(artifacts, id);
    if (!hit) continue;

    // AUTO-FILL. A fixed R x C Grid never takes a child directly: appending one
    // would make it R x C + 1 and silently grow the shape the user deliberately
    // chose. A drop that resolves to the grid itself (the gutters, the padding,
    // the outline) is redirected into the first empty cell in row-major order,
    // which is what makes "drop anything into each box" work without having to
    // hit a specific cell.
    //
    // A FULL grid does NOT gain a row — that was the explicit non-goal. It
    // stops accepting instead and the walk continues outwards, so the drop
    // lands in whatever contains the grid and the indicator says so. Aiming at
    // a specific cell still works either way: hovering a cell puts that
    // GridCell at the head of the chain, so it is matched below before the grid
    // is ever considered.
    const cells = gridCells(hit.node);
    if (cells) {
      const target = cells.find(isEmptyCell);
      if (target && validateDrop(GRID_CELL_TYPE, componentName, 0).ok) {
        const cellEl =
          hitEl.querySelector<HTMLElement>(`[data-node-id="${target.id}"]`) ?? hitEl;
        return { pageId: hit.pageId, node: target, el: cellEl };
      }
      continue;
    }

    if (validateDrop(hit.node.type, componentName, hit.node.children?.length ?? 0).ok) {
      return { ...hit, el: hitEl };
    }
  }
  for (const [pageId, page] of Object.entries(artifacts.pageSchemas ?? {})) {
    const root = (page as any).root;
    if (root && validateDrop(root.type, componentName, root.children?.length ?? 0).ok) {
      // `targetEl` is null on the click-to-insert path with nothing selected,
      // and `targetEl?.ownerDocument` then short-circuits to undefined — so the
      // root element was never found, `measureParentBox` got null, and the node
      // arrived with NO style at all. That is exactly the full-width hairline
      // this table exists to prevent, reintroduced through the door that has no
      // event to take a document from.
      const doc = targetEl?.ownerDocument ?? document;
      const rootEl = doc.querySelector<HTMLElement>(
        `[data-canvas-root] [data-node-id="${root.id}"]`,
      );
      return { pageId, node: root, el: rootEl };
    }
  }
  return null;
}

export function useCanvasDrop() {
  const dispatch = useEditorStore((s) => s.dispatch);
  const [hoverParent, setHoverParent] = React.useState<string | null>(null);

  const onDragOver = (e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes("text/x-forge-component")) return;
    e.preventDefault();
    const componentName = getDraggingComponent();
    const store = useEditorStore.getState();
    if (!componentName || !store.artifacts) {
      setHoverParent(null);
      e.dataTransfer.dropEffect = "copy";
      return;
    }
    // Highlight the REAL accepting target (or nothing → cursor shows no-drop),
    // instead of the innermost hovered node the drop would actually skip.
    const chosen = resolveAcceptingParent(store.artifacts, componentName, e.target as HTMLElement);
    setHoverParent(chosen ? chosen.node.id : null);
    e.dataTransfer.dropEffect = chosen ? "copy" : "none";
  };

  const onDragLeave = () => setHoverParent(null);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const componentName = e.dataTransfer.getData("text/x-forge-component");
    setHoverParent(null);
    if (!componentName) return;

    const store = useEditorStore.getState();
    if (!store.artifacts) return;

    const chosen = resolveAcceptingParent(store.artifacts, componentName, e.target as HTMLElement);
    if (!chosen) {
      // Surface the rejection instead of a silent console.warn.
      useEditorStore.setState({
        lastError: `${componentName} can't be placed here — no container on this page accepts it.`,
      });
      return;
    }

    // Size the new node against the parent it is actually landing in. Without
    // this the node arrived style-less and an empty Card rendered as a
    // full-width, padding-tall hairline — see deriveDropStyle. A parent that
    // can't be measured yields null and we fall back to no style at all.
    const parentBox = measureParentBox(chosen.el);
    const newNode = buildDroppedNode(componentName, parentBox);
    // Guarantee a unique id — a collision would make validateForCommit reject
    // the whole insert and the drop would silently vanish. Walks the whole
    // subtree, not just the root: a fixed-pane layout arrives carrying
    // scaffolded pane children whose ids can collide just as easily.
    const existing = collectNodeIds(store.artifacts);
    const ensureUniqueIds = (n: any) => {
      while (existing.has(n.id)) n.id = generateNodeId(n.type);
      existing.add(n.id);
      if (Array.isArray(n.children)) n.children.forEach(ensureUniqueIds);
    };
    ensureUniqueIds(newNode);

    const childIndex = chosen.node.children?.length ?? 0;
    dispatch({
      type: "insertNode",
      pageId: chosen.pageId,
      parentId: chosen.node.id,
      index: childIndex,
      node: newNode as any,
    });

    // Auto-select the new node so the user sees its props immediately
    store.setSelection(newNode.id);
  };

  return { onDragOver, onDragLeave, onDrop, hoverParent };
}

/**
 * Insert a palette component WITHOUT a drag gesture.
 *
 * The palette was drag-only: a `<li draggable>` with `onDragStart` and nothing
 * else. Clicking a component did nothing at all — confirmed live, the canvas was
 * unchanged after a click on `Grid`. That leaves anyone who cannot drag
 * comfortably (trackpad, touch, motor impairment, or an assistive device that
 * has no drag affordance at all) with no way to add a component to a page.
 *
 * Target is the current selection when it accepts the component — so clicking
 * builds *into* what you are working on, the same as dropping onto it — walking
 * up through ancestors that refuse it, and falling back to the page root. That
 * is deliberately the same resolution order `resolveAcceptingParent` uses for a
 * drop, so click and drag put the node in the same place.
 */
export function insertComponentByClick(componentName: string): boolean {
  const store = useEditorStore.getState();
  if (!store.artifacts) return false;

  // Start from the selected node's element so the DOM walk mirrors a drop onto
  // it; with nothing selected this is null and we fall through to the page root.
  const selectedEl = store.selectedNodeId
    ? document.querySelector<HTMLElement>(`[data-node-id="${store.selectedNodeId}"]`)
    : null;
  const chosen = resolveAcceptingParent(store.artifacts, componentName, selectedEl);
  if (!chosen) {
    useEditorStore.setState({
      lastError: `${componentName} can't be placed here — no container on this page accepts it.`,
    });
    return false;
  }

  const parentBox = measureParentBox(chosen.el);
  const newNode = buildDroppedNode(componentName, parentBox);
  const existing = collectNodeIds(store.artifacts);
  const ensureUniqueIds = (n: any) => {
    while (existing.has(n.id)) n.id = generateNodeId(n.type);
    existing.add(n.id);
    if (Array.isArray(n.children)) n.children.forEach(ensureUniqueIds);
  };
  ensureUniqueIds(newNode);

  store.dispatch({
    type: "insertNode",
    pageId: chosen.pageId,
    parentId: chosen.node.id,
    index: chosen.node.children?.length ?? 0,
    node: newNode as any,
  });
  // Only claim the selection if the insert actually committed — dispatch
  // refuses on a validation error and leaves `lastError` set.
  if (useEditorStore.getState().lastError) return false;
  store.setSelection(newNode.id);
  return true;
}
