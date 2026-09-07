# TentoroForge editor — audit fixes

Companion to `panels.md`, `containment.md`, `business-logic.md`. Each entry names the
finding it closes, the root cause actually found (which is not always the one the audit
guessed), the fix, and the evidence.

---

## Phase 0 fixes — crashes and data loss

### 1. `AppShell` composition props blanked the entire page — FIXED

**Finding:** `containment.md` #1. Setting `AppShell.sidebar` / `topbar` / `actions` /
`rightRail` from the Properties panel produced an uncaught
`Objects are not valid as a React child`, escaped `NodeErrorBoundary` and left `<body>`
holding only Next's error template.

**Root cause — two independent defects.**

*(a) The value reached React's child position at all.* `packages/schema/src/nodes/enterprise.ts:244-247`
types all four props as `NodeV2Ref` (a schema sub-tree) and the registry descriptions say the
same, but nothing ever converted a sub-tree into rendered nodes — `AppShell.tsx` does
`{sidebar}` verbatim. `validateProps` could not rescue it either: its step-3 coercion
(`packages/library/src/registry.ts:335`) has rules for "non-array where an array is expected"
but none for a `NodeV2` union mismatch, so a plain object survives verbatim. And the panel's
only control for those props was `actionPicker`, whose sole output *is* a plain object.

*(b) `NodeErrorBoundary` genuinely could not contain it.* Not because of where the throw
originates — because **`react-dom/server` (Fizz) never invokes `getDerivedStateFromError` /
`componentDidCatch` at all**. The only unit of error containment the server renderer
understands is a **Suspense** boundary. Verified directly against the React 19.2.4 in this
repo:

```
$ node zz_eb.mjs            # <EB> around a component rendering an object child
THREW: Objects are not valid as a React child (found: object with keys {action, trigger}).

$ node zz_eb2.mjs           # same tree, with a <Suspense> inside the boundary
staticMarkup: <div><span data-invalid-node="X">PLACEHOLDER</span><p>SIBLING SURVIVES</p></div>
```

