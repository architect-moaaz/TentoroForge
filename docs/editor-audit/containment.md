# TentoroForge editor — CONTAINMENT + RENDER audit

**Date:** 2026-09-05 · **Branch:** `smithv2` · **Project under test:** `output/gh0mlpbp` (Inventory Manager)
**Method:** every probe node was built with the editor's real `buildDroppedNode()` from
`frontend/src/components/canvas/hooks/useDrop.ts` (bundled with esbuild and called directly, so the
probes carry the *exact* default props / scaffolded children / derived `style` a user gets when they
drag from the palette). Probe pages were written to `output/gh0mlpbp/src/schemas/zzprobe-*.json` and
rendered through the scaffold at `http://localhost:6503/p/gh0mlpbp/<probe>`; the returned SSR HTML was
searched for each child's `data-node-id`, plus `data-unknown-node` / `data-invalid-node`.

Registry source of truth: `packages/registry/dist/starter.js` → `starterRegistry`, **134 entries**,
133 of them in the palette (`GridCell` is `hidden: true` — editor-created only).

> ⚠️ Concurrency note: `packages/renderer/src/nodes/layout/Grid.tsx` (mtime moved **16:06 → 16:32**
> while this audit ran), `GridCell.tsx` (new, untracked), `packages/schema/src/nodes/layout.ts` and the
> canvas overlay files are being edited by another agent. Grid findings reflect the working tree at
> 2026-09-05 16:32 and may already be stale.

---

## Summary table

**1 736 (parent, child) pairs permitted by `validateDrop`; 1 571 render; 165 fail.**

| Parent | Pairs permitted | Rendered | Failed | Verdict |
|---|---:|---:|---:|---|
| `Container` | 133 | 129 | 4 | PARTIAL — only the 4 zero-box wrappers fail |
| `Grid` (fixed 2×2, children in cells) | 133 | 129 | 4 | PARTIAL — same 4; fixed shape is editor-only CSS |
| `Card` | 133 | 129 | 4 | PARTIAL — same 4 |
| `Stack` | 133 | 129 | 4 | PARTIAL — same 4 |
| `Row` | 133 | 129 | 4 | PARTIAL — same 4 |
| `Section` | 133 | 129 | 4 | PARTIAL — same 4 |
| `Cluster` | 133 | 129 | 4 | PARTIAL — same 4 |
| `Hero` | 133 | 129 | 4 | PARTIAL — same 4 |
| `TabPanel` | 133 | 129 | 4 | PARTIAL — same 4, but invisible unless it is `children[0]` of its Tabs |
| `Sidebar` | 133 | 129 | 4 | PARTIAL — renders at 0/1/2/3 children; drop cap unreachable after scaffold; 1-col < 768px |
| `Split` | 133 | 129 | 4 | PARTIAL — as `Sidebar`; 1-col below `breakpoint` |
| `AppShell` | 133 | 129 | 4 | PARTIAL as a body container — **FATAL** once any of its 4 props is set |
| `SplitView` | 133 | **16** | **117** | **FAIL** — renders `kids[0]` only; `kids[1]` needs `?selected=`; 3+ dropped silently |
| `Tabs` | 1 (`TabPanel`) | 1 | 0 | **PARTIAL** — the pair renders, but only ever the FIRST `TabPanel` |
| `Form` | 6 | 6 | 0 | PASS — but `accepts` refuses 127 components incl. every other form control |

Failure mode of the recurring "4": `Repeat`, `Conditional`, `DataBoundary`, `Slot` emit **no
`data-node-id` at all** in any parent. A further 10 components emit a node id but an empty box
(`InspectorPanel`, `Sparkline`, `DescriptionList`, `Dialog`, `CartBadge`, `BulkActionBar`,
`KeyboardShortcuts`, `UndoManager`, `PresenceIndicator`, `TourOverlay`) — so **14 of 133 palette
components (10.5%) produce nothing visible when dropped with their registry defaults.**

## Top 10 findings by severity

