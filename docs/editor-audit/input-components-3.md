# Input audit, round 3 — the last 17 components

SegmentedControl · Transfer · Cascader · Calendar · RichTextEditor ·
BarcodeScanner · CameraCapture · Scanner · AddToCart · BulkActionBar ·
SavedViewsPicker · GlobalSearch · SearchInput · KeyboardShortcuts ·
ThemeToggle · Wizard · FilterBuilder

Method, as rounds 1–2: contract diff (component Zod schema + `.tsx` vs. the
`starter.ts` registry entry), then a live editor session — new page
`/input-lab-3` in project `gh0mlpbp`, all 17 inserted from the palette, then
Props / Style / Bindings / Tokens exercised per node. `/items` and
`/input-lab-2` were left untouched.

`className` and `style` are EXCLUDED from "missing" counts throughout.

**Registry snapshot.** `packages/registry/src/starter.ts` was read at 16:04 and
**re-read at 16:38**, after the four concurrent fix agents landed and all six
packages were rebuilt. **Not one of these 17 entries changed** between the two
reads. The round-2 fixes (`useFieldValue`, the `{{expr}}` binding migration, the
`actionPicker` → `array`/`json` conversions) reached none of them. Every finding
below is against the post-fix tree.

Every claim is marked **VERIFIED** (I did it in the live editor and read the
result back) or **INFERRED** (read from source only). Browser evidence is DOM
probes via `javascript_tool`, not screenshots — `Page.captureScreenshot` timed
out repeatedly on this tab.

---

# The headline

These 17 are the unloved tail of the input library, and they fail differently
from rounds 1–2. Round 2's bug was **state**: components that could not hold a
value. Round 3's bug is **configuration**: components the editor cannot supply
data to at all — plus one infrastructure bug that breaks their layout.

**13 of 17 render empty, inert, or visibly wrong with registry defaults**, and I
measured every one of them. Two root causes account for eleven of the thirteen.

