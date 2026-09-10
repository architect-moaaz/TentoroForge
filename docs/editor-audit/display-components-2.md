# Display audit, round 5 — the final 21 display components

Carousel · CodeBlock · DescriptionList · Dialog · FadeIn · Gauge · Heatmap ·
Kanban · Lightbox · List · QRCode · ResourceTimeline · Schematic ·
SearchResults · SplitArc · Stagger · Stat · Stepper · Tag · Tree ·
ValidationChecklist

Method, as rounds 1–4: contract diff (component Zod schema + `.tsx` vs. the
`starter.ts` registry entry, executed with `npx tsx` against the real modules),
then a live editor session — new page `/display-lab-5` in project `gh0mlpbp`,
all 21 inserted from the palette, then Props / Style / Bindings / Tokens
exercised. `/items`, `/ops-dashboard`, `/stock-intake`, `/input-lab-2`,
`/input-lab-3` and `/display-lab-4` were left untouched, and tab `2076428868`
was never used — this session ran in its own tab.

`className` and `style` are EXCLUDED from "missing" counts throughout.

Every claim is marked **VERIFIED** (I did it in the live editor / executed it
against the real source modules and read the result back) or **INFERRED** (read
from source only). Browser evidence is `javascript_tool` DOM probes —
`getBoundingClientRect` / `getComputedStyle` / the persisted page JSON — not
eyeballed screenshots.

Nothing already fixed by the post-round-4 fix pass is re-reported: the 35
`actionPicker` conversions, the ~39 added registry props, `normalizeSeed`,
`ActivityFeed.maxHeight`, the three added `style` supports, icon resolution and
the canvas `@source` globs are all excluded, and where a fix landed I say so.

> **Line-number caveat.** `packages/registry/src/starter.ts` grew **298 lines
> under me** during this session (a concurrent fix agent), and
> `packages/schema/src/nodes/composite.ts` gained 30. I re-read every one of
> the 21 entries at the end of the session: **not one of them changed** — the
> prop keys are identical, `carouselEntry`/`lightboxEntry`/`treeEntry` still
> have an empty `props: {}`. All `starter.ts` line numbers below are the
> **post-edit** ones (re-resolved by grep at the end of the session); the
> browser observations were made against the earlier build, which carried the
> same entries.

---

# P0 / P1 SUMMARY — dispatchable, one line each

Format: `target — symptom — file:line — fix`. **[REGISTRY-ONLY]** marks a fix
that is a single edit to `packages/registry/src/starter.ts` and nothing else.

## P0

| # | target | symptom | file | fix |
|---|---|---|---|---|
| 1 | `Carousel` — **no props at all** | `carouselEntry.props` is `{}`. Dropped node renders an **empty 960×45 div**. `CarouselNode.props.items` is `.min(1)` **required** → the saved page **fails `PageV2`**. | `starter.ts:3759-3767`; `schema/src/nodes/composite.ts:80-91` | **[REGISTRY-ONLY]** add `items: { type:"array", control:"json", group:"content", default:[{title:"Slide one",caption:"…"},{title:"Slide two"}] }` |
| 2 | `Lightbox` — **no props at all** | `lightboxEntry.props` is `{}`. Dropped node renders a **960×0** div (zero height). `LightboxNode.props.images` `.min(1)` required → **fails `PageV2`**. | `starter.ts:3769-3777`; `composite.ts:94-105` | **[REGISTRY-ONLY]** add `images: { type:"array", control:"json", default:[{src:"…",alt:"…"}] }` |
| 3 | `Tree` — **no props at all** | `treeEntry.props` is `{}`. Dropped node renders an **empty `<ul>` 960×200, 0 children**. `TreeNode.props.items` required → **fails `PageV2`**. | `starter.ts:3477-3484` | **[REGISTRY-ONLY]** add `items: { type:"array", control:"json", default:[{label:"Root",children:[{label:"Child",value:"c1"}]}] }` |
| 4 | `DescriptionList.items` missing | registry exposes **only `orientation`**. With no `items` and no `emptyText` the component **`return null`** — the node is **`kids=0`**, an invisible 960×96 box. Also **fails `PageV2`** (`props.items: Required`). | `starter.ts:3420-3429`; `DescriptionList.tsx:37-38` | **[REGISTRY-ONLY]** add `items` (json), `emptyText` (text), `dataSource`, `itemMode` |
| 5 | `List.items` missing | registry exposes **only `divided`**. Renders an **empty bordered `<ul>`**, `inner=0`. **Fails `PageV2`** (`props.items: Required`). | `starter.ts:3431-3439` | **[REGISTRY-ONLY]** add `items: { type:"array", control:"json", default:[{title:"First item",subtitle:"Subtitle"},{title:"Second item"}] }` and `limit` |
| 6 | `ValidationChecklist.items` missing | registry exposes **only `orientation`**. Renders an **empty div**, `inner=0`. **Fails `PageV2`** — `ValidationChecklistNode.props.items` is `.min(1)`. | `starter.ts:3886-3895`; `device.ts:35-47` | **[REGISTRY-ONLY]** add `items: { type:"array", control:"json", default:[{label:"Has a SKU",valid:true},{label:"Price set",valid:false}] }` |
| 7 | `Stepper.steps` missing | `StepperProps.steps` is **required** (`z.array(StepperStep)`, no `.optional()`, no `.default()`) and the registry exposes only `orientation`/`activeStep`/`bind`. Renders an **empty 960×24 div**. **Fails `PageV2`**. | `starter.ts:3377-3390` | **[REGISTRY-ONLY]** add `steps` (json) + `activeId` (text) |
| 8 | `Kanban.columns`/`data` missing | registry exposes **only `bind`** — 11 schema props unreachable. `KanbanNode.props.columns` is `.min(1)` **required** → **fails `PageV2`**. Renders the "No items to display yet." placeholder. | `starter.ts:3674-3683`; `composite.ts:18-34` | **[REGISTRY-ONLY]** add `columns` (json, seeded), `data`, `groupBy`, `cardTitle`, `emptyText` |
| 9 | `Heatmap.data` missing | registry exposes only `color`/`showValues`/`bind` — **9 props unreachable including `data`**. Renders the dashed "No heatmap data." placeholder forever. | `starter.ts:3350-3361` | **[REGISTRY-ONLY]** add `data` (json), `xKey`, `yKey`, `valueKey`, `cellSize`, `min`, `max` |
| 10 | `Schematic.markers`/`regions` missing | registry exposes only `width`/`height`/`showLabels`/`bind`. `markers` is the required data prop; `regions`, `statusColors`, `grid`, `heightPx` all unreachable. Renders an **empty SVG**. | `starter.ts:3363-3375` | **[REGISTRY-ONLY]** add `markers` (json), `regions` (json), `statusColors` (json), `grid`, `heightPx` |
| 11 | `SplitArc.segments` is a **binding-only control on a required array** | `SplitArcProps.segments` is `z.array(...).min(1)` **required**, and the registry declares it `type:"binding", default:null`. There is **no way to author segments literally**. `validateProps` coerces `null → []`, so the arc renders with no segments. | `starter.ts:3333-3348`; `SplitArc.schema.ts:28` | **[REGISTRY-ONLY]** change to `type:"array", control:"json"`, default `[{value:62,color:"#2563eb",label:"Received",endLabel:"2.15 kW"},{value:38,color:"#f59e0b",label:"Costs"}]` |
| 12 | `Dialog` renders **nothing** in the canvas, and **swallows its children** | The editor mounts **no `DialogStateProvider`**, so `ctx` is `null`, `open` is `false`, the Radix Portal renders nothing. The node measures **0×0, `kids=0`**. A `FadeIn` I inserted while Dialog was selected was persisted as `Dialog > FadeIn` and **never appeared on the canvas at all**. | `Dialog.tsx:37-40`; no `DialogStateProvider` anywhere in `frontend/src` | design-time override: force `open` when rendering inside the editor canvas, or give the canvas a `DialogStateProvider` with a per-node "open in editor" toggle |
| 13 | `bind: null` **silently disables the entire props validation** for 7 of 21 | `type:"binding", default:null` is persisted as `bind: null`, but every schema types it `z.string().optional()`. `null ≠ undefined`, so step-1/2 fail, step-3's coercion table has **no `received:"null"` branch**, and `validateProps` returns the **raw uncoerced props**. Every Zod `.default()` on that component is skipped. Hits **Gauge, Heatmap, Kanban, ResourceTimeline, Schematic, SplitArc, Stepper** here and **30 registry entries repo-wide**. | `starter.ts` ×30; `library/src/registry.ts:374-397`; `useDrop.ts:145-153` | either change every `default: null` to `default: undefined` **[REGISTRY-ONLY]**, or make `defaultPropsFor` filter `null` too, or add a `rec === "null"` branch to the step-3 table |
| 14 | `CodeBlock.code: ""` on a `.min(1)` page-schema prop | `CodeBlockNode.props.code` is `z.string().min(1)`; the registry seeds `""` → **`too_small`, fails `PageV2`**. Renders an empty black block. | `starter.ts:3786`; `composite.ts:107-117` | **[REGISTRY-ONLY]** seed a sample snippet, e.g. `default: "const total = items.length;"` |
| 15 | `QRCode.value: ""` on a `.min(1)` page-schema prop | `QRCodeNode.props.value` is `z.string().min(1)`; the registry seeds `""` → **`too_small`, fails `PageV2`**. Renders a scannable QR encoding the empty string. | `starter.ts:3799`; `composite.ts:119-128` | **[REGISTRY-ONLY]** seed `"https://example.com"` |
| 16 | `ResourceTimeline` — three `type:"string", default: null` props | `statusField`, `resourceGroupField`, `itemHref` are seeded `null` against `z.string().optional()` → **fails `ResourceTimelineNode`** and therefore `PageV2`. These are the **only three `type:"string", default:null` descriptors in the whole registry.** | `starter.ts:3698-3701`; `composite.ts:37-63` | **[REGISTRY-ONLY]** drop the `default` key on all three |

