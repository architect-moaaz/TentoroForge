# TentoroForge Visual Editor — Panel Audit

Audit target: Inventory Manager project `output/gh0mlpbp` (project `ad503658-18d3-42ac-bf3e-329c077ec17f`).
Method: read the write path in the panel, then find the consumer that reads it. Render probes via
`http://localhost:6503/p/gh0mlpbp/<probe>` where behaviour needed proving.

Bug class under investigation: **controls that WRITE a value nothing READS**, and **option values
outside the consumer's accepted union**.

## Summary

| # | Panel | Control | Verdict | One-line |
|---|-------|---------|---------|----------|
| _(filled in as findings land)_ | | | | |

---

## Findings

## Editor Store / Reducer

### Store — dead reducer actions (10 of 23) — GAP
`packages/patches/src/types.ts:71-93` declares 23 `EditorAction` types and
`packages/patches/src/apply.ts` handles all 23 (`case` at lines 116,143,182,209,236,270,310,347,383,409,446,458,473,488,504,514,523,535,551,561,570,580,605).
**No silent no-ops** — every action the UI can dispatch is handled. OK on that axis.

But grepping `frontend/src` for each action name shows **10 action types are dispatched by NO UI**:

| Action | UI dispatch sites | Consequence |
|---|---|---|
| `removePage` | 0 | A page can be created but **never deleted** from the editor. |
| `renamePage` | 0 | Page title is fixed at creation. |
| `updateRoute` | 0 | A page's route is fixed at creation; a typo'd route is permanent. |
| `removeDataSource` | 0 | `addDataSource` exists (1 site) but a data source can never be removed. |
| `setInitialPage` | 0 | The app's start page cannot be chosen. |
| `addTransition` / `removeTransition` | 0 | The whole NavFlow transition graph is unreachable. |
| `setGuard` | 0 | Route guards unreachable. |
| `addToken` | 0 | Tokens tab can only *update* existing tokens, never add a new one. |
| `renameToken` | 0 | Tokens cannot be renamed. |

(The only frontend hits for those names are unrelated local functions in
`frontend/src/components/rules/StateMachineEditor.tsx`, `agent-builder/config/RouterEditor.tsx`
and `lib/feel-lite/tokenizer.ts` — verified, not store dispatches.)

**Impact:** ~43% of the modelled editing surface has no control. Most user-visible:
you cannot delete or rename a page, cannot fix a route, and cannot pick the start page.

### Store — rejected commits ARE surfaced — OK (brief's premise corrected)
`frontend/src/lib/editor-store.ts:170-174` / `:196-200` set `lastError` and return without
applying, and `frontend/src/components/editor/ErrorBanner.tsx:33-43` renders it as an
"Edit rejected" toast, mounted at
`frontend/src/components/visual-editor/VisualEditorWorkspace.tsx:303`.
So a failing page is **not** silently rejected. The real hazard found is the opposite —
silent *acceptance* of a destructive `addPage` overwrite (see **PageGen** below).

---

## Tokens Tab

### Tokens — token edits never reach the PREVIEW (root split) — BUG (severe)
The preview server resolves ONE project root for tokens but TWO for schemas.