**Fix.**
- `packages/renderer/src/runtime/dispatch.tsx` — new `NODE_SLOT_PROPS` map + `resolveNodeSlotProps()`.
  Props a component renders in child position (AppShell's four) are resolved before dispatch:
  a schema node (or array of them) is rendered through `renderNode` — **delivering the
  documented sub-tree feature for the first time** — strings/numbers pass through, and
  anything else becomes a labelled `⚠ AppShell.sidebar: not renderable` placeholder.
- `packages/renderer/src/nodes/library/NodeErrorBoundary.tsx` — children are wrapped in a
  `<Suspense>`, so a throw is confined to one node under SSR too. The fallback is
  deliberately **invisible**, not the error placeholder: Fizz uses the same fallback for
  "errored" and "still streaming", and `AppShell` *does* suspend under Next's streaming SSR
  (`<!--$?-->` + `<template id="B:n">`), so an error-styled fallback painted a red box on
  every healthy AppShell. A node that genuinely threw leaves a hole in the SSR HTML and React
  re-renders that boundary on the client, where the class boundary paints the labelled
  placeholder.
- `packages/registry/src/{types.ts,starter.ts}` — new `control: "json"`; the four AppShell
  slots use it instead of `actionPicker`.
- `frontend/src/components/properties/PropControls/index.tsx` — `JsonControl`: a raw-JSON
  editor that commits on blur and **only if the text parses** (an unparseable draft is shown
  as `Not saved — …` and never reaches the store). This is also the raw-JSON escape hatch
  `containment.md` #5 says does not exist.

**Evidence.** `packages/renderer/tests/node-containment.test.tsx` — 8 tests. Live render of
probe `zzp0-appshell` through the scaffold (`/p/gh0mlpbp/zzp0-appshell`, since deleted):

```
6 ACTIONOBJECTBODY            <- the shell with the action object still renders its body
6 PAGE RENDERED TOP           <- and the page around it survives
6 PAGE RENDERED BOTTOM
3 SUBTREESIDEBAR              <- a schema sub-tree in `sidebar` now RENDERS
3 PLAINSTRINGTOPBAR
1 data-invalid-node="AppShell.sidebar"
1 not renderable
0 next-error-message          <- no Next error template; page is 140 KB of real HTML
```

### 2. `addPage` overwrote an existing page and its undo deleted it — FIXED

**Finding:** `panels.md`, "PageGen — `addPage` overwrites an existing page and its undo
deletes it".

**Root cause.** `applyAction` `case "addPage"` (`packages/patches/src/apply.ts`) did
`next.pageSchemas[action.pageId] = {...}` with no existence check, unconditionally pushed a
second `navFlow` entry, and returned `inverse: { type:"removePage" }`. `validateForCommit`
cannot catch it — `validateIdUniqueness` only looks *inside* the surviving trees and the
overwritten tree is already gone. Reachable because `PagePicker` de-duplicated only against
the `nav-flow` react-query, which returns `{ pages: [] }` on any non-ok response and is
`undefined` while loading.

**Fix.** `apply.ts` refuses three collisions with a clear message — existing `pageId`,
existing `route`, and an orphan `navFlow` entry for the id (which would also make the inverse
`removePage` destroy something `addPage` did not create). Because the create is refused, the
undo entry can only ever remove the page it actually made. `editor-store.dispatch` already
turns the throw into `lastError`, and `PagePicker.handleCreatePage` already checks `lastError`
before flushing, so the refusal surfaces in the UI with no new plumbing.
Second, `PagePicker` now sources `existingPageIds` / `existingRoutes` from the **union** of
the query and the edit store, so the dialog disambiguates the slug up front and the user
normally never reaches the refusal.

**Evidence.** `packages/patches/tests/apply.test.ts` (5 new tests) and
`frontend/src/__tests__/add-page-collision.test.ts` (3 new tests) — the colliding create sets
`lastError`, leaves `pageSchemas.items.root.id === "existing-root"`, and pushes **no** undo
entry.

### 3. `Redirect` navigated the whole editor away when dropped — FIXED

**Finding:** `panels.md`, "Components — Redirect — BUG".

**Root cause.** The canvas renders live library components and mounted **no**
`NavigatorProvider`, so `useNavigator()` fell back to `defaultNavigator`, whose `replace` is
`window.location.replace`. `Redirect` calls `nav.replace(to)` in a mount effect with a
registry default of `to: "/"`.

**Fix.** `frontend/src/lib/inert-navigator.ts` — `INERT_NAVIGATOR`, mounted by
`Canvas.tsx` around `EngineProvider`/`Engine`. Every navigation on the canvas is a no-op; the
canvas is a design surface, and a schema node is content to arrange, not behaviour to execute.
Deliberately not a router-backed navigator — a soft navigation would still lose the user's
place. `Redirect` keeps rendering its `<p data-redirect="…">Redirecting…</p>`, which is now
an inert, selectable placeholder.

This also closes the same hazard for **click-driven** navigation: `Engine` mounts a delegated
`[data-nav-trigger]` click listener that resolves through the *same* `useNavigator()` seam
(`packages/engine/src/Engine.tsx:213-227`), so clicking a `Button` / `Link` / `Table` row /
`Calendar` event / `Kanban` card on the canvas merely to select it used to navigate away too.

**Evidence.** `frontend/src/__tests__/canvas-inert-navigation.test.tsx` — 5 tests, including
two *control* cases that render the identical tree **without** the provider and assert that it
DOES navigate (`window.location.replace("/")`, `window.location.assign("/orders")`), proving
the seam is what fixed it.

**Still hazardous — components that bypass the Navigator seam** (they touch
`window.location` directly, so the provider does not reach them). All are click/submit
driven, none fire on mount, so none is a Phase-0 crash — but each will navigate the editor
away if the control is clicked on canvas:

| Component | Line |
|---|---|
| `AuthForm` | `AuthForm.tsx:93` — `window.location.assign(successRoute)` on submit |
| `IconButton` | `IconButton.tsx:58` — `window.location.assign(navigate)` on click |
| `CartPanel` | `CartPanel.tsx:110` — `window.location.href = onCheckoutNavigate` |
| `CommandPalette` | `CommandPalette.tsx:78` — `window.location.assign(item.action.to)` |
| `FilterBar` | `FilterBar.tsx:85-86` — rewrites the URL via `history.replaceState` |
| `Button` (reset-filters) | `Button.tsx:173` — `history.replaceState` when `clearsFilters` |
| `ThemeToggle`, `TourOverlay` | write `localStorage` on the editor's own origin |

Routing those through `useNavigator()` is the follow-up.

### 4. A breakpoint override with no base value rendered raw JSON to the end user — FIXED

**Finding:** `panels.md`, probe `probe_props_4`.

**Root cause, both sides.** `writePropAtBp` (`PropertiesPanel.tsx`) wrapped a
non-default-breakpoint edit as `{ default: currentRaw, [bp]: newValue }`; when the prop had no
value, `currentRaw` was `undefined`, the key vanished on `JSON.stringify`, and the schema held
`{ "lg": "…" }`. `pickResponsiveValue` (`packages/engine/src/responsive/useViewport.ts`) then
walked `xl→…→default`, found nothing, and `return value as T` handed back **the envelope**.

**Fix.**
- Resolver: the fall-through returns `undefined`, never the envelope. An envelope is never a
  legal rendered value; "no match at or below this breakpoint" means "no value here", so the
  component falls back to its own default exactly as for an unset prop.
- Panel: `writePropAtBp` takes the registry `descriptor.default` and seeds the base with
  `currentRaw ?? descriptorDefault ?? newValue`, so a base-less envelope is never written.

**Evidence.** `packages/engine/tests/responsive.test.ts` (3 new tests) and
`frontend/src/__tests__/properties-panel-phase0.test.tsx` (3 tests driving the real panel
through the BreakpointSwitcher). Live render of probe `zzp0-resp` (since deleted):
`Heading.content = {"lg":"ONLYLGHEADING"}` and `Badge.content = {"lg":"ONLYLGBADGE"}` now
render as **empty** elements at the SSR/default breakpoint — the strings appear only inside
the RSC flight payload, never in the DOM — while `{default:"BASEHEADING", lg:"LGHEADING"}`
still renders `BASEHEADING`. Before the fix the page printed
`{&quot;lg&quot;:&quot;ONLYLGHEADING&quot;}` to the user.

**Reported, NOT fixed — `sm` breakpoint mismatch.** The engine's `sm` is **480px**
(`useViewport.ts:6-12`); Tailwind's `sm:` — used in the classNames of the very same
components — is **640px**. Changing it is a live behaviour change for every schema that
already carries an `sm` override (every viewport in 480–639px would resolve differently) and
for the editor's BreakpointSwitcher semantics. Left alone deliberately; it needs its own
change with a migration story, not a drive-by edit inside a crash fix.

### 5. Token / URL / binding inputs dispatched per keystroke — FIXED

**Finding:** `panels.md`, "Tokens — every input dispatches per keystroke → undo/save storm",
plus the same defect logged against `ImageControl`'s URL box and the Bindings expression input.

**Root cause.** `editor-store.dispatch` pushes one undo entry per call and sets `isDirty`,
and each dirty transition re-arms the 500 ms autosave. Wiring `onChange` straight to
`dispatch` therefore cost one undo entry **and** one save arm per character — and, for
`<input type="color">`, one per pixel of drag inside the OS picker.

**Fix** — commit-on-blur/Enter with an Escape-abandons draft, matching the `SizeField`
pattern already in `StylePanel.tsx`; colour swatches get the 200 ms trailing debounce +
flush-on-blur already used by `BackgroundField`:
- `frontend/src/components/editor/TokenEditor.tsx` — new `TokenTextInput` / `TokenColorInput`,
  used by all four input sites (colour swatches, Flat sections, typography font, typography scale).
- `frontend/src/components/properties/PropControls/ImageControl.tsx` — URL box.
- `frontend/src/components/properties/PropControls/BindingControl.tsx` — hand-written
  expression box. The dropdown and "create data source" paths are discrete choices and still
  commit immediately.

**The `artifacts.tokens` constraint is intact.** `persistence.ts` writes `artifacts.tokens`
verbatim to `tokens.custom.json`, so the store must never be seeded with merged defaults.
Nothing here touches the store seed or `TokenEditor`'s display-only `deepMerge`; the existing
test that asserts a spacing edit leaves `Object.keys(tokens.spacing) === ["4"]` still passes.

**Evidence.** `token-editor.test.tsx` (4 new tests + 2 updated to the new commit contract),
`image-control.test.tsx` (2 new), `binding-control-commit.test.tsx` (3 new). Verbatim
contract: seven `change` events on a token field produce **0** dispatches; the following
`blur` produces exactly **1**. Five colour `change` events produce 0; one 200 ms tick
produces exactly 1, carrying the last colour.

---

### Suite status after Phase 0

| Suite | Result |
|---|---|
| `packages/patches` | 53/53 pass (5 new) |
| `packages/engine` | 45 pass, 2 fail — **identical 2 failures at HEAD** (verified against a pristine `git archive HEAD` copy) |
| `packages/renderer` | 8 new tests pass; 31 failures, **identical set at HEAD** (stale tests expecting `renderNode` to throw on unknown types) |
| `packages/registry` | 20 pass, 1 fail — `Form accepts standard form children`, caused by another agent's concurrent `accepts`→`rejects` change, not this work (HEAD copy passes 21/21) |
| `packages/library` | 23 failures, none in a test that imports `renderNode` / `NodeErrorBoundary` / `@tentoroforge/renderer` — all from concurrent work on theming/Heading/DescriptionList |
| `frontend` | 561 pass, 1 fail — the known pre-existing `exposes exactly 106 components` (registry has 133) |

## Browser-found bugs (B1-B11) — fix pass

| ID | Bug | Status | Evidence |
|---|---|---|---|
| B2 | Empty-node hints painted over toolbar + Properties panel | **FIXED** | portalled into the scroll container, `absolute` not `fixed`. Measured: hints now `877..1237` (were `1575`, `2027`) with `portalledIntoMain: true`. Screenshot confirms panel clear. |
| B3 | Palette drag-only; click did nothing | **FIXED** | `insertComponentByClick()`; item is `role="button"`, keyboard Enter/Space. Live: clicking Grid added `grid-ov7mr2` + 4 cells, 15 -> 20 nodes. |
| B6 | Sidebar main pane collapsed to 22px in a narrow parent | **FIXED** | `min(width, 40%) minmax(0, 1fr)` — keeps 240px when it fits, shrinks when it cannot. Built. |
| B7 | Device preview reflowed nothing | **FIXED (mechanism verified, end-to-end NOT re-observed)** | drop size is now a CEILING: `width:100%; max-width:420px` instead of `width:420px; max-width:100%`. Live-confirmed on a fresh Card. 38/38 drop-sizing tests pass after updating the contract they asserted. HMR kept resetting the page before the device-switch could be re-measured. |
| B8 | Drawer / InspectorPanel in the LAYOUT palette but 0x0 | **FIXED** | recategorised `layout` -> `feedback` (with Popover/Tooltip/HoverCard). |
| B9 | AppShell topbar/actions "default to SideNav" | **NOT A BUG** | registry defaults are `null`; the `{"type":"SideNav"}` seen in the panel is placeholder text in the textarea. |
| B10 | Detail template wrote cp1252, page rendered blank | **FIXED** | `encoding="utf-8"` on all 5 editor save paths. Verified: `em—dash · curly "quotes" · café` round-trips. User's corrupted `layout-detail.json` repaired in place — 17 nodes recovered. |
| B1 | `/editor/<shortId>` renders a dead shell | OPEN | not started |
| B4 | Committing a style value clears the selection | **OPEN — cause NOT identified** | ruled out: `useKeymap` correctly guards INPUT/TEXTAREA, so Enter is not hijacked there. Did not guess-fix. |
| B5 | `{{metrics.*}}` leaks to end users | OPEN | P0, needs the binding/dataSource work |
| B11 | A second drop into the same parent vanishes | **OPEN — reframed** | `ErrorBanner` IS mounted and no banner appeared, so the inserts were NOT rejected. The nodes most likely landed in an unexpected parent (nested into the previous sibling). Original "silently lost" framing is wrong. Needs a real mouse-drag repro, not synthetic DragEvents. |

### Side fix found while doing B3
`resolveAcceptingParent` built its root-fallback element with `targetEl?.ownerDocument?.querySelector(...)`.
On the click path with nothing selected `targetEl` is null, so `ownerDocument` short-circuited to
undefined and the root element was never found — `measureParentBox` got null and the node arrived
with NO style, reintroducing the full-width hairline. Now falls back to `document`.
Live before/after: `display: contents` -> `width:100%; max-width:420px; min-height:263px`.

---

## B5 — `{{metrics.*}}` leaked to end users — FIXED

**Symptom.** `/items` in the generated Inventory app rendered the literal text
`{{metrics.list_total_inventory_value}}` in a KPI tile, to the end user.

**Root cause.** `packages/renderer/src/runtime/interpolate.ts` decided whether to
show or hide an unresolved binding by *inferring* the surface:

```ts
const root = expr.match(/^([A-Za-z_$][\w$]*)/)?.[1];
if (root && Object.prototype.hasOwnProperty.call(data, root)) return "";
return text;   // root absent → keep the raw {{…}}
```

The reasoning was "no data for this root ⇒ we must be on the editor canvas, and
an author wants to see what is bound." But *root absent* is also exactly what a
**missing dataSource in a shipped app** looks like. The heuristic could not tell
an authoring surface from a production page, so it defaulted to leaking.

**Fix.** Invert it: safe by default, opt in explicitly.

- Renderer renders an unresolved binding as `""` — everywhere, in both the
  whole-string and mixed-text branches.
- The editor canvas asks for placeholders by putting `__authoring: true` in the
  data bag (`frontend/src/components/canvas/Canvas.tsx`, `resolvedPreview`). It
  is a render-time flag, never written to `store.artifacts`, so autosave cannot
  persist it into a page schema.
- The old literal fallback was protecting "the key stays present and
  string-typed" for Zod. `""` satisfies that, and `validateProps` is best-effort
  anyway (`packages/library/src/registry.ts` step 3).

**Verified.** `http://localhost:6503/p/gh0mlpbp/items` — 0 `{{…}}` in the
rendered DOM (remaining occurrences are inside `<script>`, the RSC payload
carrying the raw schema, which is data). Editor canvas at
`/editor/gh0mlpbp?page=items` — still shows all 3 placeholders. Renderer and
engine suites show no new failures vs. the pre-change baseline.

---

## B12 (NEW, open) — Stat tiles bind to a `metrics` source the page never declares

Found while verifying B5. Now that the leak is closed the three `/items` KPI
tiles render **blank**, which is the real underlying defect.

`output/gh0mlpbp/app/src/schemas/items.json` declares sources named `items`,
`totalInventoryValue`, `lowStockCount` — but its Stat nodes are bound to
`{{metrics.list_total_inventory_value}}` etc. There is no `metrics` source.

Two independent generators disagree:
- `backend/services/blueprint/page_planner.py:340` emits the binding
  `{{metrics.<_metric_key(widget)>}}`.
- `derive_data_sources` (same file, ~line 850) *does* know about the `metrics`
  namespace and even raises `PlanError` for bindings that name no fetchable
  data — but the sources that reached this file came from a different writer
  (there are 20 `schema["dataSources"] = …` sites in `backend/services/`).

`backend/services/widget_data_source_guard.py` exists precisely to give Stat
tiles a real aggregate source, but `_try_stat` only fires on a **literal
number** (`isinstance(props.get(p), (int, float))`). A Stat already carrying a
`{{…}}` string is counted as "already bound" and skipped — so the guard steps
over exactly the broken case. Nothing anywhere validates a binding's root
against the page's declared `dataSources`.

## B13 (NEW, open) — two incompatible aggregate-metric dialects

`items.json` writes metrics as `{"expression": "sum(quantity * price)",
"format": "currency"}`. Both resolvers expect `{"fn": "count", "field": "…"}`
(`frontend/src/lib/preview-resolve.ts` `resolveAggregate`, and the guard's
documented runtime contract). So even a correctly-named aggregate source would
resolve to 0 / garbage. The `expression` dialect has no parser on the render
side.

---

## B12 + B13 — blank KPI tiles — FIXED end to end

The chain that started at B5. Three separate defects stacked on the same tiles.

**B13 — two aggregate-metric dialects.** The page composer writes
`{"expression": "sum(quantity * price)"}`; every resolver reads `{"fn","field"}`.
`services/metric_dialect.py` is the single translator, wired into
`aggregate_spec` and `blueprint/page_planner`, plus `repair_output_dir()` for
projects already on disk. `sum(quantity * price)` normalises to
`{fn:"sum", expr:"quantity * price"}` — `expr`, not `field`, because `field`
must name a real column and `sum(undefined)` throws.

**B12 — a binding whose root named no declared source.** The Stats were bound to
`{{metrics.list_total_inventory_value}}` on a page declaring `items`,
`totalInventoryValue` and `lowStockCount`. `widget_data_source_guard._try_stat`
only fired on a LITERAL NUMBER, so a Stat already carrying a `{{…}}` string was
treated as "already bound" and skipped — the guard stepped over exactly the
broken case. `_is_dangling` now treats a binding whose root is neither a declared
source nor a known scope root (`item`, `row`, `user`, `$…`) as unbound. The three
tiles were rewritten to `{{totalInventoryValue.totalValue}}`,
`{{lowStockCount.lowStockCount}}`, `{{totalInventoryValue.itemCount}}`.

**The third defect, found only by looking at the rendered page.** With the schema
now completely correct, all three tiles were STILL blank.
`apps/render-scaffold/src/lib/resolvePreviewSync.ts` handled `op:"aggregate"` by
LOOKING UP a pre-computed `<entity>Stats` object and falling back to `{}` — it
never computed anything. And the lookup *succeeded*: the fixture endpoint does
return `itemStats`, a generic blob of `total`, `count`, `active`, `growthRate`…
containing **none** of the three metric names the page declares. Every binding
resolved to undefined.

This is why it survived every earlier pass: the EDITOR canvas
(`frontend/src/lib/preview-resolve.ts`) *computes* these metrics from the same
rows and showed numbers, so the tiles only looked broken in the shipped preview.
Two surfaces, two answers to "what is a KPI metric?".

Fix: `packages/engine/src/data/aggregate.ts` — one shared `computeAggregate`,
understanding both dialects, with a recursive-descent arithmetic evaluator rather
than `eval`/`new Function` (a page schema is data; data must not become code
because a tile needed a product of two columns). The scaffold now treats a
source's **declared metrics as the contract** — computed from rows, with the
looked-up blob left underneath so sources declaring no metrics behave exactly as
before.

**Verified on the real artifact**, `http://localhost:6503/p/gh0mlpbp/items`:

| tile | before | after |
|---|---|---|
| Total Inventory Value | blank | **46851.48** (Σ quantity × price) |
| Low Stock Items | blank | **0** (no row has quantity < 5) |
| Items | blank | **10** |

0 mustache placeholders in the rendered DOM.

### Known gaps left open here

- **`format` is carried but not applied.** The metrics declare
  `"format": "currency"` / `"number"`; the Stat renders `46851.48`, not
  `$46,851.48`. `interpolate` already has currency/number formatters behind the
  `{{x | currency}}` pipe syntax — the metric's `format` field is simply not
  wired to them.
- **`frontend/src/lib/preview-resolve.ts` still has its own copy** of the
  aggregate logic. It works and has no test coverage, so it was left alone this
  pass rather than refactored blind; it should delegate to
  `@tentoroforge/engine`'s `computeAggregate` so the two cannot drift again.
- **The scaffold's test suite does not run at all.** All four files under
  `apps/render-scaffold/tests/` are `node:test` modules: `node --test` cannot
  load `.ts` without a loader, and vitest reports "No test suite found". This is
  pre-existing and unrelated to these fixes, but it means the scaffold change
  above was verified against the live page only.