| # | root cause | components hit |
|---|---|---|
| **C1** | required list props typed `string`, edited with a text box, coerced to `[]` | 8 |
| **C2** | editor-canvas Tailwind CSS is missing utilities the library uses | 4 |
| **C3** | required props default to `""`, which is used rather than skipped | 3 |
| **C4** | canvas components install `document`-level listeners that capture the editor's own input | 3 |
| **C5** | fully parent-controlled with no state (round 2's C1 shape, unfixed) | 2 |
| **C6** | `name` declared, no named form control rendered | 5 |
| **C7** | props the editor cannot reach | 8 (24 props) |
| **C8** | dead props: exposed in the editor, ignored by the component | 2 |

---

# P0

## C1 — Eight required list props are typed `string` and edited with a one-line text box

The single largest defect of the round: one root cause, eight instances. Two
shapes.

**Shape A — the prop is not in the registry at all.** No control, no default,
so the component receives `[]` forever:

| component | prop | component schema |
|---|---|---|
| SegmentedControl | `options` | `z.array({value,label}).min(1)` — **required** |
| Transfer | `options` | `z.array({value,label}).min(1)` — **required** |
| Cascader | `options` | `z.array(recursive).min(1)` — **required** |

**Shape B — the prop *is* exposed, as `type:"string", control:"text",
default:""`,** where the component wants an array of objects:

| registry | prop | component schema |
|---|---|---|
| `starter.ts:3869` | `BulkActionBar.actions` | `z.array({label,workflow,variant}).min(1)` **required** |
| `starter.ts:3881` | `SavedViewsPicker.views` | `z.array({id,label,isDefault?}).min(1)` **required** |
| `starter.ts:3939` | `KeyboardShortcuts.shortcuts` | `z.array({keys,label,group?}).min(1)` **required** |
| `starter.ts:4093` | `Wizard.steps` | `z.array(WizardStep).min(1)` **required** |
| `starter.ts:4131` | `FilterBuilder.fields` | `z.array(FilterField).min(1)` **required** |

The descriptions even admit it — *"Array of {label, workflow, variant?} action
buttons (JSON)"* — but a `type:"string"` descriptor renders `TextControl`, a
one-line `<input type="text">` (`PropControls/index.tsx:30-43`). Whatever the
user types is written to the schema as a **string**, and `validateProps` step 3
then does this (`packages/library/src/registry.ts:378-381`):

```ts
if (er.code === "invalid_type" && exp === "array") {
  // Any non-array where an array is expected → [] so components never
  // crash on `.map` (e.g. Select/RadioGroup options, Table columns).
  setAtPath(coerced, er.path, []);
}
```

**The control that exists to fill the prop is the control that empties it.**
Same class as round 2's C2 (`ActionPicker` on array props), with a text box in
place of the action picker, and the same fix: `type:"array", control:"json"`
with a seeded default. The panel is already ready for it — round 2's D1
un-shadowing (`PropertiesPanel.tsx:182-188`) gives `AUTHORABLE_TYPES`
(`array`/`object`) their own control *and* the bind toggle. **None of these eight
use it.**

### Reproduction — VERIFIED end to end

1. `/input-lab-3`, palette → `SavedViewsPicker` → click. It renders a **520×24
   empty pill with zero buttons** (measured: `[data-forge-saved-views] button`
   count = **0**).
2. Props panel → `VIEWS`. Probed: `{"tag":"INPUT","type":"text","value":""}` —
   a single-line text field.
3. Typed `[{"id":"all","label":"All items"},{"id":"low","label":"Low stock"}]`
   into it, then Tab.
4. **Canvas unchanged.** Re-measured: node still `520×24`, `innerText` still
   `""`, button count still **0**.
5. Autosave wrote it to disk as a **string**:

```json
// output/gh0mlpbp/src/schemas/input-lab-3.json
{ "type": "SavedViewsPicker",
  "props": { "views": "[{\"id\":\"all\",\"label\":\"All items\"}…]",
             "activeViewId": "", "onSelectWorkflow": "" } }
```

The same file shows the other four still at their `""` defaults:
`"actions": ""`, `"shortcuts": ""`, `"steps": ""`, `"fields": ""`. And
`SegmentedControl`, `Transfer`, `Cascader` have no `options` key at all —
because the registry has no such prop to seed one from.

## C2 — The editor canvas is missing Tailwind utilities the library components depend on

**A new root cause, and it is not confined to these 17.** VERIFIED by probing
the live stylesheet.

The editor canvas's compiled CSS (`/_next/static/css/app/layout.css`, 144 rules
+ 97 inline) contains `.grid-cols-1` through `.grid-cols-6` — **and stops
there.** It has `.aspect-square` but no `.aspect-video`. It has fourteen
arbitrary `min-h-[…]` values but not `min-h-[6rem]`.

Enumerated from `document.styleSheets` (56 distinct grid/aspect/min/max rules
total):

```
.grid-cols-1 .grid-cols-2 .grid-cols-3 .grid-cols-4 .grid-cols-5 .grid-cols-6
.aspect-square
.min-h-[100px] .min-h-[120px] .min-h-[200px] .min-h-[2rem] .min-h-[400px]
.min-h-[40px] .min-h-[50px] .min-h-[60px] .min-h-[80px] …
```

No `grid-cols-7`. No `aspect-video`. No `min-h-[6rem]`.

Measured consequences on the real elements in the canvas:

| component | class it uses | computed | should be |
|---|---|---|---|
| **Calendar** | `grid grid-cols-7` | `grid-template-columns: 1148.41px` — **one column** | seven equal columns |
| **RichTextEditor** | `min-h-[6rem]` on the editable region | `min-height: 0px`, box is **1150×38** | ≥ 96px tall |
| **BarcodeScanner** | `aspect-video` on the preview | `aspect-ratio: auto`, box is **1150×22** | 16:9, ~1150×647 |
| **CameraCapture** | `aspect-video` on the preview | `aspect-ratio: auto`, box is **1150×22** | 16:9 |