- `apps/render-scaffold/src/lib/loadSchema.ts:17-25` — `schemaRoots()` deliberately searches
  **both** `output/<id>/app/src/schemas` and `output/<id>/src/schemas` ("TWO WRITERS, TWO ROOTS…
  the editor writes `output/<id>/src/schemas/`").
- `apps/render-scaffold/src/lib/resolveProject.ts:23-28` — returns `output/<id>/app` whenever
  `app/src/schemas` exists. For `gh0mlpbp` it does.
- `apps/render-scaffold/src/app/[projectId]/[...slug]/page.tsx:249` `loadTokens(projectRoot)` and
  `:281` `loadTokensCustom(projectRoot)` both take that single `app` root.
- `apps/render-scaffold/src/lib/loadTokens.ts:14-21` then reads `<app>/src/theme/tokens.custom.json`,
  which **does not exist** (`ls output/gh0mlpbp/app/src/theme/` → only `.ts` files), and silently
  `catch`es to `defaultTokens`.
- The editor's persister writes to the OTHER root:
  `frontend/src/lib/persistence.ts:70-74` → `src/theme/tokens.custom.json`, which lands at
  `output/gh0mlpbp/src/theme/tokens.custom.json`.

**Live evidence.** `output/gh0mlpbp/src/theme/tokens.custom.json` contains
`color.primary.50 = "#c0c8d3"`. The rendered page emits the default instead:
```
$ curl http://localhost:6503/p/gh0mlpbp/items | grep -o -- "--token-color-primary-50:[^;]*"
--token-color-primary-50:#eff6ff      <-- defaultTokens, NOT the user's #c0c8d3
```
**Impact:** every colour/spacing/radius/shadow/typography edit made in the Tokens tab is written
to disk correctly and is then invisible in the preview. Same root split silently drops the
project's `globals.css` (`page.tsx:265`) for editor-rooted projects.
**Obvious fix:** give `loadTokens`/`loadTokensCustom` the same two-root fallback `loadSchema` has.

### Tokens — generated app's merge destroys colour ramps and corrupts scalars — BUG (severe)
`output/gh0mlpbp/app/src/theme/tokens.server.ts` merges ONE level deep:
```js
for (const g of new Set([...Object.keys(a), ...Object.keys(b)])) {
  out[g] = { ...(a[g] ?? {}), ...(b[g] ?? {}) };   // <-- one level
}
```
Run against the project's real override file:
```
color.primary -> {"50":"#c0c8d3"}            <-- 100..950 (10 shades) DELETED
density       -> {"0":"c","1":"o","2":"m",…} <-- string spread into an object
elevation     -> {"0":"l","1":"a","2":"y",…}
```
Two distinct defects:
1. Overriding ONE shade of a colour ramp deletes the other ten — `--token-color-primary-500`
   ceases to exist in the shipped app. The user changes one swatch and the whole brand palette
   evaporates.
2. `density` / `elevation` / `motionLevel` are **top-level string scalars**
   (`packages/library/src/theme/default-tokens.ts:88-92`). Object-spreading a string yields a
   char-indexed object. `useDensity()` (`packages/library/src/theme/tokens-context.tsx:56`)
   then returns that object, and consumers index a literal record with it —
   `{compact:"p-4",comfortable:"p-6",spacious:"p-8"}[<object>]` → `undefined`
   (`packages/library/src/anchors/anchor-shared.ts:19`).
   **So the Style tab's Design System → Density / Elevation controls are STILL dead in the
   generated app**, even after the `tokens.system.*` → `tokens.density` fix. The write path is now
   right; the app's merge destroys it.
   (`radius.scale` survives — it is nested, so the one-level merge preserves it.)
Compare `apps/render-scaffold/src/lib/loadTokens.ts:5-11`, which deep-merges correctly — the two
merges disagree, so preview and shipped app render differently.

### Tokens — canvas only merges the `color` group — BUG
`frontend/src/components/canvas/Canvas.tsx:136-155`:
```ts
const merged = {
  ...(defaultTokens as Record<string, unknown>),
  color: { ...defaultTokens.color, ...(liveTokens?.color ?? {}) },
};
```
Only `color` is overlaid. `merged.spacing`, `.radius`, `.shadow`, `.motion`, `.typography` are
**always the library defaults**, regardless of what the Tokens tab wrote into `artifacts.tokens`.
**Impact:** editing spacing / radius / shadow / typography in the Tokens tab changes nothing on
the canvas. It does persist, so the user sees no feedback, assumes it failed, and retries.
Additionally the colour overlay is a **shallow** group spread — `{...defaults.color, ...live.color}`
replaces the whole `primary` object, so overriding `primary.50` wipes 100..950 on the canvas too
(the same defect as `tokens.server.ts`). `TokenEditor.tsx:28-36` does a correct `deepMerge` for
*display* only, so the panel shows a full ramp the canvas no longer has.

### Tokens — every input dispatches per keystroke → undo/save storm — BUG
`frontend/src/components/editor/TokenEditor.tsx:109-110` `update()` calls `dispatch` directly, and
every field wires it to `onChange`:
- text inputs `:203`, `:236`, `:253` — one dispatch **per keystroke**
- `<input type="color">` `:160` — one dispatch **per pixel of drag** in the OS colour picker

`editor-store.ts:176-182` pushes one undo entry per dispatch and sets `isDirty`, and each dirty
transition re-arms the 500ms persister (`persistence.ts:83-88`). Typing `1.25rem` = 7 undo entries
and a burst of saves; dragging the colour picker buries the previous state under ~100 entries.
`StylePanel.tsx:217-232` solves exactly this with a 200ms trailing debounce + flush-on-blur —
`TokenEditor` has none.

### Tokens — whole groups unreachable — GAP
`TokenEditor.tsx:112-129` renders only `color`, `spacing`, `radius`, `typography.font`,
`typography.scale`, `shadow`, `motion`. Never rendered, so never editable:
- `typography.weight`, `typography.lineHeight`, `typography.letterSpacing`,
  `typography.display`, `typography.bodyText`, `typography.numeric`, `typography.scaleMode`
  (`TypographySection` at `:218-263` only reads `t[fontKey]` and `t.scale`)
- `imagery.*`, `semantic.status`, `breakpoints`
- **`motionLevel`** — a top-level scalar with a real consumer (`useMotionLevel()`,
  `tokens-context.tsx:68`) and **no control anywhere in the editor**. `ScaleMode` likewise.

### Tokens — overrides can only be reverted for colours — GAP
The `×` "Remove override" button exists only in `ColorSection` (`TokenEditor.tsx:167-176`).
`FlatSection` and `TypographySection` render no remove affordance, so once a spacing / radius /
shadow / motion / typography token is touched it becomes a permanent per-project override with
no way back to the library default from the UI.

### Tokens — `radius.scale` is a free-text field over a closed union — BUG
`FlatSection title="Radius" root={["radius"]}` (`TokenEditor.tsx:122`) flattens `defaultTokens.radius`,
which includes `scale: "soft"` (`default-tokens.ts:58`). It is rendered as a plain
`<input type="text">` (`:200-206`). The user can type `rounded`, `pill`, anything —
`useRadiusScale()` returns it and `RADIUS_SURFACE_CLASS[value]` → `undefined`, silently applying
no radius. This is the *same* dead-option defect that was just fixed in the Style tab's
`RADIUS_SCALE_OPTIONS`, re-introduced here as free text. It also duplicates that control with no
cross-highlighting, so the two panels can be set to disagree.

---

## Style Tab

Verified by rendering `output/gh0mlpbp/src/schemas/probe_style_a.json` (Box / Card / Chart / Badge,
each given the same full StyleSlot with a unique width + motionDuration so every value is
individually traceable in the HTML). `HTTP 200`.

### Style — Size (Width/Height/Min/Max) — OK
Writes `node.style.{width,height,minWidth,maxWidth,minHeight,maxHeight}`
(`StylePanel.tsx:511-546` → `writeStyle` `:477-486` → `updateStyle`, reducer
`packages/patches/src/apply.ts:143-178`).
Readers exist on **both** paths: `packages/renderer/src/runtime/style-slot.ts:52-57` (structural)
and `packages/library/src/style/resolveStyle.ts:92-99` `applySizing` (library).
Rendered proof — all four probes carried their width:
```
probe-box    style="width:240px;…;min-height:80px"                  (structural, direct)
probe-card   <span …style="display:block;box-sizing:border-box;width:241px;min-height:81px">
probe-chart  <span …style="display:block;box-sizing:border-box;width:242px;min-height:82px">
probe-badge  <span …style="display:block;box-sizing:border-box;width:243px">
```
Sizing reaches even `Chart`, which ignores everything else, because a sizing **wrapper span** is
emitted around library nodes. Commit-on-blur, empty-clears. No defect found.

### Style — Background is DEAD on Card / Hero / Section — BUG
`packages/library/src/components/surfaces/SurfaceBackground.tsx:57-59`:
```ts
} else if (typeof background === "string") {
  bgStyle = { background };          // <-- verbatim, NO token compilation
}
```
The two object branches (`:51`, `:55`) call `backgroundCss`, which resolves token refs. The
**bare-string** branch — which is exactly what the Style tab's Background dropdown writes
(`StylePanel.tsx:152-159`, values `"color.primary.500"` …) — passes it straight through.

Rendered proof from the probe (Card given `background: "color.accent.500"`):
```html
<div style="background:color.accent.500" class="flex flex-1 flex-col rounded-[inherit]">
```
`background: color.accent.500` is not valid CSS; the browser discards the declaration. The fill
never paints. Note the Card's *other* style keys DID land correctly on the outer element
(`padding:var(--token-spacing-8); border-radius:var(--token-radius-full);
box-shadow:var(--token-shadow-lg)`) — it is only `background` that is diverted to
`SurfaceBackground` and lost.
Affects **Card, Hero, Section** (the three `SurfaceBackground` consumers).
**Fix is small:** export `colorValue` from `packages/library/src/style/resolveStyle.ts` and use it
at `SurfaceBackground.tsx:58` — `bgStyle = { background: colorValue(background) }`.
(NOT applied — two lines across two files, so left as a recorded finding.)

### Style — Background (structural + ordinary library nodes) — OK
Box: `background-color:var(--token-color-primary-500);background:var(--token-color-primary-500)`.
Badge with a raw CSS colour: `background:rebeccapurple` inline, correctly *not* token-wrapped
(`isColorTokenRef` requires a dot — `style-slot.ts:117`). The debounce at
`StylePanel.tsx:217-232` correctly collapses a colour-picker drag into one undo entry.

### Style — Padding / Radius / Shadow / Motion / Duration silently ignored by 28 components — BUG
The Style tab renders the identical control set for **whatever node is selected**, with no
indication that the node cannot honour it. Only components that call `resolveStyle` do.

Programmatic count over `packages/library/src/components` (133 dirs):
**105 honour `node.style`, 28 do not**:
`ActivityFeed, ApprovalStepper, AppShell, AuthForm, AutoFocus, Chart, CommandPalette, DataGrid,
DateRangePicker, EmptyStateRich, FilterBar, FocusRing, FocusTrap, InspectorPanel, MobileNav,
MultiSelect, OptimisticProvider, PersonCard, Redirect, ResourceTimeline, SideNav, SkipLink,
Sparkline, TabPanel, TabPanelWithDeepLink, Timeline, Toast, variants`
(a handful — FocusTrap/AutoFocus/Redirect/OptimisticProvider — are behavioural wrappers with no
box, so are legitimately styleless. The visual ones are not: **Chart, DataGrid, SideNav, AppShell,
Sparkline, Timeline, ActivityFeed, MobileNav, FilterBar, PersonCard, Toast, Kanban-adjacent
surfaces** all discard the user's padding/radius/shadow/background/motion.)

Rendered proof — the Chart probe was given
`padding:spacing.2, radius:radius.sm, shadow:shadow.sm, background:color.secondary.500,
motion:stagger, motionDuration:1.7s`. The emitted HTML carries **only** the sizing wrapper:
```html
<span data-node-id="probe-chart" style="display:block;box-sizing:border-box;width:242px;min-height:82px">
  <div style="width:100%;height:240px;font-family:Inter, system-ui, sans-serif">…
```
No `padding`, no `border-radius`, no `box-shadow`, no `background`, and **no `data-motion`**
(the only three `data-motion` attributes in the document are Box, Card and Badge).
**Impact:** the classic write-with-no-reader. Six controls, silently inert, for ~1 in 5 components.

### Style — Motion + Duration — OK (where honoured)
Options `StylePanel.tsx:318-324` exactly match the schema enum
`packages/schema/src/style-slot.ts:16` `["none","fade-in","fade-up","stagger","slide-in"]`. ✅
`motionDuration` correctly lands as the `--motion-duration` custom property, not an
`animation-duration` longhand, on both paths (`style-slot.ts:66-68`, `resolveStyle.ts:83-87`):
```
probe-box   --motion-duration:1.5s  data-motion="fade-up"
probe-card  --motion-duration:1.6s  data-motion="slide-in"
probe-badge --motion-duration:1.8s  data-motion="fade-in"
```
`CSS_TIME` in the panel (`:94`) matches `DurationValue` in the schema (`style-slot.ts:50-53`). ✅
The disabled-when-no-motion gating matches the renderer's emit condition. ✅

### Style — Padding / Radius / Shadow option values — OK
`SPACING_OPTIONS` `spacing.2/3/4/6/8`, `RADIUS_OPTIONS` `radius.sm/md/lg/full`,
`SHADOW_OPTIONS` `shadow.sm/md/lg`, `BACKGROUND_OPTIONS` `color.{primary,secondary,accent}.500`,
`color.primary.{100,50}` — every one exists in `packages/library/src/theme/default-tokens.ts`
and `compileTokens` emits the matching canonical `--token-<group>-<path>` var
(`packages/renderer/src/runtime/tokens.ts:56-62`). Verified in the rendered HTML
(`var(--token-spacing-6)`, `var(--token-radius-lg)`, `var(--token-shadow-md)` all resolve).
No dead options in this group.

### Style — Design System writes are correct but destroyed downstream — BUG (see Tokens section)
`DESIGN_SYSTEM_PATHS` (`StylePanel.tsx:368-372`) now writes the canonical `["density"]`,
`["elevation"]`, `["radius","scale"]`, and the option lists match the unions in
`packages/library/src/theme/token-types.ts:16-18`. The write path and the migration off the dead
`system.*` group are correct.
**However** `density` and `elevation` are top-level *string scalars*, and the generated app's
`tokens.server.ts` object-spreads them into char-indexed objects — so these two controls are still
inert in the shipped app. Full evidence in **Tokens — generated app's merge …** above.
`radius.scale` survives (it is nested).

### Style — no gap / flex / alignment / typography controls — GAP
The Style tab exposes 6 keys. `StyleProps` (`packages/schema/src/tokens.ts:18-43`) models 23
(`color`, `gap`, `margin*`, `paddingX/Y`, `fontSize`, `fontWeight`, `lineHeight`,
`letterSpacing`, `borderColor`, `borderWidth`, …) and `resolveStyle`
(`packages/renderer/src/runtime/tokens.ts:76-96`) reads all of them. `StyleSlot.position`
(`style-slot.ts:31-38`) is fully implemented in the renderer (`style-slot.ts:39-46`) with **no
control at all**. Text colour, gap and margin are the most conspicuous absences — there is no way
to set a text colour anywhere in the Style tab.

---


## Props Tab

Scope: `frontend/src/components/properties/PropertiesPanel.tsx`,
`frontend/src/components/properties/PropControls/*`, registry
`packages/registry/src/starter.ts` (134 components, 475 prop descriptors).

### Props — control-type inventory — GAP

Registry control values actually in use (counted over all 475 `PropDescriptor`s in
`C:\Users\user\a2ui\TentoroForge\packages\registry\src\starter.ts`):

| `control` | # props | Editor (`PropControls/index.tsx:137-149`) | Verdict |
|---|---:|---|---|
| `text` | 210 | `TextControl` (index.tsx:29) | OK |
| `select` | 71 | `SelectControl` (index.tsx:72) | real, but see SelectControl BUG below |
| `toggle` | 46 | `ToggleControl` (index.tsx:89) | OK |
| `number` | 46 | `NumberControl` (index.tsx:58) | real, but see NumberControl BUG below |
| `binding` | 43 | `BindingControl` | OK |
| `actionPicker` | 40 | `ActionPicker` | **BUG — see below, most of these are arrays** |
| `textarea` | 7 | `TextareaControl` (index.tsx:44) | OK |
| `image` | 5 | `ImageControl` | OK |
| `iconPicker` | 5 | **FALLBACK → `TextControl`** (index.tsx:147) | GAP |
| `color` | 2 | `ColorControl` (index.tsx:103) | OK |
| `spacing` | 0 | `TextControl` (index.tsx:145) | dead mapping — no prop declares it |

There is **no `dataKey` and no `json` control type** in `ControlType`
(`C:\Users\user\a2ui\TentoroForge\packages\registry\src\types.ts:3-11`). `DataKeyControl` is
dispatched by prop *name*, not by control type
(`PropertiesPanel.tsx:158` `DATA_KEY_PROPS`, used at `:324`) — it silently overrides whatever
`control` the registry declared for `xKey`/`yKey`/`dataKey`/`categoryKey`/`nameKey`/`valueKey`/`angleKey`.

**Nothing falls through to `TextControl` because of an unknown control type** — the
`?? TextControl` at `PropertiesPanel.tsx:249` is never reached today. The gaps are the two
*deliberate* fallbacks:

- `iconPicker` → plain text box. Affected props (5): `NavLink.icon`, `EmptyState.icon`,
  `IconButton.icon`, `EmptyStateRich.icon`, `FeatureCard.icon`. The user must know a valid
  lucide icon name by heart; a typo renders nothing and reports nothing.
- Dead code: `ActionControl` is defined at `PropControls/index.tsx:117-135` (a raw-JSON
  textarea) but is **not in `CONTROL_BY_TYPE`** and is not imported anywhere — grep for
  `ActionControl` outside that file returns nothing. It is the array editor that would have
  partially covered the gap below, and it is unreachable.

### Props — `actionPicker` used for 26 array/object props — BUG

`ActionPicker` (`C:\Users\user\a2ui\TentoroForge\frontend\src\components\properties\PropControls\ActionPicker.tsx:92-273`)
is a **single-action** editor: one `<select>` of `none|navigate|workflow|submitForm|openModal`
plus the fields for the chosen kind. It has no list UI, no "add item", no JSON escape hatch.

The registry nevertheless assigns `control: "actionPicker"` to **40** props, and only ~6 of them
are genuinely a single action. `PropertiesPanel.tsx:144-155` intercepts 10 of them by *name*
(`data|rows|options|items|entries|records` → `BindingControl`), which leaves **24 array/object
props whose only editor is the action dropdown**:

`Tabs.tabs`, `TabPanelWithDeepLink.tabs`, `Table.columns`, `TableSortable.columns`,
`TableSortable.onSort`, `DataGrid.columns`, `DataGrid.rowActions`, `EditableLineGrid.columns`,
`EditableLineGrid.totals`, `Chart.series`, `Form.fields`, `Form.defaultValues`,
`AppShell.sidebar`, `AppShell.topbar`, `AppShell.actions`, `AppShell.rightRail`,
`ApprovalStepper.steps`, `FilterBar.chips`, `FilterBar.savedViews`, `DateRangePicker.presets`,
`MultiSelect.selected`, `MetricTile.delta`, `MetricTile.trend`, `EmptyStateRich.illustration`,
plus `Hero.ctas` (array of CTAs).

Two concrete failures, both from `ActionPicker.tsx`:

1. **It cannot show what is there.** `detectActionType` (`:39-47`) does `typeof v !== "object"`
   — an *array* passes that test, `v.action ?? v.type` is `undefined`, so every array value is
   reported as `"none"`. A `Table.columns` with 6 columns displays as "(no action)".
2. **Touching it destroys the value.** `setType` (`:104`) calls
   `onChange(emptyForType(t))`, and `emptyForType` (`:49-57`) returns `null` for "none" or a
   single `{action:…}` object otherwise. Picking any entry in the dropdown replaces the whole
   array. There is no path back except hand-editing the JSON file.

`MetricTile.trend` is documented in the registry as "Array of numbers for the sparkline trend"
and `MetricTile.delta` as `{ value, direction }` — neither is an action, and neither is
editable.

**Impact:** table columns, form fields, chart series, tab definitions, filter chips, stepper
steps and the whole `AppShell` slot set are read-only-and-destructible from the Props tab.

### Props — `Tabs.tabs` cannot be edited; a second tab is unreachable — BUG

Priority question, answered definitively.

**Control type.** `C:\Users\user\a2ui\TentoroForge\packages\registry\src\starter.ts:1071-1095` —
`tabsEntry.props.tabs = { type: "action", default: null, control: "actionPicker",
group: "content", description: "Array of { label, icon? } tab definitions — must match children
count." }`.

**Is it editable?** No. `PropertiesPanel.tsx:249` resolves
`CONTROL_BY_TYPE["actionPicker"]` → `ActionPicker` (`PropControls/index.tsx:144`). `tabs` is not
in `DATA_SOURCE_PROPS` (`PropertiesPanel.tsx:144`) nor `DATA_KEY_PROPS` (`:158`), so it is not
intercepted. The user is shown an action-kind dropdown reading "(no action)"; any selection
overwrites `tabs` with `null` or an `{action:…}` object (`ActionPicker.tsx:104,49-57`).

**Can a user add a tab after dropping Tabs from the palette?** No.
`defaultPropsFor` (`frontend/src/components/canvas/hooks/useDrop.ts:77-85`) materialises the
registry defaults verbatim, so a dropped `Tabs` arrives as
`props: { tabs: null, value: "tab-0" }, children: []`.
The renderer's LLM-compat coercion `packages/library/src/registry.ts:74-84` then substitutes
`tabs: [{ id: "tab-0", label: "Tab" }]` **at render time only** — it never writes back, so the
schema still holds `tabs: null`.
`Tabs` renders `tabs.map((t,i) => … panels[i])`
(`packages/library/src/components/Tabs/Tabs.tsx:53,72-82`) — the tab *strip* and the *panel*
list are both driven by `props.tabs`, never by the children.

**Probe evidence** (`output/gh0mlpbp/src/schemas/probe_props_3.json`, fetched from
`http://localhost:6503/p/gh0mlpbp/probe_props_3`, since deleted): a `Tabs` with
`tabs: null` and **two** `TabPanel` children rendered exactly **one** tab button labelled
`Tab` and exactly one tabpanel containing the first child's badge. The second panel's content
(`PANELTWOCONTENT`) appears only in the RSC payload / devtools segment tree — never in a
`role="tabpanel"` element.

**Impact:** drag Tabs in, drag two TabPanels in, and the second one is invisible with no error.
The only fix is editing `props.tabs` in the schema JSON by hand. `Tabs.tabs` is a
`z.array(TabDef).min(1)` with a `children.length === props.tabs.length` refine
(`packages/schema/src/nodes/layout-v2.ts:74,85-87`) that the editor never runs — see the
validation note below.

### Props — nothing validates prop VALUES at commit — BUG (enabler)

`validateForCommit` (`C:\Users\user\a2ui\TentoroForge\packages\patches\src\validate.ts:140-145`)
runs only `validateIdUniqueness` + `validateRegistryTypes` (component-type closure). It does
**not** run the Zod node schemas and does not even run `validateRegistryClosure` (unknown-prop
check). So every write above — `tabs: {action:"navigate"}`, `size: "xs"`, a raw
`{lg:"…"}` responsive blob on a string prop — commits cleanly and only misbehaves at render.

## Page Generation

Audited by rendering, not by reading: every kind was built with the exact config
`NewPageDialog.handleCreate` passes (`NewPageDialog.tsx:146-156`), run through
`validateForCommit` + `starterRegistry`, written to
`output/gh0mlpbp/src/schemas/probe_kind_<kind>.json` and fetched from the live scaffold render
server at `http://localhost:6503/p/gh0mlpbp/probe_kind_<kind>`. All probe files were deleted
afterwards.

### PageGen — all 7 kinds render — OK

| kind | validateForCommit | HTTP | expected landmarks? | notes |
|---|---|---|---|---|
| blank | pass (`[]`) | 200 (137,668 B) | yes — `Container > Stack > <h1>Probe blank</h1>` | nothing else by design; see heading BUG below |
| form | pass (`[]`) | 200 (140,563 B) | yes — `<form>`, `<label for="field-name">` + `<input type="text" name="name">`, `<label for="field-email">` + `<input type="email">`, `<button type="submit">Submit</button>`, wrapped in `data-card` | `required:true` in schema but no `required`/`aria-required`/`*` in DOM (see below) |
| sidebar | pass (`[]`) | 200 (140,466 B) | partly — `data-sidebar-pane="aside"` with 3 × `<a href="/">Overview\|Reports\|Settings</a>`, `data-sidebar-pane="main"` with `<h1>` | renders as `<div>`, **not** `<nav>`/`<aside>`; all 3 links point at `/` |
| navbar | pass (`[]`) | 200 (142,562 B) | partly — `<h3>` brand + 3 × `<a href="/">` + `<hr role="separator">` + `<h1>` | no `<nav>` element; all 3 links point at `/` |
| dashboard | pass (`[]`) | 200 (147,948 B) | yes — 4 × `data-metric-tile` (Total/Active/Pending/Archived, value `0`) in a grid, then `data-card` "Recent activity" > `<table><thead>` 3 cols > `data-forge-empty="table"` "No recent activity" | |
| list | pass (`[]`) | 200 (144,130 B) | yes — `<h1>` + `<button data-variant="primary">New</button>`, `data-card` > `<table>` 3 headers + empty state "Nothing here yet" | |
| detail | pass (`[]`) | 200 (144,407 B) | yes — `<button data-variant="ghost">Back</button>` + `<h1>`, then `data-split-ratio="2:1" data-split-breakpoint="md"` holding "Details" and "Summary" cards | |

Zero occurrences of `Unknown node`, `data-unknown-node`, `unknown component`, `invalid props`,
`undefined` or any error-boundary text in any of the 7 responses. **No kind is broken.** The bugs
below are in the dialog's contract with the user, not in the emitted trees.

### PageGen — "Show page heading" off produces a page that renders NOTHING — BUG
`page-scaffold.ts:376-378` (`buildBlank`), `:451-455` (`buildSidebar` main pane) and `:479-481`
(`buildNavbar` body) build the content `Stack` from `heading ? [pageHeading(...)] : []`. With the
"Show page heading" checkbox (`NewPageDialog.tsx:332-335`) unchecked, `blank` emits:

```json
{"type":"Container","props":{"maxWidth":"lg"},
 "children":[{"type":"Stack","props":{"direction":"vertical","gap":"tokens.spacing.6"},"children":[]}]}
```

Rendered (`HTTP 200`, 136,767 B) the entire page body is:

```html
<div data-node-id="container-2h9pxc"><div data-node-id="stack-gik71v"></div></div>
```

An empty, zero-height stack. The user gets a 200 and a blank screen with no drop affordance, no
placeholder and no explanation. `sidebar` and `navbar` get the same empty main column (the nav
rail still renders). Impact: the most common "I will build it myself" path (Empty page + no
heading) lands the user on a page that looks like the editor failed.

### PageGen — the route preview lies whenever the slug is already taken — BUG
`NewPageDialog.tsx:132` computes the previewed route as `slugify(trimmed) || "page"` with **no**
de-duplication, while `scaffoldPage` de-duplicates against `existingPageIds` + `existingRoutes`
(`page-scaffold.ts:578-587`). Proven:

```
title "Items", existingRoutes ["/items","/items/new","/items/[id]"]
  dialog preview  ->  /items
  actually built  ->  pageId "items-2", route "/items-2"
```

The dialog shows `Route: /items` under the title field right up to the moment it creates
`/items-2`. There is no duplicate warning, no disabled Create, no post-creation notice.
Impact: the user's mental model of the route is wrong for every name collision, and collisions
are the common case (a second "Settings", "Login", "New").

### PageGen — any non-ASCII title becomes the route `/page` — BUG
`slugify` (`page-scaffold.ts:244-251`) strips everything outside `[a-z0-9]`. Proven:

```
"中文页面"              -> pageId "page"
"Отчёты"               -> pageId "page"
"صفحة"                 -> pageId "page"
"😀"                   -> pageId "page"
"!!!" / "***" / "///"  -> pageId "page"
"Café Menü"            -> pageId "caf-men"
```

`canCreate` (`NewPageDialog.tsx:136`) only requires `trimmed.length > 0`, so all of these are
accepted. A user working in any non-Latin language gets `/page`, `/page-2`, `/page-3` … with the
route bearing no relation to the title, and no warning that the title was discarded. Accented
Latin silently loses characters ("Café Menü" → `caf-men`). Impact: route naming is unusable
outside ASCII, and there is no route field to override the derived slug.

### PageGen — the "Req" checkbox is inert for Checkbox and Switch fields — BUG
`NewPageDialog.tsx:280-287` renders the "Req" checkbox for **every** field row regardless of kind.
`toFieldSpec` (`page-scaffold.ts:288`) gates `required` on `REQUIRABLE` (`:223-230` — text, email,
number, textarea, select, date). Proven:

```
input : [{label:"Agree", kind:"checkbox", required:true},
         {label:"On",    kind:"switch",   required:true}]
output: [{kind:"checkbox", name:"agree", label:"Agree"},
         {kind:"switch",   name:"on",    label:"On"}]
```

The checkbox stays visibly ticked in the dialog and the flag is silently dropped. The comment at
`page-scaffold.ts:221-222` says the drop is deliberate (the Zod union is `.strict()`), but the
dialog was never told: the control should be disabled or hidden for those two kinds. Impact: a
"you must accept the terms" checkbox is created non-required while the UI claims otherwise.

### PageGen — duplicate field labels are accepted and produce identical fields — GAP
`canCreate` only checks that `f.label.trim()` is non-empty (`NewPageDialog.tsx:135`), so three
rows can all be labelled "Name". `toFieldSpec` de-duplicates the *name* but not the *label*:

```
[{Name,text,req},{Name,email,req},{name,number}]
  -> [{name:"name",label:"Name"},{name:"name-2",label:"Name"},{name:"name-3",label:"name"}]
```

The rendered form has three visually indistinguishable fields. Impact: low severity, but it is
exactly the class of thing the dialog exists to catch before commit.

### PageGen — `required` never reaches the DOM — GAP (renderer-side)
The form probe's schema carries `"required": true` on both fields (it appears three times in the
RSC payload inside the response) but the rendered inputs are
`<input id="field-name" type="text" name="name"/>` — no `required`, no `aria-required`, and no
asterisk on the `<label>`. `packages/library/src/components/Form/Form.tsx:814` passes it to
react-hook-form's `register(name, { required: ... })`, so submit-time validation *does* work, but
SSR HTML and assistive technology see an optional field. Impact: a11y plus no visual required
affordance on any scaffolded form.

### PageGen — "Navigation links" is a read-only label, not a control — GAP
`NewPageDialog.tsx:304-317` renders a `<Label>Navigation links</Label>` above a paragraph of
labels joined by `·`. There is no way to add, remove, rename or re-target a nav entry. The list
comes from `navItemsFromRoutes(existingRoutes)` (`:69-85`), which **skips every parameterised
route** (`:75`). In a project whose only routes are `/items/[id]` and `/items/[id]/edit` the
helper returns `undefined` and `scaffoldPage` falls back to `DEFAULT_NAV_ITEMS`
(`page-scaffold.ts:237-241`) — three links labelled Overview / Reports / Settings that **all
navigate to `/`**. Confirmed in the rendered sidebar and navbar probes:
`<a href="/">Overview</a><a href="/">Reports</a><a href="/">Settings</a>`.
The dialog's preview duplicates that fallback as an inline literal at `:308-312` instead of
importing `DEFAULT_NAV_ITEMS`, so the two can drift. Impact: the two nav-shell kinds ship three
dead links by default and the user cannot fix them from the dialog.

### PageGen — `addPage` overwrites an existing page and its undo deletes it — BUG
The worst finding, and `validateForCommit` does not catch it.

`applyAction` `case "addPage"` (`packages/patches/src/apply.ts:383-405`) does
`next.pageSchemas[action.pageId] = {...}` with **no existence check**, then unconditionally
`next.navFlow.pages.push({...})`, and returns `inverse: { type: "removePage", pageId }`.
`validateForCommit` (`packages/patches/src/validate.ts:140-145`) runs only `validateIdUniqueness`
(node ids *within* the surviving trees — the old tree is already gone) and
`validateRegistryTypes`. `validateNavConsistency`, which would flag the duplicated nav entry,
lives in `validateAll` only. Proven:

```
before: pageSchemas.items.root.id = "old-root"      (navFlow: 1 entry for "items")
dispatch addPage { pageId:"items", ... }
after : validateForCommit -> []                       <-- accepted
        pageSchemas.items.root.id = "container-by2xq2"  <-- original tree destroyed
        navFlow.pages = [ {id:"items",...}, {id:"items",...} ]   <-- duplicated
        inverse = { type:"removePage", pageId:"items" }  <-- undo DELETES the page
```

Reachable from the dialog: `PagePicker.tsx:186-187` sources `existingPageIds` / `existingRoutes`
from the `nav-flow` react-query, and that query returns `{ pages: [] }` on **any** non-ok response
(`PagePicker.tsx:82-87`) and is `undefined` while loading (`:90`). Open New Page before the fetch
settles — or with the backend down — and the dialog de-duplicates against nothing, so typing an
existing page's title silently replaces that page. Ctrl-Z then removes it entirely. Impact: user
data loss with no confirmation and no error; the `lastError` guard at `PagePicker.tsx:102` never
fires because the action validates clean.

### PageGen — every scaffolded page is forced `shell: true` — GAP
`apply.ts:400` sets `shell: action.shell ?? true`, and neither `NewPageDialog` nor `PagePicker`
ever passes `shell`. The `sidebar` and `navbar` kinds emit their **own** nav rail / top bar, so
creating one inside a project that has an app shell yields two navigations stacked on the same
page. The render probes confirm the frame wrapper is always present
(`<div data-sidebar-open="false">` wraps every probe root). Impact: the two nav-shell kinds are
the ones most likely to be wrong by default, and the dialog offers no shell toggle.

### PageGen — dialog control → consumer map — OK
Every piece of dialog state has a real consumer; there is no write-only field.

| control | written | consumed |
|---|---|---|
| Page title | `NewPageDialog.tsx:196` | `:131` → `:147` (`scaffoldPage.title`) |
| Layout / template kind buttons | `:168` (`setKind`) | `:130` (`pageKindMeta`), `:148`, `:153` |
| Form width (centered/full) | `:232`, `:239` | `:149` → `page-scaffold.ts:410-431` (form only) |
| Form fields (label / kind / Req) | `:266`, `:270`, `:284` | `:152` → `toFieldSpec` (form only; **Req dropped for checkbox/switch**) |
| Add / remove field | `:142`, `:141` | same |
| Submit button label | `:327` | `:150` → `page-scaffold.ts:618` (form only) |
| Show page heading | `:333` | `:151` → every builder |
| Navigation links | — (no control) | `:153` `navItemsFromRoutes(existingRoutes)` |

Caveats: `layout`, `submitLabel` and `fields` are passed unconditionally for every kind and are
ignored by the non-form branches (harmless). `heading` is the only option shared by all seven
kinds. Verified `layout: "full"` does change the output (`Container maxWidth "xl"`, `Form` as a
direct `Stack` child instead of wrapped in a `Card`).

### PageGen — dispatch path is wired, and rejection is NOT silent — OK
`PagePicker.handleCreatePage` (`PagePicker.tsx:94-110`) dispatches
`{ type: "addPage", pageId, route, title, root }`, a declared `EditorAction`
(`packages/patches/src/types.ts:79`) handled at `apply.ts:383`. Contrary to the audit brief, a
failing page is **not** silently dropped: `editor-store.ts:170-174` sets `lastError`,
`PagePicker.tsx:102` aborts the flush, and `ErrorBanner.tsx:33-43` renders it as an
"Edit rejected" toast (mounted at `VisualEditorWorkspace.tsx:303`, auto-clearing after 5s).
All seven kinds round-trip `applyAction` + `validateForCommit` against a project that already
contains a page with `errs = []`, each getting a correct nav entry
(`{id, route, title, schemaFile:"src/schemas/<id>.json", params:[], shell:true}`).
The real risk is the opposite of silent rejection — silent **acceptance** of a destructive
overwrite (see the `addPage` BUG above).

---

## Components Palette

Palette source: `C:\Users\user\a2ui\TentoroForge\frontend\src\components\palette\Palette.tsx`
Mounted at `C:\Users\user\a2ui\TentoroForge\frontend\src\components\visual-editor\VisualEditorWorkspace.tsx:275`.
Drop handling: `C:\Users\user\a2ui\TentoroForge\frontend\src\components\canvas\hooks\useDrop.ts`.

### Components — Inventory — OK (133 entries, 6 rendered groups)

The palette has no hard-coded list: it enumerates `starterRegistry`
(`Palette.tsx:80-84`, `packages/registry/src/starter.ts:3345`) and buckets by `entry.category`,
skipping `hidden` entries. Verified by executing the real registry: **134 entries, 1 hidden
(`GridCell`) → 133 draggable items.**

Counts per rendered group (`CATEGORY_ORDER`, `Palette.tsx:13-21`):

| group | count | entries |
|---|---|---|
| Layout | 20 | Container, Grid, Card, Divider, Spacer, Hero, Stack, Row, Section, Tabs, TabPanel, Sidebar, Cluster, Split, AppShell, InspectorPanel, TabPanelWithDeepLink, Drawer, CartPage, SplitView |
| Input | 41 | Input, Textarea, Select, Checkbox, Switch, NumberInput, MoneyInput, RadioGroup, Slider, FileUpload, Combobox, Button, Form, IconButton, FilterBar, DateRangePicker, MultiSelect, DatePicker, TimePicker, ColorPicker, InputOTP, Rating, MaskedInput, KeyValueInput, SegmentedControl, Transfer, Cascader, Calendar, RichTextEditor, CameraCapture, BarcodeScanner, Scanner, AddToCart, BulkActionBar, SavedViewsPicker, GlobalSearch, SearchInput, KeyboardShortcuts, ThemeToggle, Wizard, FilterBuilder |
| Display | 31 | MoneyDisplay, Heading, MetricTile, Avatar, Badge, ApprovalStepper, PersonCard, ActivityFeed, FeatureCard, KeyValueList, Gauge, SplitArc, Heatmap, Schematic, Stepper, Tag, Stat, DescriptionList, List, Tree, Kanban, ResourceTimeline, Carousel, Lightbox, CodeBlock, QRCode, ValidationChecklist, FadeIn, Stagger, Dialog, SearchResults |
| Interactive | **0** | — group header never renders (see BUG below) |
| Data | 12 | Table, Chart, Sparkline, DataGrid, EditableLineGrid, Timeline, TableSortable, Repeat, Conditional, DataBoundary, Slot, CartPanel |
| Feedback | 19 | Alert, EmptyState, EmptyStateRich, Skeleton, LoadingState, Progress, Spinner, Banner, Popover, Tooltip, HoverCard, IllustratedEmpty, FocusTrap, FocusRing, AutoFocus, UndoManager, PresenceIndicator, OptimisticProvider, TourOverlay |
| Navigation | 10 | NavLink, Breadcrumb, CommandPalette, Link, Redirect, DropdownMenu, ContextMenu, Menubar, CartBadge, SkipLink |

### Components — commit validation — OK (no palette entry can be rejected)
`validateForCommit` (`packages/patches/src/validate.ts:139-144`) is only
`validateIdUniqueness` + `validateRegistryTypes`. Since every palette item is *by construction*
a `starterRegistry` key, `validateRegistryTypes` (`validate.ts:63-75`) can never reject it, and
`useDrop.ts:648-655` (`ensureUniqueIds`) walks the whole scaffolded subtree to guarantee id
uniqueness before dispatch. Required props / required children are **not** checked at all by
`validateForCommit`, so no palette drop is ever blocked from saving.
Also note: a commit rejection would **not** be silent — `editor-store.ts:170-174` sets
`lastError`, rendered by `ErrorBanner.tsx:33-43` (mounted `VisualEditorWorkspace.tsx:303`).
A rejected drop target likewise sets `lastError` (`useDrop.ts:632-637`).

### Components — drop → store action — OK (dispatched action IS handled)
The palette itself dispatches nothing (`Palette.tsx:170-176` only sets HTML5 drag data +
`setDraggingComponent`). The canvas's `onDrop` (`useDrop.ts:657-663`) dispatches
`{ type: "insertNode", pageId, parentId, index, node }`. That action is declared at
`packages/patches/src/types.ts:71` and handled at `packages/patches/src/apply.ts:182-206`
(children array **and** `slotKey` path), reached from `editor-store.ts:146-183`. Not a no-op.

### Components — click-to-insert — BUG (palette items are drag-only)
`Palette.tsx:168-179`: each `<li>` has `draggable`, `onDragStart`, `onDragEnd` and **no
`onClick`**. Grepping the whole canvas + palette for the drag MIME type finds only
`Palette.tsx:172` and `useDrop.ts:604,624`; there are no `onTouchStart`/pointer handlers
anywhere in `frontend/src/components/palette` or `frontend/src/components/canvas`.
Impact: (a) clicking a component does nothing at all — the single most common first gesture in
a visual editor is a dead click; (b) HTML5 `dragstart` does not fire from touch input, so on the
mobile/tablet layout — where `VisualEditorWorkspace.tsx:267-279` deliberately renders the
palette as a full-height overlay drawer — **the palette is 100% unusable**: nothing can be
inserted by any gesture.

### Components — "Interactive" group — BUG (dead group, never renders)
`Palette.tsx:17` lists `{ id: "interactive", label: "Interactive" }`, but `RegistryEntry.category`
is typed as `"layout" | "input" | "display" | "navigation" | "feedback" | "data"`
(`packages/registry/src/types.ts:44`) — `"interactive"` is not a legal category, and zero of the
134 entries use it. `Palette.tsx:158` short-circuits on the empty array, so the group silently
never appears. Harmless at runtime, but it is a lie in the source, and `CATEGORY_ORDER` is the
palette's *only* whitelist: a registry entry whose category is not one of the seven listed ids
would be invisible with no warning.
## Bindings Tab

### Bindings — an unresolved binding leaks raw `{{…}}` to end users, with zero validation — BUG (severe)
**Live evidence** from `curl http://localhost:6503/p/gh0mlpbp/items` (HTTP 200) — four distinct
unresolved bindings render as literal mustache text in the shipped markup:
```html
<span class="text-sm text-muted-foreground">Total Inventory Value</span>
<div class="flex items-baseline gap-2">
  <span class="text-2xl font-semibold text-foreground">{{metrics.list_total_inventory_value}}</span>
```
All unresolved templates in the body:
`{{metrics.list_total_inventory_value}}`, `{{metrics.list_low_stock_items}}`,
`{{metrics.list_items}}`, `{{items}}`.

Why it leaks — `packages/renderer/src/runtime/interpolate.ts:145-150`:
```ts
if (v === undefined || v === null || v === false) {
  const root = expr.match(/^([A-Za-z_$][\w$]*)/)?.[1];
  if (root && Object.prototype.hasOwnProperty.call(data, root)) return "";
  return text;                       // <-- root unknown ⇒ emit the raw {{…}}
}
```
`metrics` is not a data source on this page (its sources are `items`,
`totalInventoryValue`, `lowStockCount` — `output/gh0mlpbp/src/schemas/PAGE-001.json:1-45`), so the
root is unknown and the placeholder is emitted verbatim. The fallback is deliberate for the
*editor preview*, but it is the same code path in the production render.

**There is no validation anywhere on the path:**
- `packages/patches/src/validate.ts` — grep for `binding` / `{{` / `mustache`: **zero hits**.
  `validateForCommit` never looks at bindings, so a nonsense expression commits cleanly.
- `packages/schema/src/cross-ref-validator.ts:32` `validateCrossRefs` *does* check
  `page.dataSources[i].entity` against a registry — but nothing in `frontend/src` or
  `packages/patches` imports it. Outside its own unit test
  (`packages/schema/tests/cross-ref-validator.test.ts`) it has **no callers**. Dead validator.
- `BindingControl.tsx:337-343` — the free-text expression `<input>` fires `onChange` straight
  into `dispatch` with no parse, no root check against `sources`, and no error affordance.

**Impact:** the user's exact reported symptom. A typo'd or stale binding is accepted by the
editor, saved, and shipped as visible `{{…}}` garbage to end users. Nothing warns at any stage.
The panel could trivially flag this — it already computes `known`
(`BindingControl.tsx:170-174`), the set of every valid expression for the page, and uses it only
to decide whether to show a "Custom:" option.

### Bindings — you cannot CREATE a binding from the Bindings tab — GAP
`BindingsPanel.tsx:100-111`: when `collectBindings` returns empty the panel renders
*"No bindings on this node. Use the bind toggle in the Props tab…"*. The tab is a read/edit view
over bindings that already exist; the only way to make one is `BindToggle`
(`BindToggle.tsx`, an 18-line `{ } / Aa` button) in the Props tab. A user who opens the tab named
"Bindings" to bind something is told to go elsewhere.

### Bindings — bindings inside arrays are invisible — BUG
`BindingsPanel.tsx:60-66` — the recursive walk descends into objects but explicitly skips arrays:
```ts
} else if (v && typeof v === "object" && !Array.isArray(v)) { walk(v, …) }
```
So a binding in `Table.columns[]`, `Chart.series[]`, `Select.options[]`, `List.items[]` — all
array-of-object props — is never listed and never editable here. These are among the most common
places a real binding lives.

### Bindings — `node.bind` and `node.visibleIf` are invisible — BUG
`BindingsPanel.tsx:68` walks **only `node.props`**. The node envelope
(`packages/schema/src/page.ts:196-201`) also carries `bind` (the `DataBinding`, which is how
`Repeat` and every data-aware node get their rows) and `visibleIf` (an `Expression`). Neither is
listed or editable. Selecting a `Repeat` — the single most binding-dependent node type — shows
"No bindings on this node."

### Bindings — nested paths are read-only — GAP (documented, but a real hole)
`BindingsPanel.tsx:122-135`: only top-level prop names get a `BindingControl`; anything with a dot
(`delta.value`, the shape `Stat` and `MetricTile` actually use) renders as a static grey row.
The comment says this is because "updateProp targets a top-level prop name", but `PropPath` is
already a path type and `apply.ts`'s `updateProp` handles it — so the restriction looks
conservative rather than necessary.

### Bindings — expression input dispatches per keystroke — BUG
`BindingControl.tsx:337-343`, `onChange={(e) => onChange(e.target.value)}` → `dispatch` per
character (`BindingsPanel.tsx:143-161`). Same undo-stack/save-churn defect as the Tokens tab;
typing `totalInventoryValue.totalValue` is ~28 undo entries. Every other panel that got attention
(`StylePanel` SizeField/DurationField commit-on-blur, BackgroundField debounce) avoids this.

### Bindings — "Create a chart data source" is one-way — GAP
`BindingControl.tsx:199-227` `createSeries` dispatches `addDataSource`. There is no counterpart:
`removeDataSource` exists in the reducer (`apply.ts:488`) and is dispatched by **no UI**. A
mistakenly created series source is permanent. Errors here *are* handled properly
(`:214-222` surfaces `createError`) — good.

### Bindings — dropdown option set — OK
`BindingControl.tsx:110-166` builds options per `dataSources` op (`aggregate`/`stats` → metric
keys, `series` → whole array + `[0].label`/`[0].value`, `get`/`detail` → entity fields,
`list` → `name` + `name[0].field`), ordering by whether the prop name is a collection
(`COLLECTION_PROP`, `:38`). Entity fields come from a live registry fetch with proper
loading/error/retry states (`:88-107`, `:275-292`). The generated expressions match what
`interpolate`'s `evalExpression` resolves. No dead options found in this control.

---


### Components — render verification method
All 133 draggable entries were materialised with the **real** `buildDroppedNode` recipe
(`useDrop.ts:479-508`: `defaultPropsFor` from `starterRegistry` + empty `children` for
non-leaves + the `Sidebar`/`Split`/`SplitView` 2-Card scaffold + the `Grid` 2x2 GridCell
scaffold), written as 133 one-component pages and server-rendered through the live render
service (`http://localhost:6503/p/gh0mlpbp/probe_palette_<name>`). All 133 returned HTTP 200
and **none** produced a `⚠ <Type>` unknown-component placeholder, so the palette→renderer type
mapping is sound. Probe pages have been deleted.
Corroborated by `packages/library/tests/registry-parity.test.ts`, which currently fails on
exactly one name — `GridCell` — and `GridCell` is `hidden: true` in the palette and is
core-dispatched anyway (`packages/renderer/src/runtime/dispatch.tsx:172`).

### Components — Redirect — BUG (drops navigate the whole editor away)
`packages/library/src/components/Redirect/Redirect.tsx:20-25` calls `nav.replace(to)` in a
mount effect, and the registry default is `to: "/"` (`starter.ts`, verified by executing the
registry). The editor canvas renders live library components
(`frontend/src/components/canvas/Canvas.tsx:277-279`, `Engine`/`EngineProvider`) and mounts
**no** `NavigatorProvider` — grepping all of `frontend/src` for `NavigatorProvider` returns
nothing — so `useNavigator()` falls back to `defaultNavigator`
(`packages/renderer/src/client/Navigator.tsx:36-42`), whose `replace` is
`window.location.replace(url)`.
Impact: dragging **Redirect** onto the canvas hard-navigates the entire editor SPA to `/` the
instant it mounts. Autosave is a 500 ms debounce (`frontend/src/lib/persistence.ts:9,41,83`),
so the drop that caused it — and any edits inside the same window — are lost. Verified by
render probe: the node emits `<p data-redirect="/" role="status">Redirecting…</p>`.

### Components — Repeat / Conditional / DataBoundary / Slot — BUG (no DOM at all; unselectable)
Render probes produced **zero** DOM for all four — not even a wrapper carrying `data-node-id`:
`probe_palette_repeat` body is literally `<div data-node-id="…-root" class="…"></div>`.
They are also in `UNSIZED` (`useDrop.ts:610-616` region, the "Zero-box wrappers" group), so
`deriveDropStyle` returns `null` and no minimum height is applied either.
The canvas resolves selection and drop targets exclusively through `[data-node-id]` elements
(`useDrop.ts:540-548`). Impact: dropping any of these four inserts a node that is invisible,
cannot be clicked, cannot be selected, cannot be resized and cannot be dropped into — the
component silently disappears from the user's point of view while sitting in the saved schema.
The only recovery is the layers tree.
Root cause is data, not wiring: `Repeat.source/bind/path` default `""`, `Conditional.when`
defaults `""`, `DataBoundary.fallback` defaults `""` — with no source/condition they render
nothing by design, and the palette offers no way to arrive with one.

### Components — 11 entries render an EMPTY `<span data-node-id>` — BUG (invisible + unclickable)
Probed bodies are exactly `<span data-node-id="…"></span>` (zero-size, so a 0x0 hit box):
**Dialog, InspectorPanel, Sparkline, DescriptionList, CartBadge, BulkActionBar,
KeyboardShortcuts, UndoManager, PresenceIndicator, TourOverlay** (plus `Menubar`, which renders
an empty 1-px bordered bar).
Seven of these are additionally in `UNSIZED` (`useDrop.ts` "Anchored / viewport overlays" and
"Fixed-geometry controls" groups) so they get no `minHeight` fallback either: **Dialog,
InspectorPanel, TourOverlay, UndoManager, CartBadge, PresenceIndicator** are 0x0 forever.
`useDrop.ts`'s own comment concedes the failure mode ("a 0x0 empty Stack/Row/Grid is invisible
AND permanently unclickable") but the `UNSIZED` list re-introduces it for these types.
Impact: the palette advertises 11 draggable components that, when dropped, appear to do
nothing at all.

### Components — content comes from array props the editor cannot author — BUG (systemic)
`PropDescriptor.type` is `"string" | "number" | "boolean" | "enum" | "action" | "binding"`
(`packages/registry/src/types.ts:26`) — there is **no array or object prop type**. Every
component whose visible content is a list therefore declares that list as either
`type: "action", control: "actionPicker", default: null` or `type: "binding", default: null`,
neither of which can express `[{key,label},…]`.

Confirmed empty-on-drop as a direct result (probe bodies show the shell with no rows/items):

| entry | content prop (registry) | probe result |
|---|---|---|
| Table | `columns: action/actionPicker=null` | `<table>` with an empty `<tr>` header, no columns |
| TableSortable | `columns: action/actionPicker=null` | bare unstyled `<table><thead><tr></tr>` |
| Chart | `data`, `series`: action/actionPicker=null | empty `recharts-responsive-container` |
| Sparkline | `data: action/actionPicker=null` | renders nothing |
| Tabs | `tabs: action/actionPicker=null` | one hard-coded placeholder tab, empty panel |
| Breadcrumb | `items: action/actionPicker=null` | `<nav><ol></ol></nav>` |
| KeyValueList | `items: action/actionPicker=null` | empty `<dl>` |
| ApprovalStepper | `steps: action/actionPicker=null` | empty `<ol>` |
| FilterBar | `chips`, `savedViews`: action/actionPicker=null | empty bordered bar |
| List / Tree / DescriptionList / SegmentedControl / Cascader / Carousel / Lightbox / ValidationChecklist / Stepper / Schematic | `binding: binding=null` | empty shell (DescriptionList: nothing at all) |
| SavedViewsPicker / BulkActionBar / KeyboardShortcuts / TourOverlay | `views` / `actions` / `shortcuts` / `steps` declared as **`string`** | render nothing — the component wants an array |
| Menubar | **no props at all** in the registry | empty bordered bar, nothing configurable |

Impact: ~25 of the 133 palette entries (19%) can be dropped but never filled in from inside the
editor. `Menubar` is the worst case — it has an empty `props: {}` in `starter.ts`, so the
properties panel has literally nothing to show for it.

### Components — Table / DataGrid / EditableLineGrid / Timeline / etc. — OK-ish (honest empty states)
Not every content-less component is invisible. `DataGrid` renders "No columns defined.",
`Timeline`/`ActivityFeed` "No activity yet.", `Kanban` "No items to display yet.",
`Heatmap` "No heatmap data.", `ResourceTimeline` "No resources to display",
`EditableLineGrid` "No line items. / Subtotal 0.00 / Total 0.00". These at least tell the user
what is missing. The BUG entries above are the ones that render *silence* instead.

---

## Props Tab (continued)

Continuation of the `## Props Tab` section above (appended at the file end so as not to clobber
other agents' sections).

### Props — the `binding` prop writes a path NOTHING reads (39 components) — BUG (severe)

The registry declares a prop literally named **`binding`** on **39 components**
(`control: "binding"`, `group: "data"`):
`Input, Textarea, Select, Checkbox, Switch, NumberInput, MoneyInput, MoneyDisplay, RadioGroup,
Slider, FileUpload, Combobox, TimePicker, ColorPicker, InputOTP, Rating, MaskedInput,
KeyValueInput, Gauge, SplitArc, Heatmap, Schematic, Stepper, DescriptionList, List,
SegmentedControl, Tree, Transfer, Cascader, Calendar, Kanban, RichTextEditor, Carousel, Lightbox,
QRCode, CameraCapture, BarcodeScanner, Scanner, ValidationChecklist`
(only `DatePicker` and `Repeat` use the runtime name `bind`).

**Write path.** `PropertiesPanel.tsx:249` resolves `CONTROL_BY_TYPE["binding"]` to
`BindingControl` (`PropControls/index.tsx:146`); its `onChange`
(`PropControls/BindingControl.tsx:178,212,351`) hands back a plain expression string, and
`PropertiesPanel.tsx:348-364` dispatches `updateProp { propName: "binding", value }`.
The BindToggle path (`PropertiesPanel.tsx:266-272`) writes `props.binding = { $binding: "" }`.
Both land on `node.props.binding`.

**Consumer: none.**
- The Zod props for every one of these nodes name the field **`bind`**, not `binding` — e.g.
  `C:\Users\user\a2ui\TentoroForge\packages\schema\src\nodes\inputs.ts:17,114,132,148,165,181,199,225,239,253,268,285`.
- `createRegistry().validateProps` (`packages/library/src/registry.ts:283-300`) parses props
  against those non-strict Zod schemas, so the unknown key `binding` is **silently dropped**
  before the component mounts. No `PROP_REMAP` entry maps `binding` to `bind`
  (`packages/library/src/registry.ts:55-120`).
- Grepping `packages/renderer`, `packages/library`, `packages/engine`, `packages/compiler` and
  `packages/ir` for a consumer of `props.binding` returns exactly one hit —
  `packages/library/src/components/Table/Table.schema.ts:18`, which **deletes** it.
- The compiler reads `node.bind`
  (`packages/compiler/src/emitters/inputs.ts:41,84,103,144,161,178,203,215,234,246,258`;
  `packages/ir/src/registry.ts:88,547`).

**The codebase already knows.**
`C:\Users\user\a2ui\TentoroForge\backend\services\library_manifest.py:680-691` says verbatim:

> `starter.json` is the visual EDITOR's property-panel catalog ... it advertises names like
> `binding` on 38 input components where the runtime prop is `bind`. Unioning them taught the
> page composer to emit `props.binding`, which Zod silently dropped — every composed edit form
> lost its prefill and rendered blank.

The backend was fixed to stop emitting `props.binding`. **The Props panel was not.** It is now
the only writer of a prop name no consumer accepts.

**Impact:** the "data" group of every input component in the editor is a no-op. Binding an Input,
Select, Checkbox or Slider from the Props tab appears to work, persists to the schema, survives
save, and does nothing — in the canvas, in the preview, and in the generated app.

### Props — `Container`: 6 of its 7 registry props are inert — BUG (severe)

`Container` is the most common layout node. The registry gives it
`direction, gap, padding, align, justify, wrap, maxWidth`
(`C:\Users\user\a2ui\TentoroForge\packages\registry\src\starter.ts:7-65`), all rendered as
`select`/`toggle` controls in the Props tab's **style** group.

The renderer reads **only** `maxWidth` (plus `className` / `style` / `shellRole`):
`C:\Users\user\a2ui\TentoroForge\packages\renderer\src\nodes\layout\Container.tsx:22-38` —
`const maxKey = node.props?.maxWidth ?? "lg"` and a fixed
`mx-auto w-full px-4 sm:px-6 lg:px-8 ${maxClass}`. There is no flex, no gap, no prop-driven
padding and no align/justify/wrap anywhere in the file. `Container` dispatches to that renderer
node, not to a library component (`packages/renderer/src/runtime/dispatch.tsx:174-175`; there is
no `packages/library/src/components/Container`). The schema agrees: `ContainerNode.props` is
`{ maxWidth }` and nothing else
(`C:\Users\user\a2ui\TentoroForge\packages\schema\src\nodes\layout.ts:86-99`).

**Probe evidence** (`probe_props_5.json` fetched from
`http://localhost:6503/p/gh0mlpbp/probe_props_5`, since deleted). Input:
`props: { direction:"horizontal", gap:"xl", padding:"xl", align:"center", justify:"between",
wrap:true, maxWidth:"sm" }`. Rendered:

    <div data-node-id="pp5" class="mx-auto w-full px-4 sm:px-6 lg:px-8 max-w-screen-sm">

Only `maxWidth` survived; the two child badges stayed stacked in normal flow.

**Impact:** a user sets Container direction to horizontal, gap to xl and alignment to center,
watches six controls accept the change, and the canvas never moves. `Stack`/`Row` are the nodes
that honour those props — the panel gives no hint of that.

### Props — registry prop names absent from the runtime contract — BUG

Same class as `binding` and `Container`, found by diffing every registry prop against the Zod
props of the matching node schema (77 components have a comparable schema). Props the **panel
offers and the runtime does not accept** — silently dropped by the non-strict Zod parse:

| Component | Offered by the panel, not in the runtime contract |
|---|---|
| `Container` | `direction, gap, padding, align, justify, wrap` (see above) |
| `Grid` | `rowGap, columnGap, padding, align` |
| `Input` | `binding, validation` |
| `Select` | `binding, multiple` |
| 37 other input/data components | `binding` (listed above) |

`Grid` belongs to another agent's file and is recorded here only for completeness.

### Props — props the runtime accepts but the panel never shows — GAP

The mirror image: fields in the node contract with **no registry descriptor**, so they have no
control at all and can only be set by hand-editing JSON. Notable ones:

| Component | Unreachable from the Props tab |
|---|---|
| `Input`, `Textarea`, `Select`, `Checkbox`, `Switch`, `NumberInput`, `RadioGroup`, `Slider`, `FileUpload`, `Combobox`, `TimePicker`, `ColorPicker`, `InputOTP`, `Rating`, `MaskedInput`, `KeyValueInput` | `name`, `bind`, `validators` — **`name` is what wires a field into its Form**, and it is invisible |
| `Chart` | `title, help, overlay, encoding, viewToggles, semanticColor` |
| `Section` | `illustration, padding, collapsible` |
| `MetricTile` | `trendWindow, breakdown, threshold` |
| `Heading` | `id, align` |
| `Hero` | `illustration` |
| `Heatmap` | `data, xKey, yKey, valueKey, rows, columns, min, max, cellSize` — every prop it has |
| `Schematic` | `grid, regions, markers, statusColors, heightPx` — every prop it has |
| `Stepper` / `Tree` / `List` / `Cascader` / `Transfer` | `steps` / `items` / `items` / `options` / `options, selected, titles` |
| `DescriptionList` | `items, emptyText, dataSource, itemMode, isLoading, skeletonRows` |
| `Select` / `Combobox` / `MultiSelect` | `optionsFrom` (the FK-dropdown source) |
| `Grid` | `equalRows, equalCols` |
| `PersonCard` | `manager` |
| `ActivityFeed` | `limit, fields` |
| `RadioGroup` / `SegmentedControl` | `options`, `orientation` |

`Heatmap` and `Schematic` are the extreme case: their registry entry contains a single prop
(`binding`) that nothing reads, and every prop they actually render from is absent — so the
Props tab for those two components is 100% inert.

Two components have **no props at all** in the registry: `GridCell` (intentionally — it is the
only `hidden: true` entry, `packages/registry/src/types.ts:44-51`) and `Menubar`.

### Props — enum options outside the consumer's accepted set — BUG

`Avatar.size` is declared `options: ["xs","sm","md","lg","xl"]` in the registry and the schema
accepts all five (`packages/schema/src/nodes/display.ts:19`), but the component's class map has
**only three entries**:

    const SIZE_CLASS: Record<string,string> = { sm:"h-8  w-8  text-xs", md:"h-10 w-10 text-sm", lg:"h-16 w-16 text-base" };
    ...
    const sizeCls = SIZE_CLASS[size ?? "md"] ?? SIZE_CLASS.md;

`C:\Users\user\a2ui\TentoroForge\packages\library\src\components\Avatar\Avatar.tsx:19-23,52`

**Probe evidence** (`probe_props_2.json` via `http://localhost:6503/p/gh0mlpbp/probe_props_2`,
since deleted): `size:"xs"` and `size:"xl"` both rendered
`class="... h-10 w-10 text-sm"` with `data-avatar-size="xs"` / `data-avatar-size="xl"` — i.e.
**identical to `md`**. Two of the five options in the dropdown are silent no-ops.

`ImageControl`'s own slot hint already documents this
(`frontend/src/lib/image-asset.ts:171-175` — `slotSizeFor` reports 40px for xs/xl): the fix went
into the hint, not into the option list.

`Tag.variant` is the reverse case: the registry offers
`[default, primary, success, warning, danger]` while the schema accepts `accent` too — a valid
variant with no way to select it.

### Props — `SelectControl` cannot express "unset" — BUG

`PropControls/index.tsx:72-87` renders only the descriptor's options: there is **no empty / "—"
option** and no clear button.

1. **An optional enum can never be cleared.** `Avatar.status` is documented in the registry as
   *"Presence indicator. Omit to hide."* with `default: "online"`. `defaultPropsFor`
   (`frontend/src/components/canvas/hooks/useDrop.ts:77-85`) materialises registry defaults
   verbatim, so every dropped Avatar arrives with `status: "online"` and a green dot the user
   cannot remove from the Props tab. The renderer's hide path (`Avatar.tsx:53`,
   `status ? STATUS_CLASS[status] : undefined`) is unreachable through the UI.
2. **"No override at this breakpoint" is unrepresentable.** `readPropAtBp`
   (`PropertiesPanel.tsx:36-40`) returns `undefined` for a breakpoint with no override;
   `SelectControl` coerces that to `value=""` (`:78`), which matches no `<option>`, so the
   control renders blank and the only way out is to *set* an override.

### Props — `NumberControl` turns "empty" into 0 and "-" into NaN — BUG

`PropControls/index.tsx:58-70`:

    value={typeof value === "number" ? value : 0}
    onChange={(e) => onChange(Number(e.target.value))}

- Clearing the field fires `Number("") === 0`, so a numeric prop can never be unset — it becomes
  a literal `0`.
- Typing a lone `-` or `1e` fires `Number("-") === NaN`, which is written into the schema and
  serialises to `null` on save.
- A prop that is currently `undefined` (unset, or no override at the active breakpoint) or a
  binding string **displays as `0`** even though the schema holds nothing — the control lies
  about the current value before the user touches it.

46 props use this control.

### Props — a breakpoint override on a prop with no base value renders raw JSON — BUG

`writePropAtBp`
(`C:\Users\user\a2ui\TentoroForge\frontend\src\components\properties\PropertiesPanel.tsx:43-56`)
wraps a non-default-breakpoint edit as `{ default: currentRaw, [bp]: newValue }`. When the prop
had **no** value yet, `currentRaw` is `undefined`, the `default` key disappears on
`JSON.stringify`, and the schema ends up holding `{ "lg": "..." }`.

`pickResponsiveValue`
(`C:\Users\user\a2ui\TentoroForge\packages\engine\src\responsive\useViewport.ts:55-60`) walks
`xl -> lg -> md -> sm -> default` from the active breakpoint; below `lg` every key is
`undefined`, the loop falls through, and it does `return value as T` — **the whole object**.

**Probe evidence** (`probe_props_4.json` via `http://localhost:6503/p/gh0mlpbp/probe_props_4`,
since deleted). `Heading.content = { "lg": "ONLYLGHEADING" }` and
`Badge.content = { "lg": "ONLYLGBADGE" }` rendered literally as
`{&quot;lg&quot;:&quot;ONLYLGHEADING&quot;}` and `{&quot;lg&quot;:&quot;ONLYLGBADGE&quot;}`.

**Impact:** switch the BreakpointSwitcher to `lg`, type a heading, and the page shows raw JSON at
every width below 1024px. The fix belongs in `writePropAtBp` (omit the wrapper / emit an explicit
`default`) or in `pickResponsiveValue`'s fall-through (return `undefined`, not the envelope).

### Props — responsive props ARE resolved at the default breakpoint — OK

The rest of the BreakpointSwitcher path is sound. `packages/engine/src/Engine.tsx:177-179` calls
`useViewport()` then `resolveTreeBreakpoint(root, bp)`, and `pickResponsiveValue`
(`packages/engine/src/responsive/useViewport.ts:43-60`) correctly refuses to treat
non-breakpoint objects (`{url, overlay}` on `Hero.backgroundImage`) as responsive — matching the
panel's own `isResponsiveShape` guard (`PropertiesPanel.tsx:16-20`).

**Probe evidence** (`probe_props_1.json`, since deleted): `Container.maxWidth =
{default:"sm", lg:"full"}` rendered `max-w-screen-sm` at the SSR default breakpoint, and
`Heading.content = {default:"BASEHEADING", lg:"LGHEADING"}` rendered `BASEHEADING`. The write
path is read — as long as a `default` exists (see the BUG above).

One cosmetic mismatch: the engine's `sm` breakpoint is **480px**
(`useViewport.ts:6-12`) while Tailwind's `sm:` — used in the very same components' classNames —
is 640px. The switcher's `sm` does not mean what the CSS around it means.

### Props — the write path (reducer) — OK

`updateProp` in `C:\Users\user\a2ui\TentoroForge\packages\patches\src\apply.ts:116-135` is a
plain assignment:

    const prev = node.props[action.propName];
    node.props[action.propName] = action.value;

**No falsy check anywhere.** Setting a prop to `""`, `0`, `false` or `null` persists exactly as
written, and the inverse action captures `prev` for a correct undo. `bindProp` (`:310-342`) and
`unbindProp` (`:347-378`) are likewise unconditional. `frontend/src/lib/editor-store.ts:146-183`
wraps the call in try/catch, runs `validateForCommit`, and only then commits. The classic
"can never clear a prop / can never set false" bug is **not** present.

Two limitations worth naming (not falsy-drops):
- `updateProp` writes `node.props[propName]` **flat** — the `setNestedValue`/`deleteNestedValue`
  helpers at `apply.ts:87-105` serve other actions, so a dotted `PropPath` would create a literal
  key containing a dot. No control emits one today.
- The BindToggle's un-bind passes `literalValue: descriptor.default ?? ""`
  (`PropertiesPanel.tsx:263`), so un-binding a prop whose registry default is `null` (most
  `actionPicker` props) writes the string `""` rather than clearing the prop.

### Props — nodes without an explicit `id` cannot be edited at all — BUG

`PropertiesPanel` deliberately supports id-less nodes: `syntheticNodeId` (`:75-82`) hashes
`type + JSON.stringify(props)` and `findNodeInArtifacts` (`:88-114`) matches on that, including
for legacy `{ children: [...] }` pages, which it wraps in a synthetic `Stack` root (`:94-97`).

The store does not. `applyAction` (`packages/patches/src/apply.ts:117-121`) calls
`findNode(page.root, action.nodeId)`, and `findNode` (`:24-56`) compares **`root.id === nodeId`**
only — no synthetic-id fallback — and is handed `page.root`, which a legacy `children`-format
page does not have.

So for such a node the panel renders every control correctly and **every edit throws**
`applyAction: unknown node "<synthetic id>"`, caught at `editor-store.ts:159-163` and parked in
`lastError`. Even if it matched, the synthetic id is derived from the props and would change on
the first successful edit.

Latent for the audited project (`output/gh0mlpbp/src/schemas/PAGE-001.json` — all 21 nodes carry
ids, page uses `root`), but a live hazard for anything from the legacy pipeline the panel goes
out of its way to support.

### Props — `ImageControl` — OK

Read in full
(`C:\Users\user\a2ui\TentoroForge\frontend\src\components\properties\PropControls\ImageControl.tsx`,
253 lines, plus its pure helpers in `frontend/src/lib/image-asset.ts`). Every write matches its
consumer, and the upload endpoint exists.

**Shape vs consumer — all five image props verified:**

| Prop | `imageShape` | `writeImageUrl` emits (`image-asset.ts:279-287`) | Consumer |
|---|---|---|---|
| `Avatar.photoUrl` | `url` | bare string | `packages/library/src/components/Avatar/Avatar.tsx:61` — `const imgSrc = photoUrl || src` |
| `Avatar.src` | `url` | bare string | same line (legacy fallback) |
| `PersonCard.avatarUrl` | `url` | bare string | `packages/library/src/components/PersonCard/PersonCard.tsx:38-39` |
| `Hero.backgroundImage` | `overlay` | `{ overlay: 0.4, ...prev, url }` | `packages/library/src/components/Hero/Hero.tsx:164-166,181` reads `.url` and `.overlay ?? 0.4` |
| `Hero.media` | `media` | `{ kind: "image", alt: "", ...prev, src }` | `Hero.tsx:197-201` switches on `media.kind === "image"` and reads `.src` / `.alt` |

The `kind: "image"` default matters: `Hero.tsx:201` renders an `<object type="image/svg+xml">`
for any other `kind`, and the control never emits one.

**The upload endpoint exists and is correctly addressed.** `ImageControl.tsx:124` posts to
`/api/projects/${projectId}/images`; the route is
`C:\Users\user\a2ui\TentoroForge\backend\routers\attachments.py:116-167` on a router with
`prefix="/api/projects"` (`:32`), mounted at `backend/main.py:206`. `_project_for_ref` (`:90-113`)
accepts **either** a DB UUID or a `short_id`, and the id the control receives is the short id
(`VisualEditorWorkspace.tsx:117` calls `setProjectId(projectId)` into
`editor-store.ts:143`), so the call resolves. `api.upload`
(`frontend/src/lib/api.ts:189-195` plus `:28-34`) correctly deletes the default `Content-Type`
for a `FormData` body. The returned `/api/asset/<short_id>/figma/<file>` URL is served by route
handlers that exist in **both** surfaces —
`frontend/src/app/api/asset/[projectId]/figma/[file]/route.ts` (editor, :6501) and
`apps/render-scaffold/src/app/api/asset/[projectId]/figma/[file]/route.ts` (preview, :6503) —
which is why `backend/services/project_assets.py` writes the bytes to both output roots.

**Clearing is correct too:** `writeImageUrl(..., "")` returns `""` for shape `url` and
`undefined` for `overlay`/`media`, because `{ url: "" }` would fail the schema's
`z.string().min(1)` (`image-asset.ts:273-281`). Both persist through the reducer unconditionally
(see the write-path finding).

Only nit: the URL text box commits on every keystroke (`ImageControl.tsx:249`), so typing a URL
pushes one undo entry per character — the same per-keystroke pattern already logged against the
Tokens and Bindings tabs.

### Props — summary: what a user cannot meaningfully set

1. **Array-of-object props (24)** — routed to `ActionPicker`, which reports them as "(no action)"
   and destroys them on interaction. Enumerated in the `actionPicker` finding above.
2. **`Tabs.tabs` / `TabPanelWithDeepLink.tabs`** — the worst instance: it gates whether panels
   render at all, and a second tab is unreachable without hand-editing JSON.
3. **Object props** — `EditableLineGrid.totals`, `Form.defaultValues`, `MetricTile.delta`,
   `EmptyStateRich.illustration`, and the four `AppShell` schema sub-trees: same dead control.
4. **Every `binding` prop (39 components)** — writable, read by nothing.
5. **All six non-`maxWidth` `Container` props** — writable, read by nothing.
6. **Props absent from the registry** — including `Input.name` (the field's Form wiring),
   `Select.optionsFrom`, and every prop of `Heatmap` and `Schematic`.
7. **Optional enums** — no "unset" option, so `Avatar.status` can never be hidden.
8. **Icon props (5)** — free text only, no picker, no validation.
9. **Nothing is hidden by a `hidden` flag.** `hidden` exists only on `RegistryEntry`
   (`packages/registry/src/types.ts:44-51`) and only `GridCell` sets it, which hides the
   *component* from the palette, not any prop. `PropDescriptor` has no `hidden` field, and the
   panel's only filter is the `group` bucketing at `PropertiesPanel.tsx:231-234` — a descriptor
   with a `group` outside `content|style|state|behavior|data` would vanish, but none has one.

### Props — errata / exact counts for the `actionPicker` finding

Precise breakdown of the 40 props declaring `control: "actionPicker"` (the earlier heading said
26; the correct figure is **25**):

- **10** are intercepted by name before reaching `ActionPicker` and get `BindingControl` instead
  (`PropertiesPanel.tsx:144-155`): `Breadcrumb.items, Chart.data, Sparkline.data, DataGrid.rows,
  EditableLineGrid.rows, Timeline.entries, CommandPalette.items, ActivityFeed.entries,
  MultiSelect.options, KeyValueList.items`.
- **5** are genuinely a single action and are correctly served: `Button.onClick,
  EmptyState.action, EmptyStateRich.primaryCta, EmptyStateRich.sampleDataLink, FeatureCard.cta`.
- **25** are arrays or plain objects with no usable editor: `Hero.ctas, MetricTile.delta,
  MetricTile.trend, Tabs.tabs, Table.columns, Form.fields, Form.defaultValues, AppShell.sidebar,
  AppShell.topbar, AppShell.actions, AppShell.rightRail, TabPanelWithDeepLink.tabs, Chart.series,
  DataGrid.columns, DataGrid.rowActions, EditableLineGrid.columns, EditableLineGrid.totals,
  TableSortable.columns, TableSortable.onSort, ApprovalStepper.steps, FilterBar.chips,
  FilterBar.savedViews, EmptyStateRich.illustration, DateRangePicker.presets,
  MultiSelect.selected`.

All probe schemas written for this audit (`probe_props_1` … `probe_props_5` under
`output/gh0mlpbp/src/schemas/`) have been deleted. `issueform.json` was never touched.