| # | Severity | Finding |
|---|---|---|
| 1 | **Critical** | Setting `AppShell.sidebar` / `topbar` / `actions` / `rightRail` from the Properties panel blanks the ENTIRE page — uncaught `Objects are not valid as a React child`, escapes `NodeErrorBoundary`, no DOM at all. The panel's only control for those props (`actionPicker`) writes exactly the value that triggers it. |
| 2 | **Critical** | `SplitView` accepts unlimited children but renders only `kids[0]`; `kids[1]` renders only when the URL has `?selected=`, which the editor never sets. 117 of 133 pairs fail. Silent content loss. |
| 3 | **High** | `Tabs` renders exactly ONE panel forever: `tabs` defaults to `null`, and `library/src/registry.ts:75` replaces it with a hard-coded single tab, also discarding the user's `value`. Panels 2..N and everything inside them vanish. |
| 4 | **High** | 14 of 133 palette components render nothing at all when dropped with default props — 4 with no DOM node whatsoever (unselectable on canvas). |
| 5 | **High** | 30 `actionPicker` props (incl. `Table.columns`, `DataGrid.columns`, `Form.fields`, `Chart.series`, `Tabs.tabs`) can only be given action objects. No raw-JSON escape hatch exists in `PropControls`. Tables authored in the editor can never get columns. |
| 6 | **Medium** | Vertical `Divider` is destroyed by its own drop-derived width: `resolveStyle(style)` is spread after the 1px width in `Divider.tsx`, so the hairline becomes a full-width grey slab. (Horizontal hairline survives — that part passes.) |
| 7 | **Medium** | `Form.accepts` lists 6 components, refusing `NumberInput`, `MoneyInput`, `DatePicker`, `RadioGroup`, `Combobox`, `MultiSelect`, `Switch`, `Slider`, `FileUpload` and every layout wrapper. A real form cannot be built inside `Form`. |
| 8 | **Medium** | `Sidebar`/`Split`/`AppShell`/`Grid` are single-column below 768px, so the two-column layout the user arranges is a vertical stack on phone/tablet. `Sidebar`'s 768px is hard-coded with no prop. |
| 9 | **Medium** | `Divider.thickness` is a live `select` in the Properties panel that the component does not accept — changing it does nothing. |
| 10 | **Low** | `maxChildren: 2` on `Sidebar`/`Split` is editor-only: the renderers happily lay out a 3rd child (both extra children get `data-sidebar-pane="main"`). And because `buildDroppedNode` scaffolds both panes with Cards, a freshly dropped `Sidebar` is already "full" and refuses all direct drops. |

---

## Findings

### Baseline matrix — 12 generic list-containers — PARTIAL (129 / 133 each)

`Container`, `Grid`, `Card`, `Stack`, `Row`, `Section`, `Cluster`, `Sidebar`, `Split`, `TabPanel`,
`AppShell`, `Hero` each accept all 133 palette components per `validateDrop`. Rendering every one of
them inside every one of those parents (probe pages `zzprobe-<parent>.json`, 17 parent instances x 8
children each) gives an identical result for all of them:

```
PARENT Container: expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
PARENT Grid:      expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
PARENT Card:      expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
PARENT Stack:     expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
PARENT Row:       expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
PARENT Section:   expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
PARENT Cluster:   expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
PARENT Sidebar:   expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
PARENT Split:     expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
PARENT TabPanel:  expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
PARENT AppShell:  expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
PARENT Hero:      expected 133, missing 4   MISSING: Repeat,Conditional,DataBoundary,Slot
```

No `data-unknown-node` and no `data-invalid-node` anywhere in ~1700 rendered pairs. Containment
itself is solid; every failure below is component-level, not container-level.

**Impact:** the generic container matrix is healthy. Four palette entries never produce a box (next
finding); the three fixed-pane / prop-driven parents are the real problem area.

### Repeat / Conditional / DataBoundary / Slot inside every parent — FAIL (invisible after drop)

Dropped exactly as `buildDroppedNode` makes them, these four emit **no `data-node-id` at all** across
all 1700 probe renders — nothing in the DOM, so nothing selectable on canvas either. They are in the
`UNSIZED` set in `useDrop.ts` (correctly — they are zero-box wrappers), so they also get no
`minHeight` floor to make them clickable while empty. `Slot` is worse than the other three: it is
declared `slots.type: "leaf"` in the registry, so `validateDrop` refuses **every** child — it can
never be given content from the canvas at all.

**Impact:** four palette tiles a user can drag onto the canvas and then never see, select, or fill.
`Repeat`/`Conditional`/`DataBoundary` become visible once they have children, but the only way to put
children into an invisible node is the layer tree.

### TabPanel inside Tabs — PARTIAL (only the FIRST panel ever renders)

The suspicion in the brief is **confirmed, with a twist**: it is not that nothing renders, it is that
*exactly one* panel renders no matter how many `TabPanel`s you drop.