Calendar is the visible disaster: the weekday headers `SUN MON TUE WED THU FRI
SAT` render **stacked one per row down the right edge**, followed by the day
numbers 1…30 also stacked vertically. The node measures **1150×1511** and
overflows its 520px drop box. Diagnosed precisely — the `SUN` cell's parent is
`<div class="grid grid-cols-7 border-b border-border bg-muted/30">` with 7
children, `display: grid` resolves correctly, and `grid-template-columns`
resolves to a single track. `grid` is in the stylesheet; `grid-cols-7` is not.

Note `min-w-[140px]` (Cascader) and `max-h-48` (Transfer) **are** present, so
this is not a clean "library sources aren't scanned" boundary — it is partial
coverage, which is worse, because it means the gap is invisible until a specific
component happens to be dropped. `grid-cols-7` is the standout: the **only**
consumer of a 7-column grid in the product is the calendar, which is exactly why
nothing else in the frontend pulled it into the build.

*(Scope: VERIFIED in the editor canvas. Whether the generated app's own Tailwind
build has the same gap is UNVERIFIED — I did not open a generated app.)*

## C3 — 13 of 17 render empty, inert, or wrong with registry defaults

VERIFIED — measured every node on `/input-lab-3` with nothing but palette
defaults. `data-node-id` wrapper dimensions and `innerText`:

| component | what a dropped node renders |
|---|---|
| **SegmentedControl** | `520×6` — a hairline. `[data-segmented-control] button` count = **0** |
| **Transfer** | `1150×63`, text `Available \| › \| ‹ \| Selected` — two empty panels, arrows that move nothing |
| **Cascader** | `520×24`, `innerText` empty — one empty column, plus the wrong empty-node hint (C3a) |
| **BulkActionBar** | **`[data-forge-bulk-action-bar]` is ABSENT from the DOM.** `selectedCount` defaults to `0` and `BulkActionBar.tsx:42` is `if (selectedCount === 0) return null;` |
| **SavedViewsPicker** | `520×24`, 0 buttons |
| **KeyboardShortcuts** | `innerText` empty — `KeyboardShortcuts.tsx:42` `if (!open) return <></>` |
| **Wizard** | stepper contains **only "1.Review"**; body reads *"Review your entries before submitting."*; the Next button is labelled **"Submit"** and `disabled=false`. `steps: []` ⇒ `total=0` ⇒ `reviewIdx=0` ⇒ `isReview` true at `stepIdx=0`, so **the wizard opens on its own review screen with an armed submit** |
| **FilterBuilder** | frame + "Add a filter…" — clicked it, `[data-forge-filter-clause]` count went **0 → 0**. Dead: `addClause()` early-returns on `!fields[0]` (`FilterBuilder.tsx:64-65`) |
| **Calendar** | renders, grid broken — C2 |
| **AddToCart** | button reads "Add to cart" and its React props are `onClick=fn disabled=true` — C4 |
| **Scanner** | renders; Scan button's React props are `onClick=undefined` — C5 |
| **GlobalSearch** | renders, but `workflow: ""` — C6 |
| **SearchInput** | renders, but `endpoint: ""` — C6 |

Only **RichTextEditor, BarcodeScanner, CameraCapture and ThemeToggle** are
usable from the palette, and three of those four have their own problems below.

`BulkActionBar` is the worst because it is *invisible*: the node is in the layer
tree, the canvas shows nothing, and there is no empty-node hint — the component
returned `null`, so the hint overlay has no box to attach to.

### C3a — The empty-node hint names the one prop that is not the problem

VERIFIED. Dropping a Cascader produces the overlay:

> **Cascader — set "bind" in the Properties panel.**

`bind` is *optional* (`Cascader.schema.ts:10`). The prop the component needs is
`options` — `.min(1)` **required**, and **absent from the registry**. The hint
is generated from the registry entry, so it can only name props the registry
knows about, and for these components the registry knows only the ones that do
not matter. The user is sent to bind a data path on a component that will still
render nothing afterwards. Worse than no hint.

## C4 — AddToCart drops in permanently disabled

VERIFIED — read off the React fiber of the live node:
`onClick=fn disabled=true`.

`AddToCart.tsx:96`:

```tsx
disabled={state === "loading" || !entity || itemId == null}
```