**16 of 21 palette-dropped nodes write page JSON that `PageV2.safeParse`
rejects** (VERIFIED against the real autosaved file — see C1).

## P1

| # | target | symptom | file | fix |
|---|---|---|---|---|
| 17 | `ResourceTimeline` never calls `resolveStyle` | it spreads the **raw `StyleSlot`** into React's `style`, so `background: "color.primary.500"` and `padding: "spacing.8"` reach the DOM as invalid CSS and are dropped, and `motion` leaks in as a bogus CSS property. It is the only component in the set that imports neither `resolveStyle` nor `useMotion`. | `ResourceTimeline.tsx:115, 127-135` (no `resolveStyle` import at all) | import `resolveStyle` and wrap both `style={style}` sites |
| 18 | `ValidationChecklist` destructures `className` and never uses it | `className` is pulled off the props at `:15` and the root renders `className={rootCls}` only. Style/class authoring is silently dropped. | `ValidationChecklist.tsx:15, 27` | `className={\`${rootCls} ${className ?? ""}\`}` |
| 19 | `className` declared in the schema, never destructured — 5 components | `Gauge`, `Heatmap`, `Schematic`, `SplitArc`, `Stepper` all declare `className: z.string().optional()` and none of them accepts it. | `Gauge.tsx:35`, `Heatmap.tsx:19-23`, `Schematic.tsx:28-31`, `SplitArc.tsx:47-56`, `Stepper.tsx:39` | destructure and concatenate |
| 20 | `FadeIn` / `Stagger` **drop `style` entirely** when motion is off | at `motionLevel: "none"` both `return <>{children}</>` before `resolveStyle(style)` is ever called. Every Style-panel value on a FadeIn/Stagger vanishes for any app whose motion token is `none`. | `FadeIn.tsx:33-35`; `Stagger.tsx:37-39` | wrap the children in a styled `<div>` in the disabled branch too |
| 21 | `Tag` implements an `accent` variant nothing can express | `VARIANT_CLASS.accent` exists and is commented at length, but `TagProps.variant` is a 5-value enum without it and the registry options match. Exactly round 4's `Badge` C5c, in the sibling component. | `Tag.tsx:16`; `Tag.schema.ts:4`; `starter.ts:3400` | add `"accent"` to the Zod enum and the registry `options` |
| 22 | `Gauge.thresholds` unreachable | the entire threshold-zone feature — the thing that distinguishes `Gauge` from `Progress` — has no control. Also `size` and `showValue`. | `starter.ts:3317-3331` | **[REGISTRY-ONLY]** add `thresholds` (json), `size`, `showValue` |
| 23 | `SplitArc.stroke` unreachable | the only `SplitArc` prop with no control. | `starter.ts:3333-3348` | **[REGISTRY-ONLY]** add `stroke` (number) |
| 24 | `ValidationChecklist.orientation` enum order differs from the Zod enum | Zod is `["horizontal","vertical"]`, registry `options` is `["vertical","horizontal"]`. Both values are valid so nothing breaks, but the *first* option (the one a reset lands on) differs from the schema's first. The only enum divergence in the set. | `ValidationChecklist.schema.ts:5`; `starter.ts:3893` | **[REGISTRY-ONLY]** align the order |
| 25 | `QRCode.label` unreachable | the caption under the code has no control. | `starter.ts:3792-3802` | **[REGISTRY-ONLY]** add `label` |
| 26 | `ResourceTimeline` — 7 props unreachable | `resourceIdField`, `resourceLabelField`, `resourceSubField`, `subtitleField`, `rangeStart`, `emptyText`, `bind`. `rangeStart` in particular means the grid **always starts at today** and cannot be pointed at a historical or future window. | `starter.ts:3685-3703` | **[REGISTRY-ONLY]** |
| 27 | The empty-node hint on `Stepper` names **`bind`**, the one prop that is not the problem | round 3's C3a, unfixed and recurring. VERIFIED on the canvas: the overlay reads *"Stepper — set “bind” in the Properties panel."* `bind` is `z.string().optional()`; the prop the component needs is **`steps`**, required and absent from the registry. | round 3 C3a; `starter.ts:3377-3390` | generate the hint from the component's Zod schema, not the registry entry |
| 28 | The empty-node hint on the other five names **no prop at all** | VERIFIED: Carousel / DescriptionList / List / Tree / ValidationChecklist all get an overlay that just repeats the **palette description** (*"Carousel — Slideshow with prev/next and dots."*). It tells the user nothing about what to fill in — because the registry has no descriptor for the missing prop. | same | same |
| 29 | `Lightbox` and `Dialog` get **no hint at all** | VERIFIED: Lightbox measures 960×**0** and Dialog 0×0, so the hint overlay has no box to attach to. They are the two nodes in the set that are invisible *and* undiagnosable — round 3's `BulkActionBar` failure, twice. | `Lightbox.tsx:32-40`; `Dialog.tsx:57-59` | give the canvas a min-height for zero-box nodes, or attach the hint to the dispatcher wrapper |

---

# The headline

Rounds 1–3 were about inputs that could not hold a value. Round 4's bug was that
the registry's own seed values were the payload. **Round 5's bug is that for a
third of the display library there is no seed and no control at all** — the
registry entry is empty, or holds a cosmetic knob and nothing else, and the one
prop the component exists to render is unreachable from the editor.

**Three components — Carousel, Lightbox and Tree — have a literally empty
`props: {}` registry entry.** Their Props panel shows the node name and nothing
else. And because the page schema declares those same props `.min(1)` required,
those nodes are not merely unconfigurable — they are unrepresentable.