`packages/registry/src/starter.ts` gives `Tabs.props.tabs` a default of `null`.
`packages/library/src/registry.ts:75` then rewrites the props before render:

```ts
Tabs: (p) => {
  if (Array.isArray((p as any).tabs)) return p;
  const v = typeof p.defaultValue === "string" ? p.defaultValue : "tab1";
  return { tabs: [{ id: v, label: "Tab" }], value: v };   // <- discards p.value too
},
```

and `Tabs.tsx` renders `tabs.map((t, i) => <div …>{panels[i]}</div>)`. One tab def => one panel.

Probe `zzprobe-tabsn` (T1 = 1 panel, T2 = 2, T3 = 3, T4 = 2 with a hand-written `tabs` array,
T5 = 2 with `value: "tab-1"`):

```
NODE IDS: T1, T1_p0, T1_p0_h,
          T2, T2_p0, T2_p0_h,                    <-- T2_p1 absent
          T3, T3_p0, T3_p0_h,                    <-- T3_p1, T3_p2 absent
          T4, T4_p0, T4_p0_h, T4_p1, T4_p1_h,    <-- both render
          T5, T5_p0, T5_p0_h                     <-- T5_p1 absent
tab buttons: [(tab1,true), (tab1,true), (tab1,true), (a,false), (b,true), (tab1,true)]
tab panels:  [(tab1,true), (tab1,true), (tab1,true), (a,false,hidden=""), (b,true), (tab1,true)]
```

T4 proves the container is fine — supply a real `tabs` array and every panel renders (the inactive
one carries `hidden=""`). T5 proves the remap also throws away a `value` the user typed into the
Properties panel: the node says `value: "tab-1"`, the rendered strip says `data-tab-id="tab1"`.

**Impact:** a user builds a 3-tab section, sees one tab labelled "Tab", and the second and third
panels plus everything inside them vanish from the render. The content is still in the schema, so it
looks like data loss without being data loss — and it is completely silent.

### Anything inside SplitView — FAIL for children 3+, PARTIAL for child 2

`SplitView` is `slots: { type: "list" }` with **no `maxChildren`**, so `validateDrop` accepts an
unbounded number of children — but `SplitView.tsx` reads only `kids[0]` / `kids[1]`, and `kids[1]` is
rendered *only when the `?selected=` URL param is non-empty*:

```tsx
const kids = React.Children.toArray(children);
const masterNode = kids[0] ?? null;
const detailNode = kids[1] ?? null;
…
{selected ? (detailNode) : (<p …>{emptyText}</p>)}
```

Full matrix run (`zzprobe-splitview`, 17 instances x 8 children):

```
PARENT SplitView: expected 133, missing 117
```

16 of 133 rendered — one per parent instance. The 0/1/2/3-children probe (`zzprobe-panes`) isolates
it:

```
SplitView0                       (no children)
SplitView1, SplitView1_k0        (1 of 1 renders)
SplitView2, SplitView2_k0        (k1 MISSING - detail pane suppressed)
SplitView3, SplitView3_k0        (k1, k2 MISSING)
```

**Impact:** the highest-loss container in the editor. Drop three things into a SplitView and two of
them disappear with no warning, no cap in the palette and no indicator; the second one is invisible
until the preview URL carries a selection param the editor never sets.

### Sidebar / Split at 0, 1, 2, 3 children — PASS (render) but the drop cap is unreachable

`packages/registry/src/starter.ts:1307,1372` declares `slots: { type: "list", maxChildren: 2 }` on
both. Rendering is faithful at every count — `zzprobe-panes` shows every child present:

```
Sidebar0 | Sidebar1 + _k0 | Sidebar2 + _k0,_k1 | Sidebar3 + _k0,_k1,_k2
Split0   | Split1   + _k0 | Split2   + _k0,_k1 | Split3   + _k0,_k1,_k2
```

A 3rd child is *not* rejected by the renderer — `Sidebar` maps every child into a
`[data-sidebar-pane]` (`i === 0 ? "aside" : "main"`, so children 2 and 3 are **both** labelled
`main`) and it lands in an implicit third grid row. `Split` passes `{children}` straight into a
2-track grid, so a 3rd child wraps to row 2. The cap is therefore editor-only, and any other writer
(JSON edit, LLM patch, projection) silently produces a 3-pane "two-pane" layout.