Registry defaults are `entity: ""` and `itemId: ""` (`starter.ts:3802-3803`),
confirmed on disk. `""` is falsy ⇒ `!entity` is true ⇒ **every freshly-dropped
AddToCart is a greyed-out, unclickable button.** Both props are required by
`AddToCart.schema.ts:17-18` with no `.default()`, so there is no value the
schema could have supplied.

---

# P1

## C5 — Scanner is fully parent-controlled with no state at all

VERIFIED — the live Scan button's React props are **`onClick=undefined`**. That
is round 2's dead-input signature, unfixed.

`Scanner.tsx` takes `value`, `status`, `statusMessage` as props and holds
**zero** `useState`. Its button is `onClick={onScan}`; `onScan` is not in the
schema, not in the registry, and the renderer passes only validated props
(`dispatch.tsx:352`). **The Scan button does nothing, forever.**

The Properties panel makes it legible in the worst way: `status` is an editable
`select` offering `idle | scanning | success | error`, so the *designer* can put
the component into "scanning" while the *end user* never can. It is a static
mock of a scanner dressed as a working one. `BarcodeScanner` is the real
implementation of the same idea.

`SegmentedControl` is the other half of this cause, quieter. `SegmentedControl.tsx:15-17`
gates on `value !== undefined` **alone** — the exact trap `useFieldValue.ts:29`
names as *the* anti-pattern, and the one round 2 explicitly flagged and did not
fix. It is harmless only because the registry exposes no `value`; the moment a
`defaultValue`/`value` prop is added (as round 2 did for nine other components)
it becomes the toggle that cannot be toggled.

## C6 — Two required strings default to `""`, and `""` is used rather than skipped

| component | prop | schema | registry default |
|---|---|---|---|
| GlobalSearch | `workflow` | `z.string().min(1)` **required** | `""` |
| SearchInput | `endpoint` | `z.string().min(1)` **required** | `""` |