| # | root cause | severity | components hit |
|---|---|---|---|
| **C1** | the editor cannot author the one prop the component exists to show | **P0** | 8 |
| **C2** | `bind: null` silently disables the whole props validation | **P0** | 7 (30 registry-wide) |
| **C3** | the editor writes page JSON that `PageV2` rejects | **P0** | **16** |
| **C4** | Dialog renders nothing and hides its children | **P0** | 1 |
| **C5** | `style` reaches the component and is dropped or applied unresolved | **P1** | 3 |
| **C6** | `className` declared and ignored | **P1** | 6 |
| **C7** | `Tag.accent` is implemented and unreachable | **P1** | 1 |
| **C8** | props the editor cannot reach | **P1** | 17 (52 props) |
| **C9** | the empty-node hint names the wrong prop, or no prop | **P1** | 6 |
| **C10** | *(clean)* zero React warnings, zero console errors | — | — |

**29 distinct defects.** 16 are P0.

**12 of 21 render blank, empty, or as a placeholder with nothing but registry
defaults**, and I measured every one. **16 of 21 write page JSON the project's
own schema rejects** — round 4 found 2.

The good news, stated up front and all VERIFIED: **no dead props anywhere in
this set** (rounds 3 and 4 both found some), **no wrong control for a type**,
**no missing Tailwind utilities** (round 3's C2 stays fixed), **no React key
warnings** (round 4's C6 does not recur — `Stepper` uses the guarded
`step.id ?? i` form the last round asked for), **zero console errors of any
kind**, and the Bindings surface is intact on every prop the registry declares.

---

# Per-component contract table

Produced by `npx tsx` against the real `packages/library` schema modules and the
real `starterRegistry` (INFERRED-by-execution), then confirmed on the canvas
(VERIFIED). `seed → PageV2` is `PageV2.safeParse` run over the **actual
autosaved** `output/gh0mlpbp/src/schemas/display-lab-5.json`.

| component | schema keys (excl. className/style) | required | missing from editor | dead props | renders on drop | seed → PageV2 | reads `style`? |
|---|---|---|---|---|---|---|---|
| **Carousel** | items | — | **items** | — | **empty 960×45 div** | **FAIL** `props.items: Required` | yes |
| **CodeBlock** | code, language, showCopy | — | — | — | black block, empty `<pre>` | **FAIL** `props.code: too_small` | yes (outer div only) |
| **DescriptionList** | items, dataSource, itemMode, emptyText, orientation, isLoading, skeletonRows | — | **items**, dataSource, itemMode, emptyText, isLoading, skeletonRows | — | **nothing — `return null`** | **FAIL** `props.items: Required` | yes |
| **Dialog** | id, title, description, size | **id** | — | — | **nothing — 0×0, children invisible** | OK | yes |
| **FadeIn** | delay, duration | — | — | — | wrapper, 960×0 empty | OK | **only when motion enabled** |
| **Gauge** | value, min, max, label, unit, thresholds, size, showValue, bind | — | thresholds, size, showValue | — | correct dial, "72% Utilization" | **FAIL** `props.bind: null` | yes |
| **Heatmap** | data, xKey, yKey, valueKey, rows, columns, color, min, max, showValues, cellSize, bind | — | **data**, xKey, yKey, valueKey, rows, columns, min, max, cellSize | — | "No heatmap data." placeholder | **FAIL** `props.bind: null` | yes |
| **Kanban** | data, groupBy, columnOrder, cardTitle, cardDescription, cardBadge, cardFields, cardHref, columns, moveBetweenLanes, emptyText, bind | — | **all 11 except bind** | — | "No items to display yet." | **FAIL** `props.columns: Required`, `props.bind: null` | yes |
| **Lightbox** | images | — | **images** | — | **960×0 — zero height** | **FAIL** `props.images: Required` | yes |
| **List** | items, divided, limit | — | **items**, limit | — | **empty bordered `<ul>`** | **FAIL** `props.items: Required` | yes |
| **QRCode** | value, size, label | — | label | — | QR of the empty string | **FAIL** `props.value: too_small` | yes |
| **ResourceTimeline** | resources, resourceIdField, resourceLabelField, resourceSubField, resourceGroupField, items, itemResourceField, startField, endField, titleField, subtitleField, statusField, itemHref, rangeStart, days, emptyText, bind | — | resourceIdField, resourceLabelField, resourceSubField, subtitleField, rangeStart, emptyText, bind | — | "No resources to display" | **FAIL** ×3 `null` strings | **raw — no `resolveStyle`** |
| **Schematic** | width, height, grid, regions, markers, statusColors, showLabels, heightPx, bind | — | grid, regions, **markers**, statusColors, heightPx | — | **empty SVG, 960×520** | **FAIL** `props.bind: null` | yes |
| **SearchResults** | hrefPattern, skeletonRows, pristineText, emptyText | — | — | — | pristine copy — **correct** | **OK** | yes |
| **SplitArc** | segments, total, title, size, stroke, showLegend, showEndLabels, bind | **segments** | stroke | — | title + empty arc track | OK (no strict shape) | yes |
| **Stagger** | delay, interval | — | — | — | wrapper; **children render** | **OK** | only when motion enabled |
| **Stat** | label, value, delta, trend, caption | — | — | — | "Metric / 0" — **correct** | **OK** | yes |
| **Stepper** | steps, orientation, activeStep, activeId, bind | **steps** | **steps**, activeId | — | **empty 960×24 div** | **FAIL** `props.steps: Required`, `props.bind: null` | yes |
| **Tag** | label, variant, removable | — | — | — | "Tag" pill — **correct** | **OK** | yes |
| **Tree** | items | — | **items** | — | **empty `<ul>`, 0 children** | **FAIL** `props.items: Required` | yes |
| **ValidationChecklist** | items, orientation | — | **items** | — | **empty div, 0 children** | **FAIL** `props.items: Required` | yes, but `className` is dead |

**No dead props in this set** — every registry descriptor maps to a real schema
key. That is a clean result and worth recording: rounds 3 and 4 both found dead
props, this one has none.

**One enum divergence** (ValidationChecklist.orientation ordering) and **no
wrong controls for a type** among the props the registry does expose. Every
failure in this round is a prop the registry *omits*, or a `default` that is the
wrong value — never a control mismatch.

---

# P0 — root causes

## C1 — The editor cannot author the one prop these components exist to show

**Eight components** (Carousel, Lightbox, Tree, DescriptionList, List,
ValidationChecklist, Stepper, Kanban) have a single prop that carries all their
content, and **the registry exposes no control for it.** Three of them —
`carouselEntry`, `lightboxEntry`, `treeEntry` — have a literally **empty props
object**:

```ts
// packages/registry/src/starter.ts:3759
export const carouselEntry: RegistryEntry = {
  name: "Carousel", category: "display", icon: "GalleryHorizontal",
  description: "Slideshow with prev/next and dots.",
  slots: { type: "leaf" },
  props: {
  },
};
```

`lightboxEntry` (`:3769`) and `treeEntry` (`:3477`) are the same shape.

This is round 3's C1 shape A — *"the prop is not in the registry at all"* — but
it is **worse here**, because for six of the eight the page schema declares that
prop **required and `.min(1)`**, so the node is not merely unconfigurable, it is
**unrepresentable**:

```ts
// packages/schema/src/nodes/composite.ts:80-91
export const CarouselNode = z.object({
  type: z.literal("Carousel"),
  props: z.object({
    items: z.array(z.object({ image, title, caption }).strict()).min(1),
  }).strict(),
  …
}).strict();
```

`LightboxNode.images` (`:94-105`), `KanbanNode.columns` (`:18-34`),
`ValidationChecklistNode.items` (`device.ts:35-47`) are all `.min(1)`;
`DescriptionListNode.items`, `ListNode.items`, `TreeNode.items` and
`StepperNode.steps` are all required.

### Reproduction — VERIFIED end to end

1. New page **`/display-lab-5`**, project `gh0mlpbp`.
2. Palette search → click each of the 21. All 21 inserted; the persisted page
   confirms it.
3. Measured every node on the live canvas
   (`[data-node-id]` wrapper, its first element child, and that child's own
   child count):

```
carousel             span=960x45  child=DIV  960x45  inner=1  txt=""
descriptionlist      span=960x96  kids=0     child=-          txt=""     ← returned null
dialog               span=0x0     kids=0     child=-          txt=""     ← rendered nothing
lightbox             span=0x0     child=DIV  960x0   inner=1  txt=""     ← zero height
list                 span=960x278 child=UL   960x278 inner=0  txt=""     ← empty <ul>
stepper              span=960x24  child=DIV  960x24  inner=0  txt=""
tree                 span=960x200 child=UL   960x200 inner=0  txt=""
validationchecklist  span=960x125 child=DIV  960x125 inner=0  txt=""
heatmap              child=DIV 960x238  txt="No heatmap data."
kanban               child=DIV 960x345  txt="No items to display yet."
resourcetimeline     child=DIV 960x520  txt="No resources to display"
schematic            child=DIV.w-full 960x520  inner=1  txt=""          ← empty <svg>
searchresults        child=DIV 960x520  txt="Search across your data."  ← correct
gauge                child=DIV 403x252  txt="72%Utilization"            ← correct
stat                 child=DIV 403x252  txt="Metric0"                   ← correct
tag                  child=SPAN 41x20   txt="Tag"                       ← correct
splitarc             child=DIV 403x252  txt="Energy Balance Today"      ← title only, empty arc
qrcode               child=DIV 128x128  inner=1                         ← QR of ""
codeblock            child=DIV 960x90   txt="Copy"                      ← empty <pre>
```

4. **The persisted page confirms the props are simply absent.** From
   `output/gh0mlpbp/src/schemas/display-lab-5.json`, written by the editor while
   I worked:

```json
{ "type": "Carousel",            "id": "carousel-v9yyxz",            "props": {} }
{ "type": "Lightbox",            "id": "lightbox-j4buei",            "props": {} }
{ "type": "Tree",                "id": "tree-y3amhl",                "props": {} }
{ "type": "DescriptionList",     "id": "descriptionlist-fyy7tv",     "props": {"orientation":"vertical"} }
{ "type": "List",                "id": "list-fhdgf8",                "props": {"divided":true} }
{ "type": "ValidationChecklist", "id": "validationchecklist-5ihpre", "props": {"orientation":"vertical"} }
{ "type": "Stepper",             "id": "stepper-hiv3zh",             "props": {"orientation":"horizontal","activeStep":0,"bind":null} }
{ "type": "Kanban",              "id": "kanban-tqdgun",              "props": {"bind":null} }
```

**`props: {}`.** Three components in the display palette produce a node with no
props at all, and no Props-panel control exists that could ever give them one.

**Twelve of these twenty-one render blank, empty, or as a placeholder with
nothing but registry defaults.** The brief's catalogue sweep said only 4
components in the whole product render nothing and all 4 are config-driven
builtins; that is not what the canvas shows for this set.

### The worst of them: DescriptionList returns `null`

`DescriptionList.tsx:37-38`:

```tsx
if (rows.length === 0 && !props.isLoading) {
  if (!emptyText) return null;
  …
}
```

The registry seeds neither `items` nor `emptyText`, so the component returns
`null`. VERIFIED: the node's `data-node-id` wrapper has **`childElementCount ===
0`** — it is a 960×96 empty box in the layer tree with no DOM under it at all.
This is round 3's `BulkActionBar` failure (a node the canvas cannot show and the
user cannot diagnose), in a component whose emptiness is *entirely* the
registry's doing: the component has an `emptyText` escape hatch and the editor
exposes no control for it.

## C2 — `bind: null` silently disables props validation on 7 of 21

**A new root cause, and the sharpest one this round.** It is invisible: no
warning, no badge, no render change — the props simply stop being validated.

`type: "binding", default: null` is the registry's universal shape for a bind
control (`starter.ts` ×30). `defaultPropsFor` filters **only `undefined`**
(`frontend/src/components/canvas/hooks/useDrop.ts:145-153`), and `normalizeSeed`
has two rules — numeric-domain strings and empty URL descriptors — neither of
which touches `null`:

```ts
export function normalizeSeed(descriptor: any, value: unknown): unknown {
  if (value === undefined) return undefined;
  if (isNumericDomain(descriptor) && typeof value === "string" && …) return Number(value);
  if (isUrlDescriptor(descriptor) && value === "") return undefined;
  return value;                       // ← null falls straight through
}
```

So `bind: null` is written to the node. **VERIFIED on disk** — every one of the
seven carries it:

```json
"props": { "value": 72, "min": 0, "max": 100, "label": "Utilization", "unit": "%", "bind": null }
```

But every schema types it `z.string().optional()`, and in Zod `null` is not
`undefined`. `validateProps` step 1 and 2 fail, and step 3's coercion table
(`packages/library/src/registry.ts:374-397`) has branches only for
`expected:"array"`, `expected:"object"` and `received:"undefined"` — **there is
no `received:"null"` branch.** The retry fails and the function returns
`finish(coerced)` — the raw props.

**VERIFIED by executing the real step-1/2/3 pipeline against the real schemas and
the real registry seeds:**

```
Gauge:            STEP3 STILL FAILS -> raw props to component: {"value":72,…,"bind":null}   errs=["bind:invalid_type"]
Heatmap:          STEP3 STILL FAILS -> {"color":"var(--color-primary-500)","showValues":false,"bind":null}
Kanban:           STEP3 STILL FAILS -> {"bind":null}
Schematic:        STEP3 STILL FAILS -> {"width":100,"height":60,"showLabels":true,"bind":null}
Stepper:          STEP3 STILL FAILS -> {"orientation":"horizontal","activeStep":0,"bind":null,"steps":[]}
SplitArc:         STEP3 STILL FAILS -> {"segments":[],…,"bind":null}  errs=["segments:too_small","bind:invalid_type"]
ResourceTimeline: STEP3 STILL FAILS -> {…,"statusField":null,"resourceGroupField":null,"itemHref":null}
```

The consequence is the same as round 4's C3b `Heading.level` finding, and just
as invisible: **every guarantee the component's Zod schema offers is skipped.**
`Gauge`'s `value/min/max` defaults, `Heatmap`'s `data` preprocess (`v == null →
[]`), `Stepper`'s enum narrowing, `Schematic`'s marker preprocess — none of them
run for a palette-dropped node. The components survive only because each
re-implements its own parameter defaults.

**Scope beyond this set — VERIFIED by grep:** `type: "binding", default: null`
appears **30 times** in `starter.ts` (of 134 entries), and
`type: "string", default: null` **3 times** (all three in
`resourceTimelineEntry`). So this class hits roughly a quarter of the registry,
including components audited in rounds 1–4 where it went unnoticed precisely
because it is silent.

`bind` is also not a real schema key on several of these — but that is not the
issue: it *is* declared (`z.string().optional()`) on Gauge, Heatmap, Kanban,
Schematic, SplitArc, Stepper and ResourceTimeline. The value, not the key, is
what fails.

## C3 — 16 of 21 dropped nodes write page JSON that `PageV2` rejects

Round 4 found two. This round the editor produces **sixteen** invalid nodes out
of twenty-one, on a page it wrote itself.

**VERIFIED against the real autosaved file** — I ran `PageV2.safeParse` from
`packages/schema/src/page.ts` over
`output/gh0mlpbp/src/schemas/display-lab-5.json`, then isolated each node into
its own single-child page to attribute the failures precisely:

```
Carousel             PageV2=FAIL  strict: ["props.items :: Required"]
CodeBlock            PageV2=FAIL  strict: ["props.code :: String must contain at least 1 character(s)"]
DescriptionList      PageV2=FAIL  strict: ["props.items :: Required"]
Dialog               PageV2=OK
FadeIn               PageV2=OK
Gauge                PageV2=FAIL  strict: ["props.bind :: Expected string, received null"]
Heatmap              PageV2=FAIL  strict: ["props.bind :: Expected string, received null"]
Kanban               PageV2=FAIL  strict: ["props.columns :: Required", "props.bind :: Expected string, received null"]
Lightbox             PageV2=FAIL  strict: ["props.images :: Required"]
List                 PageV2=FAIL  strict: ["props.items :: Required"]
QRCode               PageV2=FAIL  strict: ["props.value :: String must contain at least 1 character(s)"]
ResourceTimeline     PageV2=FAIL  strict: ["props.resourceGroupField :: Expected string, received null",
                                           "props.statusField :: Expected string, received null",
                                           "props.itemHref :: Expected string, received null"]
Schematic            PageV2=FAIL  strict: ["props.bind :: Expected string, received null"]
SearchResults        PageV2=OK
SplitArc             PageV2=OK      (no strict node shape — anyRegistered accepts `segments: null`)
Stagger              PageV2=OK
Stat                 PageV2=OK
Stepper              PageV2=FAIL  strict: ["props.steps :: Required", "props.bind :: Expected string, received null"]
Tag                  PageV2=OK
Tree                 PageV2=FAIL  strict: ["props.items :: Required"]
ValidationChecklist  PageV2=FAIL  strict: ["props.items :: Required"]
```

Every failure reports the union's second-branch message —
*"type is already covered by a strict node shape, or collides with a reserved
structural bucket"* (`page.ts:661-668`) — which is the `anyRegistered` guard
correctly refusing to rescue a node whose strict shape exists and failed. The
guard is right. The registry is wrong.

Three distinct causes, all registry-side:

- **C3a — the required content prop is absent** (Carousel, Lightbox, Tree,
  DescriptionList, List, ValidationChecklist, Stepper, Kanban). See C1.
- **C3b — `null` where the schema wants an optional string** (Gauge, Heatmap,
  Kanban, ResourceTimeline, Schematic, Stepper). See C2. This is the same shape
  as round 4's `Avatar.photoUrl: ""` — a value that is *present and wrong* where
  *absent* was the correct answer.
- **C3c — `""` against a `.min(1)`** (CodeBlock.code, QRCode.value). This is
  round 4's C3a exactly, in two new components. `normalizeSeed`'s
  `isUrlDescriptor` rule was written for precisely this and does not fire,
  because it keys on `control === "image" && imageShape === "url"` and these are
  `control: "textarea"` / `control: "text"`.

### Blast radius — INFERRED, code-cited, unchanged from round 4

The control-plane save path (`backend/routers/output_projects.py:238-253`) does
no validation, which is why my page saved cleanly. The app-foundation embedded
editor does validate
(`backend/templates/app-foundation/src/app/(dev-only)/api/editor/save/route.ts:49-58`
→ 422 → `packages/editor/src/save/api.ts:32-35` → `{ ok: false }`), so in that
editor **a page containing any of these sixteen cannot be saved at all**. At
runtime generated apps take the soft path
(`packages/renderer/src/runtime/validate.ts:3-14` console.warns and renders
anyway). I did not open a generated app or an embedded editor; the schema
failures themselves are VERIFIED.

## C4 — Dialog renders nothing and swallows its children

`Dialog` is one of the three containers in this set (`slots: { type: "list",
accepts: ["*"] }`). On the canvas it is a **0×0 node with zero DOM children**.

`Dialog.tsx:37-40`:

```tsx
const ctx = useContext(DialogStateContext);
// No engine wrapper supplied (e.g. component rendered standalone in tests)
// → render closed; tests can supply a stub context.
const open = ctx?.open?.[id] ?? false;
```

`DialogStateProvider` is exported from `@tentoroforge/renderer` and mounted by
the engine — and **grep finds no reference to it anywhere under
`frontend/src`.** So in the editor canvas `ctx` is `null`, `open` is `false`,
and `RDialog.Portal` renders nothing.

**VERIFIED, and the evidence is accidental and conclusive.** While inserting, a
`FadeIn` landed inside the Dialog because Dialog was the selected node. The
persisted page records it:

```json
{ "type": "Dialog", "id": "dialog-gah4q6",
  "props": { "id": "dialog", "title": "", "description": "", "size": "md" },
  "children": [ { "type": "FadeIn", "id": "fadein-t56lxs",
                  "props": { "delay": 0, "duration": 300 } } ] }
```

and the canvas showed **no `fadein-t56lxs` node at all** — my
`document.querySelectorAll('[data-node-id]')` sweep after the insert listed 10
nodes and that child was not among them. I only discovered it existed by reading
the saved file. A user who drops content into a Dialog gets a node that is on
disk, in the layer tree, and invisible, with no indication that the container
swallowed it.

It does **not** trap the editor — because it never opens, there is no modal
scrim and no focus trap. The failure is the opposite: unreachable, not
inescapable. Also worth noting, `Dialog.tsx:62` stamps
`data-node-id={id}` — the **`id` prop**, not the node id — on `RDialog.Content`,
so an open dialog would put a second, colliding `[data-node-id="dialog"]` into
the document via the portal, outside the canvas subtree. INFERRED; I could not
open a Dialog in the canvas to confirm it.

`FadeIn` and `Stagger`, by contrast, **do render their children** — VERIFIED:
after the six inserts that landed inside my Stagger, the node measured
`inner=6` with `textContent` `"Metric0Tag…"`, i.e. the Stat, Stepper, Tag, Tree
and ValidationChecklist children all rendered through the wrapper.

---

# P1 — root causes

## C5 — `style` reaches four components and is dropped or mis-applied

Round 4's C4 was *"three components never destructure `style`"*. That exact
shape is **fixed** for this set — twenty of twenty-one destructure `style` and
call `resolveStyle`. Two new variants replace it.

### C5a — ResourceTimeline applies the raw StyleSlot without resolving tokens

**VERIFIED end to end, A/B against a component that does resolve it.** Same two
Style-panel `<select>` controls, same two values, on two nodes on the same page:

| node | panel actions | persisted `node.style` | rendered `style` attribute | computed |
|---|---|---|---|---|
| **Gauge** | BACKGROUND = `color.primary.500`, PADDING = `spacing.8` | `{width, maxWidth, minHeight, background:"color.primary.500", padding:"spacing.8"}` | `width:100%; max-width:403px; min-height:252px; background: var(--token-color-primary-500); padding: var(--token-spacing-8);` | `rgb(59,130,246)` / `32px` ✅ |
| **ResourceTimeline** | identical | `{width, maxWidth, minHeight, background:"color.primary.500", padding:"spacing.8"}` | `width: 100%; max-width: 960px; min-height: 520px;` — **background and padding are gone** | `rgba(0,0,0,0)` / `0px` ❌ |

The panel wrote. The file recorded (I read both back from
`output/gh0mlpbp/src/schemas/display-lab-5.json`). The token refs reached React
unresolved, the CSSOM rejected `background: "color.primary.500"` as an invalid
value, and it never appeared in the style attribute — no error, no warning.


`ResourceTimeline.tsx` is the only component in the set that imports neither
`resolveStyle` nor `useMotion`. Both of its render paths spread the StyleSlot
straight into React:

```tsx
// :114-119  (empty state)
return (
  <div className={className} style={style} data-timeline-empty>

// :127-135  (populated)
<div className={className} data-resource-timeline
  style={{ border: "1px solid hsl(var(--border))", …, ...style }}>
```

`node.style` carries token *references* — `background: "color.primary.500"`,
`padding: "spacing.8"` — which `resolveStyle` turns into
`var(--token-color-primary-500)` (`packages/library/src/style/resolveStyle.ts:5-7,
33, 44-46`). Passed raw, React writes an invalid CSS value and the browser
discards it, silently. Literal values (`"#3b82f6"`, `"16px"`) would work, so the
failure is *selective*: the Style panel's colour and spacing **dropdowns** —
which emit token refs — do nothing, while typing a hex into the same field
works. That is harder to notice than round 4's total inertness.

It also spreads the StyleSlot's non-CSS keys, including `motion`, into React's
`style` object. INFERRED from source; I did not drive the Style panel on
ResourceTimeline in the browser.

### C5b — FadeIn and Stagger discard `style` when motion is disabled

```tsx
// FadeIn.tsx:33-35 / Stagger.tsx:37-39
if (!env.enabled) {
  return <>{children}</>;      // resolveStyle(style) is never reached
}
```

`env.enabled` is false at `motionLevel: "none"`. In that configuration every
Style-panel value on a FadeIn or Stagger — background, padding, radius, shadow —
is written to disk and rendered nowhere, and the fragment means there is not
even an element to attach it to. The sizing half still works, because
`LibraryDispatcher` handles sizing on its own wrapper
(`LibraryDispatcher.tsx:57-67`). INFERRED — the editor's motion token was
`(none)` in the Style panel but I did not set the app-level `motionLevel` token
to `"none"` to reproduce it live.

## C6 — `className` is declared and ignored by six components

Excluded from the "missing props" counts per the brief, but it is a contract
defect rather than a Style-panel concern, so it is reported here.

| component | schema declares `className` | component |
|---|---|---|
| `Gauge` | yes (`Gauge.schema.ts:19`) | `Gauge.tsx:35` — not destructured; root is `"inline-flex flex-col items-center"` |
| `Heatmap` | yes (`:21`) | `Heatmap.tsx:19-23` — not destructured |
| `Schematic` | yes (`:36`) | `Schematic.tsx:28-31` — not destructured; root is `"w-full"` |
| `SplitArc` | yes (`:42`) | `SplitArc.tsx:47-56` — not destructured |
| `Stepper` | yes (`:19`) | `Stepper.tsx:39` — not destructured |
| `ValidationChecklist` | yes (`:6`) | **destructured at `:15` and then unused** — `className={rootCls}` at `:27` |

`ValidationChecklist` is the notable one: the prop is pulled off the props
object, which is exactly the shape that makes the omission invisible to a
reviewer, and then dropped. This is round 3's `CameraCapture.className` finding
recurring.

## C7 — `Tag` implements an `accent` variant nothing can express

Round 4's C5c, verbatim, in the sibling component. `Tag.tsx:10-17`:

```tsx
const VARIANT_CLASS: Record<string, string> = {
  default: "bg-muted text-foreground",
  primary: "bg-primary/10 text-primary",
  // Accent — second brand hue (see Badge.tsx for the same rationale).
  // Composer sets `variant="accent"` when a chip should read as a
  // secondary emphasis rather than a primary CTA.
  accent:  "bg-accent text-accent-foreground",
};
```

`TagProps.variant` is `z.enum(["default","primary","success","warning","danger"])`
(`Tag.schema.ts:4`) and `tagEntry`'s `options` match it exactly
(`starter.ts:3400`). The `accent` row is unreachable from the editor and
unrepresentable in a page schema. The comment even points at `Badge.tsx` — the
component round 4 filed the identical finding against — which means both halves
of the pair were written together and neither enum was updated.

Unlike round 4's `Avatar.SIZE_CLASS`, `Tag` guards its lookup
(`VARIANT_CLASS[variant] ?? ""`), so an out-of-enum value degrades to an
unstyled pill rather than emitting a literal `undefined` class. Round 4's
recommendation 9 has landed here.

## C8 — Props the editor cannot reach

Counts exclude `className`/`style`. This is the largest such table of any round.

| component | unreachable props | n |
|---|---|---|
| **Kanban** | data, groupBy, columnOrder, cardTitle, cardDescription, cardBadge, cardFields, cardHref, columns, moveBetweenLanes, emptyText | **11** |
| **Heatmap** | data, xKey, yKey, valueKey, rows, columns, min, max, cellSize | **9** |
| **ResourceTimeline** | resourceIdField, resourceLabelField, resourceSubField, subtitleField, rangeStart, emptyText, bind | 7 |
| **DescriptionList** | items, dataSource, itemMode, emptyText, isLoading, skeletonRows | 6 |
| **Schematic** | grid, regions, markers, statusColors, heightPx | 5 |
| **Gauge** | thresholds, size, showValue | 3 |
| **List** | items, limit | 2 |
| **Stepper** | steps, activeId | 2 |
| **Carousel / Lightbox / Tree / ValidationChecklist** | items / images / items / items | 1 each |
| **QRCode** | label | 1 |
| **SplitArc** | stroke | 1 |
| CodeBlock · Dialog · FadeIn · SearchResults · Stagger · Stat · Tag | — | 0 |

**52 unreachable props across 21 components.** Standouts:

- **Kanban is the largest contract gap in the library** — larger than round 3's
  Calendar (10). The schema's own comment calls data mode *"(preferred)"* and
  legacy static columns *"(still supported)"*, and the editor exposes **neither**
  — only `bind`. `moveBetweenLanes`, the Spec-E cross-lane drag/drop feature
  documented at length in `Kanban.schema.ts:43-55` and fully implemented in
  `Kanban.tsx:144-168`, is unreachable. A board that cannot be given columns and
  cannot be told which field a drag writes is a placeholder.

- **`Gauge.thresholds` is the feature that distinguishes Gauge from Progress.**
  `Gauge.tsx:49-62` implements zone bands and active-zone colouring in full, and
  the schema's own docstring says so: *"Distinct from Progress (linear / plain
  circular): supports arbitrary ranges, zone bands, and a target-style needle."*
  The editor exposes value/min/max/label/unit. **An inventory app cannot paint a
  utilization dial red above 90% from the editor.**

- **`ResourceTimeline.rangeStart`** unreachable ⇒ the grid always begins at
  today (`ResourceTimeline.tsx:69`, `parseDay(rangeStart) ?? todayEpochDay()`).
  A scheduler that cannot be pointed at next month is a scheduler you cannot
  plan with.

- **`Schematic.regions` and `statusColors`** unreachable ⇒ the component reduces
  to an empty coordinate grid. `width: 100` / `height: 60` are exposed — the two
  props that mean nothing without markers to place in that space.

---

## C9 — The empty-node hint fires for six of them, and helps with none

**VERIFIED on the canvas.** Six of the twelve blank nodes get the editor's
amber dashed empty-node overlay. Enumerated from the live DOM:

```
"Carousel — Slideshow with prev/next and dots."
"DescriptionList — Term/description key-value pairs."
"List — Data-driven item list with title/subtitle."
"Tree — Hierarchical expandable tree view."
"ValidationChecklist — List of labelled pass/fail validation items."
"Stepper — set “bind” in the Properties panel."
```

Five of the six are the **palette description verbatim** — they say what the
component is, never what is missing, because the registry has no descriptor for
the missing prop for the hint to name. The sixth is round 3's C3a **exactly,
unfixed**: it sends the user to set `bind` (`z.string().optional()`) on a
component whose actual need is `steps` (required, absent from the registry), and
a user who follows the instruction will get a component that still renders
nothing.

`Lightbox` (960×**0**) and `Dialog` (0×0) get **no hint at all** — the overlay
needs a box and they have none. Those two are invisible *and* undiagnosable.

Interestingly the hint for `DescriptionList` renders even though the component
returned `null` — the overlay attaches to the dispatcher's sized wrapper, not to
component output. So the machinery to hint a zero-box node exists; `Lightbox`
and `Dialog` miss out only because their wrappers carry no `minHeight`.

## C10 — Zero React warnings, zero console errors (a clean result)

**VERIFIED.** After a full reload with all 21 nodes on the page, and after
driving Props and Style edits on several of them, `read_console_messages`
returned **282 messages, of which every single one is a Fast Refresh line or the
React DevTools banner**, and `onlyErrors: true` returned **no errors or
exceptions at all.**

No `Each child in a list should have a unique "key" prop`. Round 4's C6 and
round 2's Timeline finding do **not** recur in this set — the eight
list-rendering components here all key correctly (see below). No `$binding`
render errors. No `Maximum update depth exceeded`. No prop-type warnings from
the seven components running on unvalidated raw props (C2) — which is precisely
why C2 needed to be found by execution rather than by console.

---

# What works — verified, and worth recording

- **Four of twenty-one render correctly on drop with nothing but registry
  defaults**: `Gauge` (`"72% Utilization"`, needle and arc drawn), `Stat`
  (`"Metric / 0"`), `Tag` (a 41×20 pill reading "Tag"), and `SearchResults`
  (its pristine copy — which is the correct state for a results list with no
  query). `CodeBlock` renders its chrome correctly, just with no code in it.
- **Three components honestly declare their empty state** rather than rendering
  a broken box: `Heatmap` ("No heatmap data.", a dashed placeholder),
  `Kanban` ("No items to display yet."), `ResourceTimeline` ("No resources to
  display"). That is materially better than round 3's silent hairlines, and it
  is the pattern the other eight should copy.
- **`Stagger` renders its children correctly** — VERIFIED, `inner=6` with all
  six child nodes' text present.
- **No dead props anywhere in the set.** Every registry descriptor maps to a
  real schema key. Rounds 3 and 4 both found dead props; this round has none.
- **No wrong control for a type**, and **one** trivial enum divergence
  (ValidationChecklist ordering).
- **List keys correctly.** Round 4's C6 (`key={step.id}` on an optional `id`)
  does **not** recur: `List.tsx:29` keys on index, `Tree.tsx:36` and
  `TreeItem:27` on index, `DescriptionList.tsx:81` on index,
  `ValidationChecklist.tsx:33` on index, `Carousel.tsx:63` on index,
  `Lightbox.tsx:43` on index, `SearchResults.tsx:169` on
  `` `${entity}:${id}:${i}` ``, `Kanban.tsx:192/229` on `col.id`/`card.id`
  (both **required** in `Kanban.schema.ts:4,9`), and — the one that mattered —
  **`Stepper.tsx:71` keys on `step.id ?? i`**, the guarded form round 4's
  recommendation 8 asked for. See the false-positives section. Confirmed
  empirically: **zero key warnings in the console** across the whole session
  (C10).
- **No missing Tailwind utilities.** Round 3's C2 stays fixed with no residue
  here. VERIFIED by `getComputedStyle` on the real elements rather than by
  scanning class strings:

  | class | component | computed |
  |---|---|---|
  | `min-w-[220px]` | SplitArc root | `min-width: 220px` ✅ |
  | `text-[11px]` | SplitArc legend | `font-size: 11px` ✅ |
  | `inline-flex flex-col items-center` | Gauge root | `display: inline-flex` ✅ |
  | `border-dashed` + `italic` | Heatmap placeholder | `dashed` / `italic` ✅ |
  | `rounded-lg` | List `<ul>` | `border-radius: 10px` ✅ |
  | `rounded-full` | Tag pill | resolved (9999px clamp) ✅ |
  | `px-2.5 py-0.5` | Tag pill | `10px` / `2px` ✅ |
  | `select-none` | Tree `<ul>` | `user-select: none` ✅ |

  The geometry-heavy components the brief flagged — Heatmap, Schematic,
  SplitArc, Gauge — all resolve. `Schematic`'s emptiness is **not** a CSS
  problem: its `<svg>` carries the right `viewBox="0 0 100 60"` and measures
  960×320, and `svg.childElementCount === 0` because there is no marker,
  region or grid data to draw.
- **The Props panel is honest about what it has.** VERIFIED by reading the panel
  back for each node: `Carousel`, `Lightbox` and `Tree` render **the node name,
  the node id and the breakpoint selector and nothing else** — not a single
  control. `DescriptionList` and `ValidationChecklist` show only `ORIENTATION`,
  `List` only `DIVIDED`, `Kanban` only `BIND`, `Stepper` only
  `ORIENTATION / ACTIVESTEP / BIND`. The panel is not hiding these props; they
  do not exist.
- **The Bindings surface is intact.** Every registry-declared prop carries its
  per-prop bind toggle, and `Stepper`/`Kanban`'s `BIND` control offers the full
  scope picker (`form.<field>` / `row.<field>` / `state.<key>` / current user
  id) with the correct empty state *"No page data sources — pick a scope above
  or type an expression below."* Round 2's `{{expr}}` migration is holding.
  The problem is not that binding is broken; it is that for eight components
  **there is no prop to bind** (C1).

---

# Panel-by-panel verdict

| tab | verdict |
|---|---|
| **Props** | The failure surface, and for a third distinct reason. Round 3's props failed because the *control* was wrong; round 4's because the *default* was wrong; **round 5's fail because the control does not exist.** Three components have a completely empty Props panel and five more expose only a cosmetic knob. Every control that *is* present works: `ORIENTATION`, `DIVIDED`, `ACTIVESTEP`, `SIZE`, `SHOWVALUES` all commit live. No dead props, no wrong controls, one trivial enum-ordering divergence. |
| **Style** | Works on 20 of 21, and the round-4 C4 shape (never destructuring `style`) is **fixed** for this set. Two new leaks: `ResourceTimeline` applies the StyleSlot **raw**, so token dropdowns are silently inert while a literal hex would work (C5a, VERIFIED A/B against Gauge); `FadeIn`/`Stagger` discard `style` entirely on the motion-disabled path (C5b, INFERRED). Sizing is unaffected everywhere — `LibraryDispatcher` owns it. |
| **Bindings** | Works. Per-prop bind toggles on every declared prop, correct scope picker, correct empty state, **zero render errors and zero `$binding` failures across all 21 nodes**. Its reach is capped by C1: for eight components the prop worth binding is not declared, so there is nothing to bind. |
| **Tokens** | Works, unchanged. Global panel, identical for all 21. Token refs resolve to `var(--token-…)` correctly wherever `resolveStyle` is called — verified on Gauge. |

---

# False positives I ruled out

Six things I chased that are **not** bugs. Each would have been wrong in the
report.

1. **"`useMotion` is called after an early return, so Kanban / Heatmap /
   DescriptionList break the Rules of Hooks."** They do call it conditionally —
   `Kanban.tsx:171-181` returns the empty state without it and `:188` calls it —
   which looked like a guaranteed *"Rendered more hooks than during the previous
   render"* the moment a bound Kanban received data. It is not a bug:
   `packages/library/src/style/useMotion.ts:9-12` calls **no React hook at all**;
   it is a pure function that returns `{}` or `{"data-motion": …}`. The name is
   a lint hazard (it would trip `react-hooks/rules-of-hooks` and it invites
   exactly this mistake), but there is no runtime defect. Retracted.

2. **"`SplitArc.segments: null` crashes the component on `segments.map`."**
   `SplitArc.tsx:57` maps `segments` with no guard and the registry seeds `null`,
   which reads as a certain TypeError. It is not: `validateProps` step 3
   (`registry.ts:378-381`) coerces any non-array in an array position to `[]`
   **before** the component is called. **VERIFIED by executing the real
   pipeline** — SplitArc receives `{"segments":[], …}`. The arc renders as a
   title plus an empty track. Same reasoning clears `Stepper.steps` (arrives as
   `[]`) and `Heatmap.data`. The bug is silent emptiness, not a crash — which is
   why C1 is graded on data loss.

3. **"FadeIn did not insert from the palette."** My first insertion sweep listed
   no `fadein-*` node and I nearly filed it as a palette bug. It had inserted —
   as a **child of Dialog**, which was the selected node — and Dialog renders
   nothing, so the child never reached the DOM. The saved page shows
   `Dialog > FadeIn (fadein-t56lxs)`. The palette is fine; this became the
   evidence for C4 instead.

4. **"Every `bind: null` node fails to render."** No. The failure is entirely
   silent: `validateProps` returns the raw props and each component's own
   parameter defaults cover for the skipped Zod defaults, so Gauge renders a
   perfectly correct dial. The defect is that validation is **skipped**, not that
   rendering breaks — which is why it needed the executed step-1/2/3 simulation
   (C2) rather than a screenshot.

5. **"`SplitArc.total: 0` is a harmful default like `ActivityFeed.maxHeight: 0`."**
   The brief flagged the numeric defaults in Gauge / SplitArc / Heatmap /
   Carousel / ResourceTimeline and this one looks identical to round 4's C1a.
   It is correctly guarded: `SplitArc.tsx:59` is
   `const denom = (total && total > 0 ? total : sum) || 1;` — `0` is falsy and
   falls through to the sum, exactly as the registry description claims
   (*"0/omitted → sum of segment values"*). Checked the rest of the numeric
   defaults the same way: `Gauge.min: 0` is a legitimate range floor
   (`Gauge.tsx:36-38` uses `min ?? 0` and guards `span` with `|| 1`);
   `Stepper.activeStep: 0` correctly means "first step is current"
   (`Stepper.tsx:51-55`); `Schematic.width: 100`/`height: 60` match the schema's
   documented defaults; `ResourceTimeline.days: 14` matches; `QRCode.size: 128`
   matches; `SplitArc.size: 220` matches. **No `maxHeight: 0`-class harmful
   numeric default exists in this set** — the harmful defaults here are `null`
   and `""`, not `0`.

6. **"Round 4's `key={x.id}` bug recurs in Stepper."** `StepperStep.id` is
   `z.string().optional()` (`Stepper.schema.ts:4`), which is exactly the
   `ApprovalStepper` setup round 4 filed as C6, and the brief predicted it for
   Stepper. `Stepper.tsx:71` keys on **`step.id ?? i`** — the guarded form. Round
   4's recommendation 8 landed here. Checked all eight list-rendering components
   in the set (see "What works"); **none** keys on a bare optional `id`.

7. **"Clicking the STYLE tab collapses the properties panel."** It appeared to:
   my scripted `[...buttons].find(b => b.textContent.trim()==='STYLE').click()`
   left the panel collapsed to a vertical tab rail. That is my artifact — the
   selector also matches the panel's own collapse control, whose accessible
   text overlaps. Re-expanding by clicking the chevron at the panel edge and
   driving the real `<select>` elements worked cleanly, and C5a is graded on
   that second run only. (Same shape as round 4's false positive 4.)

Also not reported, per the brief: the pages list grew under me while I worked
(the concurrent tab's automated build), and Fast Refresh reloads during
insertion. Neither affected a measurement — every finding above was re-measured
after its own mutation, and the C1/C3 evidence comes from the persisted page
file rather than from live DOM state.

---

# Feature recommendations

1. **Add the missing content prop to all eight components, as
   `type:"array", control:"json"` with a seeded sample.** `Carousel.items`,
   `Lightbox.images`, `Tree.items`, `DescriptionList.items`, `List.items`,
   `ValidationChecklist.items`, `Stepper.steps`, `Kanban.columns`. This is
   round 3's recommendation 1 applied to the display half of the library, it is
   eight lines in one file, and it takes eight components from *unconfigurable*
   to *configurable*. **Highest-value change in this report.**

2. **Kill `default: null` in the registry, or teach the pipeline to skip it.**
   Thirty entries seed `bind: null`, and the seed defeats `validateProps`
   entirely (C2). Three fixes are available and only one is right: dropping the
   `default` key is correct (absent means unset), filtering `null` in
   `defaultPropsFor` is a good belt-and-braces second, and adding a
   `received:"null"` branch to the step-3 table is the wrong layer — it would
   paper over an invalid seed rather than stop it being written. This one change
   fixes seven of this round's `PageV2` failures and roughly a quarter of the
   registry.

3. **Add the registry test round 4 asked for, and make it assert both schemas.**
   For every entry: build the default props object through `normalizeSeed` and
   assert it parses against **both** the library `Props` schema **and** the
   `<Name>Node` shape in `packages/schema`. That single test catches C1, C2 and
   C3 at once — all sixteen invalid nodes — and would have caught round 4's
   `Avatar.photoUrl` and round 3's `FileUpload.maxSizeMb` too. Round 4's
   recommendation 1 is still the right recommendation and this round is the
   argument for it: the failure count went from 2 to 16 in one audit.

4. **Give the canvas a design-time Dialog.** A container that renders nothing,
   accepts children, and hides them on disk (C4) is worse than a container that
   refuses the drop. Mount a `DialogStateProvider` in the editor canvas and add a
   per-node "open in editor" affordance — the same problem round 3's
   recommendation 8 raised for `BulkActionBar`'s conditional `null`, now with a
   container and therefore with data loss attached. While in that file, stop
   stamping `data-node-id={props.id}` on `RDialog.Content`
   (`Dialog.tsx:62`) — it collides with the editor's own node-id attribute.

5. **`resolveStyle` must be mandatory, not conventional.** Round 4 found three
   components that ignored `style`; the fix pass gave those three `style`, and
   this round found a component that *takes* `style` and applies it **raw**
   (C5a) plus two that discard it on one code path (C5b). The convention is not
   holding. Either have `LibraryDispatcher` resolve the StyleSlot itself and pass
   the component a plain `CSSProperties`, or add the library test round 4's
   recommendation 5 proposed — render every registered component with
   `style: { background: "color.primary.500" }` and assert
   `var(--token-color-primary-500)` appears somewhere in its subtree. The second
   is cheap and catches all four.

6. **Every component needs an `emptyText` and the editor needs to expose it.**
   Three components in this set (Heatmap, Kanban, ResourceTimeline) render an
   honest empty-state string; `DescriptionList` has one and the registry hides
   it; five others render a silent empty box. A blank bordered rectangle is
   indistinguishable from a broken render. Make the empty state part of the
   contract, seed it, and expose the control.

7. **Expose `Gauge.thresholds` and `Kanban.moveBetweenLanes`.** Both are fully
   implemented, both are documented in their schemas as the feature that
   justifies the component's existence, and neither is reachable (C8). This is
   round 4's `MetricTile.threshold` finding recurring on the component actually
   named "Gauge" — ask the same audit question of every display entry: *can the
   editor supply the thing this component displays, and turn on the thing that
   makes it worth choosing?*

8. **Rename `useMotion`.** It is not a hook (false positive 1), it sits in every
   render path in the library, and its name makes conditional calls look like
   Rules-of-Hooks violations to every reader and to `eslint-plugin-react-hooks`.
   `motionAttrs(motion)` costs one rename and removes a permanent source of
   false findings in exactly this kind of audit.

9. **Add `accent` to `Tag` and `Badge`.** Both implement it, both enums omit it,
   the comments cross-reference each other (C7). Same fix, same file pair, two
   lines. Round 4's recommendation 6 named `Badge`; `Tag` is the other half.

10. **Distinguish "the registry omits this prop" from "the user has not filled
    it in" in the empty-node hint.** Round 3's recommendation 10 asked for the
    hint to be generated from the component schema rather than the registry
    entry. This round is the strongest case yet: for eight components the schema
    knows the required prop, the registry has no descriptor for it, and the
    editor therefore cannot even name the thing that is missing — and for
    `DescriptionList` the component returns `null`, so there is no box for a
    hint to attach to at all.