The editor-side wrinkle is the opposite one: `buildDroppedNode` **pre-fills both panes with Cards**
(`scaffoldPanes`, `FIXED_PANE_COUNT = { Sidebar: 2, Split: 2, SplitView: 2 }`), so a freshly dropped
Sidebar/Split already has `children.length === 2` and `validateDrop(…, 2)` returns
`"Sidebar is full (max 2)"` for *every* subsequent drop. `resolveAcceptingParent` then walks outward.
In practice drops land inside the scaffold Cards (the hovered element is the Card, which heads the
ancestor chain), which is the intended flow — but you can never put a non-Card directly in a pane
without first deleting the scaffold Card.

**Responsive behaviour, honestly reported at both widths.** Both are a single stacked column below
the breakpoint. Rendered CSS, verbatim from the probe:

```css
[data-sidebar-id="…"] { display:grid; grid-template-columns:1fr; gap:1.5rem; }
@media (min-width: 768px) { [data-sidebar-id="…"] { grid-template-columns: 240px 1fr; gap:2rem; } }

[data-split-id="…"] { grid-template-columns:1fr; min-width:0; }
@media (min-width: 768px) { [data-split-id="…"] { grid-template-columns: 1fr 1fr; } }
```

At a phone/tablet canvas width the "two-column layout" the user chose is a vertical stack; at >=768px
it is two columns. `Split.props.breakpoint` (sm/md/lg -> 640/768/1024) is settable from the panel;
`Sidebar`'s 768px is hard-coded with no prop, so a Sidebar can never be made to split earlier.

### Grid inside Container and Container inside Grid — PASS (both directions)

`zzprobe-cross`. All node ids present in the SSR DOM, no unknown/invalid markers:

```
Grid(2x2 cells) > cell0 > Container > Heading   ->  GC_grid, GC_grid_cell0, GC_container, GC_container_h  OK
Grid(rows:0, legacy) > Container > Heading      ->  GL_grid, GL_container, GL_container_h                 OK
Container > Grid(2x2) > 4 cells > Heading each  ->  CG_container, CG_grid, CG_grid_cell0..3 + _h          OK
Grid > cell0 > Grid(2x2) > 4 cells > Heading    ->  GG_outer, GG_outer_cell0, GG_inner, GG_inner_cell0..3 OK
Card > Grid(2x2) filled                         ->  CardG, CardG_grid, CardG_cell0..3 + _h                OK
Row  > Grid(2x2) filled                         ->  RowG,  RowG_grid,  RowG_cell0..3 + _h                 OK
```

**Impact:** none — both directions work, including grid-in-grid and a grid inside a flex Row.

### Deep nesting — PASS at 5 and at 8 levels

`zzprobe-deep`. `Container > Grid > GridCell > Card > Stack > Heading` (the requested 5-level chain,
6 counting the auto-created cell) and an 8-deep alternating
`Container/Stack/Card/Section/Cluster/Row/Hero` chain:

```
D_container, D_grid, D_cell0, D_card, D_stack, D_heading            <- the requested chain
D8_1_Stack, D8_2_Card, D8_3_Section, D8_4_Cluster, D8_5_Row,
D8_6_Hero, D8_7_Container, D8_leaf                                  <- 8 levels, leaf present
```

**Impact:** none — nesting depth is not a limit.
### AppShell — PASS as a plain container, FAIL the moment any of its four props is set

Three separate probes.

**(a) Plain / with children — PASS.** `zzprobe-as-plain`:

```
ids = ASP_empty, ASP_kids, ASP_kids_h1, ASP_kids_h2      (no invalid/unknown nodes)
```

Positional children land in `<main class="overflow-y-auto …"><div class="px-4 py-4 …">{children}</div></main>`,
and the full matrix (`zzprobe-appshell`) rendered 129 of 133 children inside it. So `AppShell` as a
plain body container works, and that is *all* a user can build with it from the canvas.

**(b) `sidebar` set to what the Properties panel actually writes — FAIL, whole page blanks.**
`AppShell.sidebar/topbar/actions/rightRail` are `control: "actionPicker"`, and `ActionPicker` can only
emit one of five action shapes (`frontend/src/components/properties/PropControls/ActionPicker.tsx:47`
`emptyForType`). Choosing "Navigate" writes `{action:"navigate", trigger:""}` into `sidebar`. Probe
`zzprobe-as-action` with exactly that value:

```
ids = []                       <-- nothing rendered at all, not even the page root
PAGE ERROR: Objects are not valid as a React child (found: object with keys {action, trigger}).
            If you meant to render a collection of children, use an array instead.
```

The error escapes `NodeErrorBoundary` (it is thrown while React renders the *child position*, above
the boundary) and takes the entire SSR document with it — `<body>` contains only
`<template data-next-error-message=…>`.