Both are invalid on arrival (round 2's C6 class). But unlike a `null` array, an
empty *string* is consumed rather than skipped. **VERIFIED by driving each
component's own React `onChange` — exactly what a keystroke does — with a
`fetch` interceptor and a `MutationObserver` installed:**

```
props(searchInput).onChange({target:{value:'hammer'}})
props(globalSearch).onChange({target:{value:'drill'}})
→ { "fetches": ["?q=hammer"],
    "workflowButtons": [" args={\"query\":\"drill\"}"],
    "pageUrl": "http://localhost:6501/editor/gh0mlpbp" }
```

- `SearchInput.fetchResults()` (`SearchInput.tsx:50`) built `"" + "?" + "q=…"`,
  a **relative** URL. It resolved against the editor's own page — the component
  issues a search request against `/editor/gh0mlpbp`, every 300ms of typing.
- `GlobalSearch.fire()` (`GlobalSearch.tsx:44-50`) injected a
  `<button data-forge-workflow="">` into `document.body` and clicked it —
  dispatching a workflow whose **name is the empty string**, every 200ms.

A required prop defaulting to `""` is not "unset"; it is a live misconfiguration
that generates traffic and events. `null` would at least be skippable.

## C7 — Three canvas components install `document`-level listeners that capture the editor's own input

These are library components rendered live inside the editor canvas, and three
attach handlers to `document` / `documentElement` — so they capture input aimed
at the *editor*, not at the page being designed.

**ThemeToggle — VERIFIED, and it does not need to be clicked.**

Right after inserting it, with no interaction:

```
document.documentElement.dataset.theme → "light"   // the EDITOR's own <html>
```

Then clicking it (`element.click()`), and reading back:

```
before { html: "light", ls: null }
after  { html: "dark",  ls: "dark" }   // localStorage["forge-theme"] on the editor origin
```

`ThemeToggle.tsx:49` writes `document.documentElement.dataset.theme` in its
mount effect and `:57` persists to `localStorage` on click. **Merely dropping a
ThemeToggle on a page stamps an attribute on the editor's root element**, and
clicking it persists a preference to the editor's own origin that survives the
session. (I restored it to `light` afterwards.)

**KeyboardShortcuts — VERIFIED, with an important correction.** Dispatching a
`?` keydown on `document` with focus on `document.body` — what happens when a
user presses `?` anywhere in the editor outside a text field — opened the
overlay:

```
OVERLAY OPENED position=fixed inset=0px zIndex=1000 bg=rgba(0,0,0,0.4)
overlay rect = 1278 x 4983   (viewport 1525 x 678)
```

It obscures **the entire design canvas** — 4983px, the full canvas scroll
height. It does **not** reach the palette or the properties panel: I checked
`document.elementFromPoint` over the palette search box and got the palette's
own `INPUT`, not the overlay. `position: fixed` is trapped by the canvas's zoom
transform. So this is a P1 (the design surface disappears behind a scrim over a
stray keystroke), not the editor-lockout I first assumed. Escape closes it.

**GlobalSearch — VERIFIED, and the sharpest of the three.** With focus in the
**editor's own palette search box**, dispatching Ctrl+K on `document`:

```
focus before      = INPUT (placeholder "Search components…")
event.defaultPrevented = true
focus after       = INPUT (aria-label "Global search")
is GlobalSearch input? true
```

`GlobalSearch.tsx:29-39` calls `e.preventDefault()` and `inputRef.current.focus()`.
A component on the canvas swallowed the editor's keystroke and **stole keyboard
focus out of the editor chrome and into the page being designed**.

This is a class rounds 1–2 never hit, because none of their components touched
`document`. The fix is structural: the renderer knows whether it is in the
editor canvas or a real app, and global listeners plus `documentElement` /
`localStorage` writes must be inert in the former.

## C8 — Five components carry a `name` that submits nothing

VERIFIED live — queried `input[name], select[name], textarea[name]` inside each
node's `data-node-id` wrapper:

```
segmentedcontrol   namedControls = NONE
calendar           namedControls = NONE
richtexteditor     namedControls = NONE
scanner            namedControls = NONE
transfer           namedControls = NONE
```

Round 2's D3 found `Rating` had no named form control. Here it is five more
times, three of which declare `name` as a **required** schema field:

| component | what `name` is actually used for |
|---|---|
| **SegmentedControl** | only `aria-label={label ?? name}` (`SegmentedControl.tsx:21`); segments are `<button type="button">` |
| **Calendar** | destructured as `const { name: _name, … }` (`Calendar.tsx:137`) and **discarded**. `grep '<input' Calendar.tsx` → 0 hits |
| **RichTextEditor** | only `aria-label={label ?? name}` (`RichTextEditor.tsx:87`); the editable region is `contentEditable` — invisible to `FormData` by construction |
| **Transfer** | no `name` prop at all, no form control |
| **Scanner** | no `name` prop at all, no form control |

The Properties panel describes `name` as *"Form field name — the key this value
submits under"*, which is a false statement for all of them.

`BarcodeScanner` and `CameraCapture` are the counter-examples and the pattern to
copy: both render `<input type="hidden" name={name} value={…}>`, and both do so
**only once a value exists**, so an empty field cannot clobber a same-named
sibling (`BarcodeScanner.tsx:191-193`, `CameraCapture.tsx:130-137`). Their
`namedControls = NONE` reading above is correct and expected — no photo, no
barcode, no hidden field yet.

## C9 — Props the editor cannot reach

Counts exclude `className`/`style`; verified against the 16:38 registry.

| component | unreachable props | n |
|---|---|---|
| **Calendar** | `events`, `dateField`, `endDateField`, `titleField`, `colorField`, `eventHref`, `emptyText`, `view`, `detailFields`, `value` | **10** |
| **RichTextEditor** | `value`, `placeholder`, `mentions`, `embeds` | 4 |
| **Transfer** | `options`, `selected`, `titles` | 3 |
| **Scanner** | `scanLabel`, `value`, `statusMessage` | 3 |
| **BarcodeScanner** | `formats`, `autoSubmit` | 2 |
| **SegmentedControl** | `options` | 1 |
| **Cascader** | `options` | 1 |
| AddToCart · the eight Spec-C/E components | — | 0 |

Standouts:

- **Calendar is the largest contract gap in the whole 41-component library.**
  Its own schema comment calls event-calendar mode *"preferred for data views"*
  and documents nine props for it — `events`, `dateField`, `titleField`,
  `colorField`, `eventHref`, `view`, `detailFields`… — and **the editor exposes
  `name` and `bind`.** The entire event mode is unreachable; the editor can only
  produce the mode the schema itself labels *"(legacy)"*. The palette
  description says "Month-grid date picker", so the user is never told the other
  mode exists.

  This is also a **schema-layer** block, not just a registry one:
  `packages/schema/src/nodes/composite.ts:6-15` declares `CalendarNode.props` as
  `.strict()` with exactly `{ name, value, bind }`. Event mode is not
  expressible in a page schema at all.

- **`BarcodeScanner.autoSubmit` unreachable.** The component's own comment
  (`BarcodeScanner.tsx:88-89`) calls this *"scan-to-search: … so the user never
  has to press the button"*. On an inventory app, scan-to-search is *the* reason
  to put a barcode scanner on a page, and it cannot be turned on.

- **`Transfer.titles` unreachable** ⇒ the columns are permanently labelled
  "Available" / "Selected" in English, hardcoded at `Transfer.tsx:36,41`.
  Confirmed on the canvas.

## C10 — Dead props: exposed in the editor, ignored by the component

| prop | registry | component |
|---|---|---|
| `Cascader.placeholder` | `starter.ts:3358`, `control:"text"`, default `"Select…"` | **never destructured, never rendered** (`Cascader.tsx:13`) |
| `CameraCapture.className` | declared in `CameraCapture.schema.ts` | **not destructured** (`CameraCapture.tsx:18-26`); the root div hardcodes `className="flex flex-col gap-3"` |

VERIFIED for the first: the saved node carries `"placeholder": "Select…"` and
the rendered Cascader's `innerText` is `""` — the string appears nowhere.

`Cascader.placeholder` is the damaging one because it is the **only content prop
Cascader has**. A user configuring a Cascader sees exactly two controls — a
placeholder that does nothing, and a bind that will not populate it — and no way
to reach the one prop that matters.

---

# The state contract — all 17 classified

Against `packages/library/src/util/useFieldValue.ts`. **None of the 17 uses the
hook.** Four hold a field value at all.

| component | classification | named form control? |
|---|---|---|
| SegmentedControl | **conditionally controlled — the documented anti-pattern.** Gates on `value !== undefined` alone (`:15-17`); never re-seeds | **NO** |
| Transfer | self-managing (`useState(selected ?? [])`); never re-seeds from the prop | **NO** |
| Cascader | self-managing (`useState<string[]>([])`); no seed input at all | **NO** |
| Calendar | conditionally controlled, hand-rolled; `Calendar.tsx:151-162` seeds `selected` from `value` and re-syncs in an effect — the one component here that got the re-seed right | **NO** |
| RichTextEditor | **uncontrolled and write-only.** `value` is stamped into `innerHTML` once on mount (`:37-43`) and never again, so a panel edit to `value` is invisible until reload. Typing calls an `onChange` nobody passes, so the HTML lives only in the DOM | **NO** (contentEditable) |
| BarcodeScanner | self-managing (camera / file / native bridge all write it) | **yes**, conditional hidden input |
| CameraCapture | self-managing (uploads, stores the file id) | **yes**, conditional hidden input |
| Scanner | **fully parent-controlled, zero state — DEAD.** C5 | **NO** |
| AddToCart | self-managing (request lifecycle only) | n/a — a button |
| BulkActionBar | no value | n/a |
| SavedViewsPicker | **parent-controlled** (`activeViewId`, no state); clicking a view does not move the selection | n/a |
| GlobalSearch | **no value at all** — uncontrolled input, read only inside the debounce | n/a |
| SearchInput | self-managing (`useState("")`, publishes to `searchStore`) | n/a — not a form field |
| KeyboardShortcuts | self-managing (`open`) | n/a |
| ThemeToggle | self-managing (`theme`), persisted to localStorage | n/a |
| Wizard | self-managing (`values`, `stepIdx`); per-step fields **do** carry `name=` | **yes**, per-step |
| FilterBuilder | **uses `useUrlState`** (`:45`) — the only one in the set that persists to the URL | n/a |

Round 2's fix moved nine components onto one contract. These 17 are still on
five, and two (SegmentedControl, Scanner) are the exact shapes that hook was
written to kill.

---

# Panel-by-panel verdict

| tab | verdict |
|---|---|
| **Props** | The failure surface for this round — C1, C9, C10. Plain text props work correctly: typing `RFID reader` into `Scanner.LABEL` updated the canvas live (VERIFIED). Enum options were **not** truncated anywhere — `Scanner.deviceType`, `Scanner.status`, `AddToCart.variant/size`, `FilterBuilder.combinator` all match their Zod enums exactly. |
| **Style** | Works. Width / min-H / max-W are seeded at drop and write through to `node.style`. Six of these components declare `.strict()` schemas with no `className` key and hardcode large inline `style` objects, but each spreads `...styleProps` last, so Style-panel values do land. |
| **Bindings** | Round 2's `$binding` fix is holding — **zero render errors and zero issue badges across all 17 nodes.** The tab's empty state is correct and helpful: *"No bindings on this node. Use the bind toggle in the Props tab to wrap a value in `{{ … }}`."* And the per-prop bind toggles are present on every prop of every node, now with both `title` **and** `aria-label` (round 2's accessibility note is fixed): `"steps: literal value — click to bind to data"`. |
| **Tokens** | Works, unchanged — global panel, identical for all 17. |

---

# False positives I ruled out

Four things I chased that are not bugs. Each cost real time, and each would have
been wrong in the report.

1. **"`views: \"\"` will crash `SavedViewsPicker` on `views.find`."** It will
   not. `validateProps` step 3 (`registry.ts:378-381`) coerces any non-array in
   an array position to `[]` *before* the component sees it, so `.find` runs on
   an array. Same reasoning clears `shortcuts`, `actions`, `steps`, `fields`.
   The bug is silent emptiness, not a crash — which is why C1 is graded on data
   loss rather than render errors.

2. **"Nine components cannot be data-bound at all."** Retracted. Nine lack a
   component-level `bind` prop (`AddToCart`, `BulkActionBar`,
   `SavedViewsPicker`, `GlobalSearch`, `SearchInput`, `KeyboardShortcuts`,
   `ThemeToggle`, `Wizard`, `FilterBuilder`), which is what I first wrote up as
   a round-2-C5-style finding. But I then checked the Props panel on `Wizard`
   and found a bind toggle on **every** prop — `steps`, `title`, `submitLabel`,
   `onComplete`, `successRoute` all carry
   `title="…: literal value — click to bind to data"`. Per-prop `{{expr}}`
   binding is universal. The missing `bind` prop costs a convenience control,
   not the capability. Downgraded out of the findings entirely.

3. **"Every non-ASCII registry default is mojibaked on save."** No. Reading
   `output/gh0mlpbp/src/schemas/input-lab-3.json` showed
   `"placeholder": "Searchâ€¦"` — textbook UTF-8-as-Latin-1. It
   was **my** artifact: Python's `open()` defaults to cp1252 on Windows. The raw
   bytes are `"placeholder": "Search\xe2\x80\xa6"` — correct UTF-8 for `…`. No
   bug.

4. **"Typing in the Properties panel causes an infinite setState loop."** The
   console carried two `Error: Maximum update depth exceeded` exceptions with a
   clean stack — `PropControls/index.tsx:48 onChange` →
   `PropertiesPanel.tsx:603 onChange` → `editor-store.ts:156 dispatch` →
   zustand `setState` → `forceStoreRerender` — timestamped to the minutes I was
   typing into the panel. It looked like a P0. It is not: the stack names
   `PropertiesPanel.tsx:602-603` and that file is **485 lines long**. The loaded
   bundle was a concurrent agent's in-flight edit. I reloaded to pick up the
   current build, cleared the console, retyped into `Scanner.LABEL`, and got a
   correct live canvas update and **zero** console errors. Exactly the transient
   the brief warned about.

Also not reported, per the brief: selection loss and panel resets after Fast
Refresh (seen repeatedly while inserting), and the fact that clicking a canvas
input does not focus it — the canvas swallows the click for node selection,
which is correct design-mode behaviour, and is why C6 was verified by driving
the React `onChange` directly rather than by typing.

---

# Feature recommendations

1. **Convert all eight list props to `type:"array", control:"json"` with seeded
   defaults.** This is the round-1 `Select.options` fix applied to
   `SegmentedControl.options`, `Transfer.options`, `Cascader.options`,
   `BulkActionBar.actions`, `SavedViewsPicker.views`,
   `KeyboardShortcuts.shortcuts`, `Wizard.steps`, `FilterBuilder.fields`. It
   takes eight components from *unconfigurable* to *configurable* and the panel
   is already ready for it. Highest value single change in this report.

2. **Fix the editor-canvas Tailwind build, then add a regression guard.** The
   canvas CSS must cover every utility any library component uses. `grid-cols-7`
   alone is the difference between a working calendar and a vertical list of
   weekday names. A cheap guard: a test that scans `packages/library/src/**` for
   class literals and asserts each resolves in the built canvas stylesheet —
   this class of bug is silent, partial and completely invisible in review.

3. **A required-prop guard at drop time.** `buildDroppedNode`
   (`useDrop.ts:503`) already special-cases `name`; generalise it. When a prop
   is required by the component schema and the registry default is `""`/`null`,
   seed a working sample (two example segments, one example step) or refuse the
   drop with an explanation. A component whose first impression is a 6px
   hairline reads as broken software, not unconfigured software. Round 2's
   recommendation 6 (mark required props) is the weak half of this; seeding is
   the strong half.

4. **An editor-canvas rendering mode that neutralises global side effects.**
   `document.addEventListener`, `documentElement.dataset` writes and
   `localStorage` writes must be inert inside the canvas. Three of these 17
   currently reach out and modify the editor (C7) — one of them steals the
   editor's keyboard focus — and the class will recur with every future
   component that owns a shortcut or a theme.

5. **Fix Calendar's grid, then expose event mode** — at the registry *and* at
   `CalendarNode` in `packages/schema`. Ten unreachable props on the component
   whose own docs call the unreachable half "preferred" is the largest contract
   gap in the library. An inventory app that cannot plot stock deliveries on a
   month grid is missing the feature the component was built for.

6. **A hidden form control on every named input.** Five components (C8)
   advertise a `name` and submit nothing. Either give each the
   `BarcodeScanner.tsx:193` pattern, or drop `name` from their schemas so the
   panel stops promising a key that never appears. A required `name` with a
   description that is false is the worst of the three options.

7. **Move Scanner onto `useFieldValue`, or retire it.** As shipped it is a
   non-functional mock: a button wired to an `onScan` nothing can supply, and a
   status only the designer can change. `BarcodeScanner` is the working version
   of the same idea; the palette should not offer both as if they were peers.
   `SegmentedControl` should move onto the hook at the same time — it carries
   the anti-pattern round 2 documented and is one added prop away from failing.

8. **Distinguish "renders nothing on purpose" from "renders nothing because it
   is broken."** `BulkActionBar` returns `null` at `selectedCount === 0` — right
   in a shipped app, invisible in the editor. The canvas needs a design-time
   placeholder for components whose real behaviour is conditional; the same
   problem `SplitView.requireSelection` already hit in `containment.md`.

9. **Never default a required string to `""`.** `GlobalSearch.workflow` and
   `SearchInput.endpoint` (C6) generate live HTTP traffic and workflow events in
   their unconfigured state. `null` plus the recommendation-3 guard is strictly
   safer than an empty string that reads as a valid value everywhere downstream.

10. **Generate the empty-node hint from the component schema, not the registry
    entry.** The hint currently names whatever prop the registry happens to
    expose (C3a: *"set 'bind'"* on a Cascader that needs `options`). The Zod
    schema knows which props are required and which are missing; it is the
    correct source for the sentence.