**(c) `sidebar` set to a schema sub-tree, which is what the registry description promises
("Schema sub-tree for the navigation sidebar") — FAIL, same whole-page blank.** `zzprobe-as-subtree`:

```
ids = []
PAGE ERROR: Objects are not valid as a React child (found: object with keys {id, type, props}).
```

`AppShell.tsx` types these as `React.ReactNode` and renders `{sidebar}` verbatim; nothing in
`dispatch.tsx` converts a schema sub-tree in a *prop* into rendered nodes. Only a plain string works
(`zzprobe-as-string` → `ids = AST, AST_body`, the string appears as text in the aside).

**Impact:** the highest-severity finding in this audit. Selecting any action in the AppShell property
panel — the only control the panel offers for those four props — blanks the entire preview/canvas
with an uncaught React error, and the schema is left in that state on disk. And the documented
feature (compose a sidebar/topbar sub-tree) is unreachable by any editor path.

### actionPicker values in the other 26 data props — PASS (defensive), but the prop is still dead

`zzprobe-actionprops` puts `{action:"navigate", trigger:""}` into 16 representative data props. All 16
components still render:

```
AP_Table_columns, AP_Chart_data, AP_Chart_series, AP_Sparkline_data, AP_DataGrid_columns,
AP_DataGrid_rows, AP_Timeline_entries, AP_Breadcrumb_items, AP_KeyValueList_items,
AP_MultiSelect_options, AP_ActivityFeed_entries, AP_CommandPalette_items, AP_Form_fields,
AP_Hero_ctas, AP_MetricTile_delta, AP_EmptyState_action
```

`validateProps`' step-3 coercion (`packages/library/src/registry.ts:335`, "any non-array where an
array is expected → `[]`") absorbs it. So these degrade to empty rather than crashing — the AppShell
four are uniquely fatal because they are `ReactNode` props with no Zod array to coerce against.

**Impact:** no crash, but 30 registry props (listed under *Feature gaps*) can be *changed* in the panel
and can never be given a correct value.

### 10 components render an EMPTY box with default props — FAIL (invisible on canvas)

Measured by scanning each `<span data-node-id="X__<parent>__<Child>" …>` in the matrix HTML for a body
that is immediately `</span>`. Identical set in `Container`, `Card` and `Stack` (124 dispatcher spans
each):

```
InspectorPanel, Sparkline, DescriptionList, Dialog, CartBadge,
BulkActionBar, KeyboardShortcuts, UndoManager, PresenceIndicator, TourOverlay
```

Their registry defaults explain each one:

```
Sparkline          {"data":null,…}          -> no series
DescriptionList    {"binding":null,…}       -> no rows
Dialog             {"id":"dialog",…}        -> closed; its CHILD does not render either
BulkActionBar      {"selectedCount":0,…}    -> hidden until a selection exists
KeyboardShortcuts  {"shortcuts":"",…}       -> nothing to list
TourOverlay        {"steps":"",…}           -> no steps
UndoManager        {…}                      -> nothing on the stack
InspectorPanel     {"paramKey":"inspector"}  -> position:fixed, returns null until ?inspector= is set
PresenceIndicator  {"route":"",…}           -> no room
CartBadge          {"href":"/cart",…}       -> hideZero/empty cart
```

The `Dialog` case is worth separating: `Dialog` is the one wildcard container
(`slots: { type:"list", accepts:["*"] }`), so `validateDrop` lets a user drop anything into it — and
`zzprobe-dialog` shows the dialog's child `DLG_h` is **absent from the DOM** while `DLG` itself is
present. Everything a user builds inside a Dialog is invisible on canvas.

**Impact:** 10 palette tiles that drop onto the canvas as nothing. Combined with the 4 zero-box
wrappers above, **14 of 133 palette components (10.5%) produce no visible output when dropped.**

### Divider — PARTIAL: horizontal hairline survives; vertical is destroyed; `thickness` is dead

`zzprobe-divider` renders a Divider inside each of Container/Card/Row/Stack/Cluster/Section/Hero, at
`thickness: thin` and `thick`, and at both orientations. All 21 have a `data-node-id`. The rendered
inline styles:

```html
<!-- horizontal, thin  (DIV_Container) -->
<hr role="separator" aria-orientation="horizontal" style="border:none;
    background-color:var(--token-neutral-200); width:900px;
    height:var(--token-spacing-px); display:block; margin:var(--token-spacing-2) 0; max-width:100%"/>

<!-- horizontal, THICK (DIVT_Container) — byte-identical height -->
<hr role="separator" aria-orientation="horizontal" style="… height:var(--token-spacing-px); …"/>

<!-- vertical (DIVV_Container) -->
<hr role="separator" aria-orientation="vertical" style="border:none;
    background-color:var(--token-neutral-200); width:900px;   <-- should be 1px
    height:100%; display:block; margin:0 var(--token-spacing-2); max-width:100%"/>
```

1. **Horizontal hairline: PASS.** The `RULE` shape in `useDrop.ts` deliberately sets only `width`, and
   `height: var(--token-spacing-px)` (1px) survives the derived width. Confirmed in all 7 parents.
2. **Vertical: FAIL.** `Divider.tsx` sets `width: var(--token-spacing-px)` for the vertical case, then
   spreads `...resolveStyle(style)` **after** it — so the drop-derived `width: 900px` overwrites the
   hairline dimension. A vertical divider renders as a 900px-wide, full-height filled slab. The `RULE`
   comment ("a hairline's thinness is the component's whole identity") is right, but it only guards
   the horizontal axis; `orientation` is not consulted by `deriveDropStyle`.
3. **`thickness` is a dead prop.** The registry declares
   `thickness: enum[thin|medium|thick], control: select` but `Divider.tsx`'s props are only
   `{ orientation, style }` — the value is dropped by `validateProps` and never reaches the DOM.
   Selecting "thick" in the panel changes nothing.

**Impact:** (1) is fine. (2) makes vertical dividers unusable from the palette — the user gets a grey
block, not a rule. (3) is a visible control in the Properties panel that does nothing.

### GridCell — PASS in every position, including the states the editor should never create

`zzprobe-gridcell`. `GridCell` is `hidden: true` (not in the palette) and `slots: { type:"list",
rejects:["GridCell"] }` — so it rejects only itself and `validateDrop` would accept a GridCell into
any container. All three degenerate states render every node:

```
Container > loose GridCell > Heading             -> GCEL_container, GCEL_loose, GCEL_loose_h        OK
Grid(rows2,cols2) with FIVE cells                -> GCEL_grid_c0..c3 + GCEL_grid_extra (+ headings) OK
Grid(rows2,cols2) with loose non-cell children   -> GCEL_mixed, GCEL_mixed_h0, GCEL_mixed_h1        OK
```

The 5th cell simply flows into an implicit 3rd row; `gridCells()` in `frontend/src/lib/grid-cells.ts`
returns a list longer than `rows*columns` and `planGridCells` treats that as "needs reconciling"
rather than lying about addressing — matching the documented intent.

**Impact:** none for rendering. Worth noting for the concurrent Grid-cells work: an over-long or mixed
cell list is *renderable*, so a reconcile bug would be silent rather than crashing.

### Dialog / Drawer / Popover — PARTIAL (present, but content invisible on canvas)

`zzprobe-dialog`: `DLG`, `DRW`, `POP` all emit `data-node-id`, but `Dialog`'s child `DLG_h` does not
appear. `Drawer`/`Popover` render only their trigger. These are in `useDrop.ts`'s `UNSIZED` set with
the correct justification ("a Dialog is centred on the viewport … the parent's box is simply the wrong
reference frame"), so they also get no size.

**Impact:** `Dialog` is the only wildcard container in the registry and the editor will happily let you
build a whole form inside it; none of it is visible until the dialog is opened at runtime.

### Form — PASS (6 of 6), but its accepts-list is the narrowest in the registry

`Form` is `slots: { type:"list", accepts:["Input","Textarea","Select","Checkbox","Button","Heading"] }`.

```
PARENT Form: expected 6, missing 0
```

All six render. But `validateDrop` therefore refuses `NumberInput`, `MoneyInput`, `DatePicker`,
`Combobox`, `MultiSelect`, `RadioGroup`, `Switch`, `Slider`, `FileUpload`, `Textarea`-adjacent controls,
`Row`/`Stack`/`Grid` (so a two-column form is impossible), `Alert`, `Divider` and `Card` — 127 of 133
components, including **every other form control in the library**.

**Impact:** the component named `Form` cannot contain a date field, a money field, a radio group, a
file upload, or any layout wrapper. Users must build forms in a `Stack`/`Grid` instead, which then
loses `Form.workflow` submission.

### Tabs / TabPanelWithDeepLink accepts-lists

`Tabs` accepts only `TabPanel` (correct). `TabPanelWithDeepLink` is `slots: { type:"list" }` with the
same `tabs` actionPicker prop as `Tabs`, so it inherits the same one-panel-only defect.
### Grid — PASS for containment; the fixed R x C shape is EDITOR-ONLY (mid-change, note the clock)

`packages/renderer/src/nodes/layout/Grid.tsx` mtime moved during this audit
(**2026-09-05 16:06 → 16:32**), and `GridCell.tsx` is new/untracked, so this is a snapshot of work in
progress by the concurrent agent. What the current tree renders:

```html
<div data-node-id="CG_grid" class="grid grid-cols-1 md:grid-cols-2 gap-4"
     style="width:1100px;max-width:100%;min-height:165px"
     data-grid-rows="2" data-grid-columns="2">
  <div data-node-id="CG_grid_cell0" data-grid-cell="" class="flex flex-col gap-2 min-w-0"> … </div>
```

Two things follow, both deliberate per the source comment but both worth saying out loud:

1. A fixed grid emits **no `grid-template-columns`** — only the inert `data-grid-rows` /
   `data-grid-columns` attributes. The fixed template lives in `frontend/src/app/globals.css:236+`
   scoped to `[data-canvas-root]`, which exists only in the editor. **In the scaffold preview (port
   6503) and in the generated app, a 2x2 grid is `grid-cols-1 md:grid-cols-2`** — one column below
   768px. So the shape the user arranges in the editor is not the shape the preview or the shipped app
   shows below `md`.
2. Containment through cells is sound in every probe: children in cells, cells in cells, grids in
   grids, and a grid whose cell list is longer than `rows*columns` all render (see the GridCell
   finding).

Also from `useDrop.ts:resolveAcceptingParent`: a **full** fixed grid stops accepting
(`cells.find(isEmptyCell)` → none → `continue`), so the drop walks outward and lands in the grid's
parent. Documented as an explicit non-goal ("a full grid stays full"), but from the user's seat a drop
aimed at a full 2x2 grid silently lands somewhere else.

---

## Feature gaps

Components in the palette that a user cannot actually use from the editor, with the concrete blocker.

| Component | Blocker |
|---|---|
| `AppShell` | Its four composition props (`sidebar`, `topbar`, `actions`, `rightRail`) are `React.ReactNode` but wired to `control: "actionPicker"`. The panel can only write an action object; that object is rendered as a React child and **blanks the whole page** with "Objects are not valid as a React child". A schema sub-tree — what the registry description promises — does the same. Only a plain string works. Usable only as a bare body container. |
| `Tabs`, `TabPanelWithDeepLink` | `tabs` defaults to `null` and is `actionPicker`. `packages/library/src/registry.ts:75` replaces it with a single hard-coded `[{id:"tab1",label:"Tab"}]`, so only `children[0]` renders and `props.value` is discarded. No panel control can author `[{id,label}]`. Multi-tab UI is impossible from the editor. |
| `SplitView` | Renders `kids[0]`/`kids[1]` only, and `kids[1]` only when the URL carries `?selected=<id>` — which the editor never sets. `slots` declares no `maxChildren`, so the editor lets you add any number and silently drops all but the first. |
| `Slot` | `slots.type: "leaf"` in the registry, so `validateDrop` refuses every child, and the component renders nothing without one. A slot that can never be filled. |
| `Repeat`, `Conditional`, `DataBoundary` | Zero-box wrappers with no `data-node-id` in the DOM when empty and no `minHeight` floor (they are in `UNSIZED`). Invisible and unclickable on canvas, so the only way to give them children is the layer tree. `Repeat`/`Conditional` additionally need a binding/predicate the palette drop does not create. |
| `Dialog` | The only `accepts: ["*"]` container, but renders nothing (closed) — its children are absent from the DOM. Anything built inside it is invisible on canvas. |
| `Drawer`, `Popover`, `Tooltip`, `HoverCard`, `ContextMenu`, `DropdownMenu`, `CommandPalette`, `Lightbox` | Anchored/viewport overlays. They render only a trigger (or nothing); the panel/menu body never appears on canvas. `CommandPalette` and `Lightbox` are `fixed inset-0 z-50` — when they *do* open they cover the whole canvas. |
| `InspectorPanel` | `position: fixed` + returns `null` until `?inspector=` is in the URL. Never appears on canvas at all (`slots.type: "list"`, so it also swallows any children dropped into it). |
| `TourOverlay`, `UndoManager` | Render nothing with default props (`steps: ""`, empty undo stack) and are `position: fixed` when active. Nothing to see or select after a drop. |
| `Sparkline`, `DescriptionList`, `KeyboardShortcuts` | Render empty with their defaults (`data: null`, `binding: null`, `shortcuts: ""`). `Sparkline.data` gets a binding picker (`data` ∈ `DATA_SOURCE_PROPS`); `KeyboardShortcuts.shortcuts` does not — it is a plain text field for what must be an array. |
| `BulkActionBar`, `PresenceIndicator`, `CartBadge` | Render nothing until runtime state exists (`selectedCount: 0`, empty `route`, empty cart). Not authorable, only observable in a running app. |
| `Divider` (vertical) | The drop-derived `width` overwrites the component's 1px vertical hairline (`resolveStyle(style)` is spread last in `Divider.tsx`), producing a full-width grey slab. |
| `Divider.thickness` | Declared as a `select` in the registry; `Divider.tsx` does not accept the prop. The control exists and does nothing. |
| `Form` | `accepts` is only `["Input","Textarea","Select","Checkbox","Button","Heading"]` — it refuses every other form control in the library (`NumberInput`, `MoneyInput`, `DatePicker`, `RadioGroup`, `Combobox`, `MultiSelect`, `Switch`, `Slider`, `FileUpload`, …) and every layout wrapper, so a multi-column or grouped form cannot be built inside a `Form`. |
| 30 `actionPicker` props | `Hero.ctas`, `Button.onClick`, `MetricTile.delta`, `MetricTile.trend`, `Tabs.tabs`, `Table.columns`, `EmptyState.action`, `Form.fields`, `Form.defaultValues`, `AppShell.sidebar`, `AppShell.topbar`, `AppShell.actions`, `AppShell.rightRail`, `TabPanelWithDeepLink.tabs`, `Chart.series`, `DataGrid.columns`, `DataGrid.rowActions`, `EditableLineGrid.columns`, `EditableLineGrid.totals`, `TableSortable.columns`, `TableSortable.onSort`, `ApprovalStepper.steps`, `FilterBar.chips`, `FilterBar.savedViews`, `EmptyStateRich.illustration`, `EmptyStateRich.primaryCta`, `EmptyStateRich.sampleDataLink`, `DateRangePicker.presets`, `MultiSelect.selected`, `FeatureCard.cta`. `ActionPicker` emits only `navigate` / `workflow` / `submitForm` / `openModal` objects and there is **no raw-JSON escape hatch** in `PropControls`. Only the six names in `DATA_SOURCE_PROPS` (`data`, `rows`, `options`, `items`, `entries`, `records`) get a binding picker instead. For the other 30, the panel can change the value but can never make it correct — `Table.columns` and `DataGrid.columns` mean every table in the editor is column-less unless the schema was written by the pipeline. |
| `Sidebar` breakpoint | `Sidebar`'s two-column split is hard-coded at `@media (min-width: 768px)` with no prop. `Split` at least exposes `breakpoint` (sm/md/lg). |
| `Text` primitive | `dispatch.tsx` renders a `Text` node type, but there is **no `Text` entry in the registry**, so the palette cannot create one. `Heading` is the only text primitive a user can drop. Same for `Box` and `Image` — handled by `dispatch.tsx`, absent from `starterRegistry`. |

---

## Probe hygiene

All 28 `output/gh0mlpbp/src/schemas/zzprobe-*.json` files created by this audit have been deleted.
`issueform.json` and `PAGE-001.json` were never written to (mtimes unchanged: 16:07 and 15:15).

Note for whoever reads this next: **131 `probe_palette_*.json` files appeared in that directory at
16:29 during this audit** and are NOT mine — another agent is writing them. They were left in place.

## How to reproduce

```bash
# 1. bundle the editor's real drop factory (pure functions only)
node_modules/.bin/esbuild frontend/src/components/canvas/hooks/useDrop.ts \
  --bundle --platform=node --format=cjs --tsconfig=frontend/tsconfig.json --outfile=useDrop.cjs

# 2. build probe pages from buildDroppedNode() into output/gh0mlpbp/src/schemas/
# 3. render and grep
curl -s -m 400 http://localhost:6503/p/gh0mlpbp/<probe> \
  | grep -o 'data-node-id="[^"]*"\|data-unknown-node="[^"]*"\|data-invalid-node="[^"]*"'
```

A page whose `<body>` contains only `<template data-next-error-message=…>` and no `<main>` is the
whole-page-crash signature (finding #1).
