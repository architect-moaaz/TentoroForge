# Display audit, round 4 — 10 display components

MoneyDisplay · MetricTile · Heading · Avatar · Badge · ApprovalStepper ·
PersonCard · ActivityFeed · FeatureCard · KeyValueList

Method, as rounds 1–3: contract diff (component Zod schema + `.tsx` vs. the
`starter.ts` registry entry), then a live editor session — new page
`/display-lab-4` in project `gh0mlpbp`, all 10 inserted from the palette, then
Props / Style / Bindings / Tokens exercised per node. `/items`, `/input-lab-2`
and `/input-lab-3` were left untouched.

`className` and `style` are EXCLUDED from "missing" counts throughout.

Every claim is marked **VERIFIED** (I did it in the live editor and measured the
result) or **INFERRED** (read from source, or executed against the real source
modules outside the browser). Browser evidence is `javascript_tool` DOM probes —
`getBoundingClientRect` / `getComputedStyle` / the React console — not eyeballed
screenshots. Two screenshots were taken and both succeeded; round 3's
`Page.captureScreenshot` timeouts did not recur.

Registry read at 19:50; the live editor session ran 20:00–20:30 against the same
build. No entry among these 10 changed under me.

---

# The headline

Rounds 1–3 were about inputs that could not hold a value. **Round 4's bug is
that the registry's own seed values are the payload.** The editor now seeds
every dropped node from `starterRegistry` prop defaults, and for four of these
ten the seed is a value the component reads as an instruction rather than as
"unset" — one of which makes the component render as an 18-pixel empty bar on
drop.

| # | root cause | severity | components hit |
|---|---|---|---|
| **C1** | seeded defaults the component treats as a command, not as "unset" | **P0** | 5 |
| **C2** | MoneyDisplay has no way to receive an amount | **P0** | 1 |
| **C3** | the editor writes page JSON that `PageV2` rejects | **P0** | 2 |
| **C4** | three components never read `style` — the Style panel is inert | **P1** | 3 |
| **C5** | Props panel controls that are overridden, truncated, or dead | **P1** | 5 |
| **C6** | ApprovalStepper keys its rows on an optional `id` | **P1** | 1 |
| **C7** | props the editor cannot reach | **P2** | 5 (12 props) |
| **C8** | two competing drop-defaults tables; the correct one is dead code | **P2** | all |
| **C9** | `control:"iconPicker"` is still a plain text box | **P2** | 1 |
| **C10** | an out-of-enum value in a JSON prop emits a literal `undefined` class | **P3** | 1 |

**20 distinct defects.** 8 are P0/P1 render-or-data failures.

The good news is real and worth stating up front: **all six of the
`actionPicker` → `array`/`object` + `control:"json"` conversions in this set
work** (C-verified below), **no Tailwind utility used by these ten is missing
from the canvas** (round 3's C2 is fixed with no residue here), and **the
`{{expr}}` binding format holds** — zero `$binding` render errors across all
ten nodes.

---

# Per-component contract table

Diffed against `packages/registry/src/starter.ts` and the component's own Zod
schema, executed via `npx tsx` against the real modules (INFERRED-by-execution),
then confirmed on the canvas.

| component | schema keys | required | missing from editor | dead props | seed valid? | Style panel? |
|---|---|---|---|---|---|---|
| **MoneyDisplay** | value, currency, locale, compact, showSymbol, align | — | **`value`** | — | renders `—` | yes |
| **MetricTile** | label, value, format, delta, icon, trend, importance, trendWindow, breakdown, threshold | label, value, format | `trendWindow`, `breakdown`, `threshold` | — | **delta → "1,250%"** | yes |
| **Heading** | level, content, id, weight | — | `id` (+ `align`, which exists only on `HeadingNode`) | — | **`level:"2"` fails the schema** | yes |
| **Avatar** | src, photoUrl, name, size, status | — | — | — | **`photoUrl:""`/`src:""` fail `.min(1)`** | yes |
| **Badge** | content, variant | — | — | — | ok | yes |
| **ApprovalStepper** | steps, orientation, onStepClick | steps | — | **`onStepClick`** | steps lack `id` → key warning | **NO** |
| **PersonCard** | name, role, department, avatarUrl, avatarInitials, email, status, manager, layout | name | **`manager`** | — | ok | **NO** |
| **ActivityFeed** | entries, title, showFilter, limit, fields, maxHeight | — | `limit`, `fields` | — | **`maxHeight:0` collapses it; `title:""` blanks the header** | **NO** |
| **FeatureCard** | title, description, icon, cta, layout | title, description, layout | — | — | `description:""` → empty `<p>` | yes |
| **KeyValueList** | items | items | — | — | ok | yes |

Enum options were **not** truncated anywhere in the registry — with one
exception that is a *schema* truncation, not a registry one (C5c). No prop uses
a wrong control for its type. No `null` defaults on required props.

---

# P0

## C1 — Five seeded defaults are values the component reads as an instruction

`buildDroppedNode` (`frontend/src/components/canvas/hooks/useDrop.ts:503`)
delegates to `defaultPropsFor` (`:77-85`):

```ts
export function defaultPropsFor(componentName: string): Record<string, unknown> {
  const entry = (starterRegistry as any)[componentName];
  if (!entry) return {};
  return Object.fromEntries(
    Object.entries(entry.props as Record<string, any>)
      .map(([n, d]) => [n, d.default])
      .filter(([, v]) => v !== undefined),
  );
}
```

Every registry `default` is copied onto the node verbatim. It filters
`undefined` only — `0`, `""` and a malformed object all survive. This is
exactly the mechanism round 3 caught with `FileUpload.maxSizeMb: 0` and
`MultiSelect.maxSelectionLabel: 0`; three of the five instances below are the
same shape, and one is worse.

### C1a — **ActivityFeed drops in with `max-height: 0px` and shows nothing** (the worst finding of the round)

`packages/registry/src/starter.ts:2601-2607`:

```ts
maxHeight: {
  type: "number",
  default: 0,
  control: "number",
  group: "style",
  description: "Maximum height in px (0 = unconstrained).",
},
```

`ActivityFeed.tsx:68-72` disagrees:

```tsx
<ol
  className="overflow-y-auto"
  style={{ maxHeight: maxHeight != null
    ? (typeof maxHeight === "number" ? `${maxHeight}px` : maxHeight)
    : "480px" }}
>
```

`0 != null` is **true**, so the component writes `max-height: 0px` and the
`overflow-y: auto` clips everything. The registry's "0 = unconstrained" is a
contract the component never agreed to; the component's "unconstrained" is
`undefined`.

**Reproduction — VERIFIED end to end:**

1. `/display-lab-4`, palette → `ActivityFeed` → click.
2. Measured on the live node:

```
[data-node-id^=activityfeed] section  =  960 x 18
                             ol       =  958 x 0
   getComputedStyle(ol).maxHeight     =  "0px"
   ol.getAttribute("style")           =  "max-height: 0px;"
   ol.querySelectorAll("li").length   =  2      ← the seeded entries ARE there
   first li height                    =  54.8px ← and each has real height
```

The two seeded entries render, measure 54.8px each, and are clipped to
invisibility. What the user sees on the canvas is an **18-pixel empty grey
bar**. There is no error, no issue badge, no empty-node hint — the component
returned real DOM, so nothing in the editor thinks anything is wrong.

3. Set `MAX HEIGHT` to `320` in the Props panel — the feed appears:

```
olMaxH = "320px"   ol = 109px   section = 127px
```

4. **The intended escape hatch does not exist.** Clearing the `MAX HEIGHT`
   field snaps it straight back to `0` (the number control coerces empty →
   `0`), and re-measuring gives `olMaxH = "0px", section = 18` again. So from
   the Props panel there is **no reachable value that means "unconstrained"**:
   the value the description names as unconstrained is the value that breaks
   it, and the value the component wants (`undefined`) is unreachable.

The `title: ""` seed compounds it — `ActivityFeed.tsx:52` declares
`title = "Activity"` as a parameter default, which `""` does not trigger, so
the header `<h3>` renders with `textContent === ""` and height `0`. VERIFIED.
The 18px bar is a border and 4px of padding around an empty heading.

### C1b — MetricTile's seeded delta renders as **1,250%**

`starter.ts:1091-1101` seeds `delta: { value: 12.5, direction: "up" }`.
`MetricTile/delta.ts` documents the numeric contract as a **fraction** —
"only under the documented convention (0.12 == 12%)" — and formats with
`style: "percent"`. So `12.5` becomes 1250%.

VERIFIED on the canvas: `[data-delta-direction] .innerText` is
`"↑\n1,250%"`. Every freshly-dropped KPI tile claims a twelve-hundred-percent
rise. The seed should be `0.125`.

### C1c / C1d — `Avatar.photoUrl: ""` and `Avatar.src: ""`

See C3 — these are page-schema violations, not just cosmetic.

### C1e — `FeatureCard.description: ""` on a **required** prop

`FeatureCardNode.props` declares `description: z.string()` (required, no
`.optional()`), and the Props panel now correctly renders a red **REQUIRED**
marker above it (round 2's Phase 7 landing). It is then seeded `""`, so every
dropped FeatureCard shows a required field the editor itself left blank and an
empty `<p>` under the title. VERIFIED — `fc.querySelector("p").textContent` is
`""`.

`paletteDefaults.ts:144` — the *other* defaults table — seeds this correctly as
`"Short feature description"`. See C8.

## C2 — MoneyDisplay cannot display money

`MoneyDisplayProps` (`packages/library/src/components/Money/Money.schema.ts:36-46`)
is:

```ts
export const MoneyDisplayProps = z.object({
  value:       z.union([z.number(), z.string()]).nullable().optional(),
  currency:    z.string().default("USD"),
  locale:      z.string().default("en-US"),
  compact:     z.boolean().default(false),
  showSymbol:  z.boolean().default(true),
  align:       z.enum(["left", "right"]).default("right"),
  …
});
```

`moneyDisplayEntry` (`starter.ts:528-543`) exposes **currency, locale, compact,
showSymbol, align** — the five formatting knobs — and **not `value`**. There is
also no `bind` prop.

**VERIFIED in the live editor.** Props panel for the dropped node, read back
verbatim:

```
CONTENT   CURRENCY   LOCALE
STYLE     ALIGN  (left | right)
BEHAVIOR  COMPACT   SHOWSYMBOL
```

Per-prop bind toggles exist for all five:

```
"currency: literal value — click to bind to data"
"locale: literal value — click to bind to data"
"align: literal value — click to bind to data"
"compact: literal value — click to bind to data"
"showSymbol: literal value — click to bind to data"
```

— and none of them is the amount. The Bindings tab reads *"No bindings on this
node."* The canvas renders:

```html
<span class="tabular-nums text-end" data-money-display="" data-empty="">—</span>
```

`Money.tsx:184-185` computes `hasValue` from `value`, which is permanently
`undefined`, so the em-dash is permanent. On disk the saved node is
`{"currency":"USD","locale":"en-US","compact":false,"showSymbol":true,"align":"right"}`
— no `value` key exists to bind, and per-prop `{{expr}}` binding cannot invent
one, because the bind toggle is rendered per *declared descriptor*.

**A currency display component that has no way to be given a currency amount.**
This is the round-2 `Combobox.options` finding ("a search box that can never
have anything to search") on the one component in the set whose entire purpose
is a single value. It is also unlike C1: not a bad default, an absent contract.

There is no `MoneyDisplayNode` in `packages/schema` either, so it lands on the
open `anyRegistered` fallback — which means adding `value` costs one registry
line and nothing else.

## C3 — The editor writes page JSON that the project's own schema rejects

**VERIFIED against the real autosaved file**, not a synthetic one. I ran
`PageV2.safeParse` from `packages/schema/src/page.ts` over
`output/gh0mlpbp/src/schemas/display-lab-4.json` — the file the editor wrote
while I worked:

```
[
 { "code": "too_small", "minimum": 1, "path": ["root","children",3,"props","src"] },
 { "code": "too_small", "minimum": 1, "path": ["root","children",3,"props","photoUrl"] },
 { "code": "custom",
   "message": "type is already covered by a strict node shape, or collides with a reserved structural bucket",
   "path": ["root","children",10,"type"] }
]
```

Two independent causes.

### C3a — `Avatar.photoUrl` and `Avatar.src` are seeded `""` against a `.min(1)`

`packages/schema/src/nodes/display.ts:8-12`:

```ts
src:      z.string().min(1).optional(),
photoUrl: z.string().min(1).optional(),
```

`starter.ts:1128-1143` seeds both to `""`. `.optional()` means *absent is fine*;
`""` is present and too short. On disk:

```json
{ "id": "avatar-znc55i", "type": "Avatar",
  "props": { "name": "User", "photoUrl": "", "src": "", "size": "md", "status": "online" } }
```

`validateProps` cannot rescue it either: its step-3 coercion table
(`packages/library/src/registry.ts:372-395`) handles `invalid_type` only, and
this is `too_small`, so the parse fails outright and the component receives the
raw `""` props. It renders correctly by luck (`imgSrc = photoUrl || src` is
falsy → initials), but the node is invalid everywhere upstream.

### C3b — A palette-dropped Heading writes `level` as a **string**

`starter.ts:955-962` declares `level` as `type: "enum", options: ["1"…"6"],
default: "2"` — strings. Both consumers want a number:

```ts
// packages/library/src/components/Heading/Heading.schema.ts:16
level: z.number().int().min(1).max(6).default(2),
// packages/schema/src/nodes/foundation.ts:194  (inside .strict())
level: z.number().int().min(1).max(6).optional(),
```

On disk, the two Headings on my page — **written by the same editor, in the same
session** — carry different types:

```json
{ "id": "heading-nc3ygd", "type": "Heading", "props": { "content": "display-lab-4", "level": 1 } }
{ "id": "heading-71oxtw", "type": "Heading", "props": { "content": "Heading", "level": "2", "weight": "bold" } }
```

The first came from the New-page template ("Show page heading"), which writes a
number. The second came from the palette, which writes the registry's string.

`HeadingProps.safeParse` therefore **fails on every palette Heading** —
confirmed by execution:

```
strictParse: [{"code":"invalid_type","expected":"number","received":"string","path":["level"]}]
final props: {"content":"Heading","level":"2","weight":"bold"}
```

The render survives by accident: `TAGS[level]` and `LEVEL_CLASS[level]` are
plain JS objects, and `obj["2"]` and `obj[2]` are the same key. VERIFIED — I
set LEVEL to 4 in the panel and the canvas produced `<h4>` at `font-size: 16px`
with `text-base font-semibold`. **But because the strict parse fails, every
other guarantee `HeadingProps` offers is skipped for every Heading in the
product**, and the node is unrepresentable in a page schema.

The `anyRegistered` open fallback explicitly refuses to catch it
(`page.ts:661-668`) — *"Refuses any type the strict union already covers.
Without this the fallback weakens validation for enumerated components: a
Heading with level 99 fails its strict shape, falls through here, and passes."*
That guard is correct; it is the registry that is wrong.

### Blast radius — INFERRED, code-cited

The control-plane save path
(`backend/routers/output_projects.py:238-253`) does **no** validation, which is
why my page saved fine and why rounds 1–3 never hit this. The generated app's
own embedded editor is a different story —
`backend/templates/app-foundation/src/app/(dev-only)/api/editor/save/route.ts:49-58`:

```ts
const parse = Page.safeParse(schema);
if (!parse.success) {
  return NextResponse.json({ ok: false, errors: … }, { status: 422 });
}
```

`saveSchema` maps 422 to `{ ok: false }` (`packages/editor/src/save/api.ts:32-35`).
So **in an app-foundation-embedded editor, any page containing a
palette-dropped Heading or a dropped Avatar cannot be saved at all** — and
Heading is close to the most common node in the product. At runtime, generated
apps take the softer path: `packages/renderer/src/runtime/validate.ts:3-14`
console.warns *"Page did not strictly validate"* and renders anyway. I did not
open a generated app or an embedded editor, so both consequences are INFERRED
from the code; the schema failure itself is VERIFIED.

---

# P1

## C4 — Three of the ten never read `style`, so the Style panel is silently inert

The canvas wrapper applies **sizing only**
(`packages/renderer/src/nodes/library/LibraryDispatcher.tsx:56-66`):

```tsx
const sizing = sizingFromStyle((validatedProps as { style?: unknown }).style);
if (sizing) {
  return (
    <span data-node-id={node.id}
          style={{ display: "block", boxSizing: "border-box", ...sizing }}>
      <Component {...validatedProps}>{children}</Component>
    </span>
  );
}
```

Everything else in `node.style` — background, padding, radius, shadow, motion —
reaches the component as a `style` prop (`dispatch.tsx:356-357`) and is the
*component's* job to apply via `resolveStyle(style)`. Three of these ten never
destructure it:

- `ApprovalStepper.tsx:31` — `export function ApprovalStepper({ steps, orientation = "horizontal" }: Props)`
- `PersonCard.tsx:30` — nine props, no `style`
- `ActivityFeed.tsx:52` — `{ entries, title, maxHeight, limit, fields }`

(`ActivityFeedNode.props` even *declares* `className` and `style`; the component
ignores both.)

**Reproduction — VERIFIED, A/B against a component that does read it.** For each
node: select → STYLE tab → BACKGROUND = `color.primary.500`, PADDING =
`spacing.8` (both `<select>` controls, so the commit path is React's own).

| node | root element | `style` attribute on the root | computed background | computed padding |
|---|---|---|---|---|
| **MetricTile** | `DIV` | `width:100%; max-width:403px; min-height:69px; background:var(--token-color-primary-500); padding:var(--token-spacing-8)` | `rgb(59,130,246)` | `32px` |
| **ApprovalStepper** | `OL` | **`null`** | `rgba(0,0,0,0)` | `0px` |
| **PersonCard** | `DIV` | **`null`** | `rgba(0,0,0,0)` | `0px` |
| **ActivityFeed** | `SECTION` | **`null`** | `oklch(1 0 0)` (its own `bg-card`) | `0px` |

The value is not lost — it is written to the document and persisted. From
`output/gh0mlpbp/src/schemas/display-lab-4.json`:

```json
{ "id": "approvalstepper-jja9fv", "type": "ApprovalStepper",
  "props": { … },
  "style": { "width": "100%", "maxWidth": "960px", "minHeight": "24px",
             "background": "color.primary.500", "padding": "spacing.8" } }
```

So the panel writes, the file records, the canvas shows nothing, and the
generated app will show nothing either. The user's only feedback is that
half the Style panel does nothing on three of ten components and there is no
way to tell which three.

Round 3 wrote *"each spreads `...styleProps` last, so Style-panel values do
land"* for its 17. That is not true for these three.

## C5 — Props-panel controls that are overridden, truncated, or dead

### C5a — `Badge.variant` is silently overridden by content inference

`Badge.tsx` carries two contradictory statements. The comment above the
inference table:

> *"Authors who DO specify a variant override this — explicit always wins."*

And the code twelve lines below it:

```tsx
const inferred = _inferVariant(content);
const resolvedVariant: Variant =
  inferred !== "neutral"
    ? inferred                                     // ← inference wins
    : variant && variant !== "neutral" ? variant : "neutral";
```

Inference is checked **first**. `SEMANTIC_VARIANT_HINTS` maps ~50 words —
`active`, `completed`, `pending`, `high`, `critical`, `low`, `draft`,
`in_progress`, `new`, `todo`, `review`, `blocked`… — the exact vocabulary a
status badge is made of.

**VERIFIED live**, driving the Props panel and reading `getComputedStyle` off
the rendered pill:

| CONTENT | VARIANT (panel) | rendered background | which won |
|---|---|---|---|
| `Active` | `neutral` | `oklch(0.95 0.052 163.051)` — emerald-100 | inference (success) |
| `Active` | **`danger`** | `oklch(0.95 0.052 163.051)` — **unchanged** | inference (success) |
| `in_progress` | **`danger`** | `oklch(0.932 0.032 255.585)` — blue-100 | inference (primary) |
| `Shipping` | `danger` | red-100 | the variant (no keyword match) |

Setting VARIANT to `danger` on a badge reading "Active" produces a **green**
badge. The control does nothing and says nothing. Whatever the merits of
inference as a fallback for LLM-generated pages, in the editor it means the
designer cannot override their own component, and the failure is invisible.

### C5b — `Avatar.size` `xs` and `xl` are silently identical to `md`

`Avatar.tsx:19-23`:

```tsx
const SIZE_CLASS: Record<string, string> = {
  sm: "h-8  w-8  text-xs",
  md: "h-10 w-10 text-sm",
  lg: "h-16 w-16 text-base",
};
```

Three rows. The Zod enum and the registry `options` both offer **five**:
`["xs","sm","md","lg","xl"]`. `SIZE_CLASS[size] ?? SIZE_CLASS.md` swallows the
other two.

**VERIFIED — measured through the panel's own select:**

| panel value | `data-avatar-size` | box | class |
|---|---|---|---|
| `xs` | `xs` | **40×40** | `h-10 w-10 text-sm` ← md |
| `sm` | `sm` | 32×32 | `h-8 w-8 text-xs` |
| `lg` | `lg` | 64×64 | `h-16 w-16 text-base` |
| `xl` | `xl` | **40×40** | `h-10 w-10 text-sm` ← md |
| `md` | `md` | 40×40 | `h-10 w-10 text-sm` |

The attribute proves the value reaches the component; there is simply no row
for it. **Two of the five options in the dropdown do nothing.** This is not a
registry truncation — it is the component that is short.

### C5c — `Badge` implements an `accent` variant that nothing can express

`Badge.tsx:15` types `Variant` as
`"neutral" | "primary" | "accent" | "success" | "danger" | "warning"` and
`VARIANT_CLASS` carries a full, carefully-commented `accent` row (the second
brand hue, wired to `--accent`/`--accent-foreground`). But
`BadgeProps` (`Badge.schema.ts`) is `.strict()` with a **five**-value enum that
omits `accent`, and the registry `options` match the Zod enum. So the accent
branch is unreachable from the editor **and** unrepresentable in a page schema —
`validateProps` would reject the value before the component saw it. VERIFIED
that the panel's select offers exactly
`["neutral","primary","success","danger","warning"]`.

### C5d — `ApprovalStepper.onStepClick` is a dead prop

Registry (`starter.ts:2400-2406`) and `ApprovalStepperNode`
(`enterprise.ts:18`) both declare it, described as *"Workflow ID triggered when
a step is clicked (optional)."* `ApprovalStepper.tsx:31` destructures
`{ steps, orientation }` and the file contains **no `onClick` anywhere** — the
steps are `<li>`s and `<div>`s. VERIFIED on disk: my saved node carries
`"onStepClick": ""` and no step is clickable.

Same shape as round 3's C10 (`Cascader.placeholder`): a control that promises
behaviour the component does not have.

### C5e — `Avatar.status` cannot be turned off

`display.ts:20-25` documents the contract explicitly: *"Omit `status` to render
no status indicator… this slot uses undefined as the 'absent' signal."* The
registry seeds `status: "online"` and the select offers
`["online","offline","away","busy"]` — no empty option. VERIFIED: every dropped
Avatar carries a green presence dot (measured, `oklch(0.696 0.17 162.48)`) and
there is no value in the control that removes it. A plain avatar in a table row
is not expressible.

### C5f — `FeatureCard.icon` renders an empty square. See C9.

## C6 — ApprovalStepper keys its rows on an optional `id`

This is round 3's `Timeline` bug, in the one component round 3 predicted it
for and did not check.

`ApprovalStepper.tsx:35` (vertical) and `:60` (horizontal):

```tsx
{steps.map((step, idx) => (
  <li key={step.id} className="flex gap-3">
```

`StepperStep.id` is `z.string().optional()` (`enterprise.ts:5`) and the seeded
default (`starter.ts:2385`) is
`[{label:"Submitted",status:"approved"}, {label:"Manager review",…}, {label:"Finance",…}]`
— **no `id` on any of the three.** So every seeded row gets `key={undefined}`.

**VERIFIED** — `read_console_messages` immediately after inserting the ten:

```
[ERROR] Each child in a list should have a unique "key" prop.
        Check the render method of `ApprovalStepper`.
```

It is the **only** React warning the ten produce, and it fires on drop with
nothing but registry defaults.

Note `paletteDefaults.ts:217-224` seeds `id: "1"/"2"/"3"` on every step — the
correct fix, in the table that is not used. See C8.

---

# P2

## C7 — Props the editor cannot reach

Counts exclude `className`/`style`.

| component | unreachable props | n |
|---|---|---|
| **MetricTile** | `breakdown`, `threshold`, `trendWindow` | 3 |
| **ActivityFeed** | `limit`, `fields` | 2 |
| **Heading** | `id`, plus `align` (declared on `HeadingNode`, absent from the library schema *and* the registry) | 2 |
| **MoneyDisplay** | `value` — see C2 | 1 |
| **PersonCard** | `manager` | 1 |

Standouts:

- **`MetricTile.breakdown` and `MetricTile.threshold` are the entire "widget
  anatomy" slice.** `foundation.ts:110-128` documents them at length —
  breakdown sub-lines ("Clients 2,000 / Male 984 / Female 1,016"), and a
  threshold rule that paints the value amber/red and stamps `data-threshold` for
  app CSS. `MetricTile.tsx` implements both fully, including a `<dl
  data-metric-breakdown>` grid and a `pickThresholdTone` function. **The editor
  exposes neither.** A KPI tile that cannot be given a warning threshold is
  missing the feature that makes it a KPI tile rather than a number.

- **`PersonCard.manager` is the only thing that distinguishes `layout:
  "expanded"` from a bigger compact card.** VERIFIED: I set LAYOUT to
  `expanded`, filled ROLE and DEPARTMENT, and the card rendered
  `JD | Jane Doe | Head of Ops | Operations` with **no "Reports to" block** —
  `/Reports to/.test(innerText)` is `false`. `PersonCard.tsx:57-70` renders it,
  accepting both `{name, role}` and a bare name string; there is no control for
  either shape.

- **`ActivityFeed.fields`** is the field-map the dashboard composer uses so a
  feed bound to a real entity does not render *"Someone"* on every row
  (`normalizeEntry.ts:1-14` says so in as many words). Unreachable from the
  editor, so a hand-bound feed cannot be mapped. I hit the same wall on
  KeyValueList from the other side — see the Bindings verdict below.

## C8 — Two competing drop-defaults tables, and the correct one is dead code

`packages/editor/src/panes/Palette/paletteDefaults.ts` is a second,
hand-written defaults table with the same purpose as the registry's `default`
fields — *"Default props… for newly-dropped palette items."* It is consumed only
by `packages/editor/src/dnd/DndContext.tsx:34`, while the frontend canvas has
its own drop path (`frontend/src/components/canvas/hooks/useDrop.ts:503`) that
reads `starterRegistry` instead. VERIFIED by observation: the canvas showed the
`starter.ts` seeds (`Status`/`Owner` on KeyValueList, `level: "2"` on Heading,
`photoUrl: ""` on Avatar), never the `paletteDefaults` ones.

The divergences are the punchline. **`paletteDefaults` is right in every case
where `starter.ts` is wrong:**

| prop | `starter.ts` (live) | `paletteDefaults.ts` (dead) |
|---|---|---|
| `Heading.level` | `"2"` — a string, fails `PageV2` (C3b) | `2` — a number ✅ |
| `Avatar.photoUrl` / `.src` | `""`, `""` — fail `.min(1)` (C3a) | absent ✅ |
| `ApprovalStepper.steps[].id` | absent — React key warning (C6) | `"1"`, `"2"`, `"3"` ✅ |
| `ActivityFeed.maxHeight` | `0` — collapses the feed (C1a) | absent ✅ |
| `ActivityFeed.title` | `""` — blanks the header (C1a) | `"Activity"` ✅ |
| `FeatureCard.description` | `""` on a required prop (C1e) | `"Short feature description"` ✅ |
| `MetricTile.value` | `"0"` (string) | `0` (number) |
| `PersonCard.role` | `""` | `"Senior Engineer"` |

Four of this report's P0/P1 findings were already solved, in this repo, in a
file the shipped editor does not call. That is worth more than any individual
fix: it is the strongest single argument for one defaults table with a test.

## C9 — `control: "iconPicker"` is still a plain text box, and FeatureCard renders no icon at all

Two independent halves, both VERIFIED.

**The control.** `frontend/src/components/properties/PropControls/index.tsx:183`:

```ts
iconPicker: TextControl,   // fallback — proper icon picker is future work
```

Round 2's Phase 5 fixed icon *resolution* (`IconButton` no longer paints the
word "Plus") and exported `ICON_NAMES` "to drive the picker UI" — but the picker
UI was never wired. `FeatureCard.icon` is the only `iconPicker` prop in this
set, and the panel renders a bare `<input type="text">` with no placeholder and
no discovery. Round 2's recommendation 5 is still open.

**The component.** `FeatureCard.tsx:31-38` never calls `resolveIcon`:

```tsx
{icon && (
  <span
    className={`inline-flex items-center justify-center rounded-md bg-primary/10 text-primary ${isLeft ? "h-10 w-10 shrink-0" : "h-12 w-12"}`}
    data-icon={icon}
    aria-hidden="true"
  />
)}
```

A self-closing span. VERIFIED: I typed `Sparkles` — a real Lucide name, and the
registry's own palette icon for FeatureCard — into the ICON field, and measured:

```
tag = SPAN   childElementCount = 0   svg count = 0   innerText = ""   box = 48 x 48
class = "inline-flex items-center justify-center rounded-md bg-primary/10 text-primary h-12 w-12"
```

An empty 48×48 tinted square. The contrast is in the same session:
`MetricTile.icon` set to the same `Sparkles` produced **`svg count = 1`**,
because `MetricTile.tsx:222-236` does call `resolveIcon` and renders `<IconComp
size={20} strokeWidth={1.5} />`.

So a user picking an icon for a FeatureCard gets: no picker, no validation, and
a blank box — with no way to tell whether they mistyped the name or the feature
does not exist.

## C10 — An out-of-enum value in a JSON prop emits a literal `undefined` class (P3)

`validateProps`' step-3 coercion table handles `invalid_type` only; an
`invalid_enum_value` falls through and the raw value reaches the component
(`registry.ts:372-395`).

**VERIFIED.** I authored ApprovalStepper's `steps` JSON with a deliberate bad
status:

```json
[{"label":"Draft","status":"approved","actor":"Vish"},
 {"label":"Legal","status":"rejected","actor":"Ada","timestamp":"2026-03-01T10:00:00Z"},
 {"label":"Payout","status":"skipped"},
 {"label":"Done","status":"bogus-status"}]
```

The first three rendered correctly (✓ emerald, ✕ rose, — dashed). The fourth's
dot came out as:

```
class = "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold undefined"
```

`STATUS_DOT[step.status]` is `undefined`, template-interpolated into the
className. The dot renders unstyled and transparent with the index "4" in it.
`MetricTile/delta.ts` fixed exactly this for `DELTA_TONE` ("`DELTA_TONE[undefined]`
used to put the literal string `undefined` into the tile's className") —
`ApprovalStepper`'s three lookup maps never got the same treatment, and neither
did `PersonCard.STATUS_DOT`.

---

# What works — verified, and worth recording

## The `actionPicker` → `array`/`object` conversions all hold

All six props the brief flagged were checked in the panel:

| prop | control rendered | authored, round-tripped? |
|---|---|---|
| `KeyValueList.items` | **RowsControl** — per-row label/value fields, ↑ ↓ ✕, *+ Add row*, *Edit as JSON* | **VERIFIED** |
| `ApprovalStepper.steps` | JSON textarea, with the reason shown | **VERIFIED** |
| `ActivityFeed.entries` | JSON textarea (seeded array, correctly formatted) | present and rendering |
| `MetricTile.delta` | JSON textarea `{ "value": 12.5, "direction": "up" }` | rendering (badly — C1b) |
| `MetricTile.trend` | JSON textarea `[4, 8, 6, 12, 10, 14]` | rendering (sparkline present) |
| `FeatureCard.cta` | JSON, seeded `{label, href}` | rendering ("Learn more →") |

**KeyValueList — VERIFIED end to end.** Clicked *+ Add row*, typed `SKU` /
`TF-9910` into the new row's fields, and the canvas went from
`STATUS | Active | OWNER | Jane Doe` to
`STATUS | Active | OWNER | Jane Doe | SKU | TF-9910`, with
`[data-kv-row]` count 2 → 3. Round 2's Phase 6 RowsControl is real and works.

**ApprovalStepper — VERIFIED end to end.** Replaced the whole `steps` array
through the JSON textarea with four steps (including `actor` and `timestamp`)
and the stepper re-rendered as
`✓ Draft Vish | ✕ Legal Ada | — Payout | 4 Done`, with per-status dot classes
`bg-emerald-600` / `bg-rose-600` / `border-dashed`. This is the round-3 C1
failure mode *fixed*: the control fills the prop it exists to fill.

RowsControl's shape-sniffing degrades honestly. For `ApprovalStepper.steps` the
panel reads:

> **STEPS** — *Editing as JSON — no value / key / id on every row.*

That is the right behaviour and the right message.

## No missing Tailwind utilities

Round 3's C2 (`@source` globs off by one `../`) is fixed —
`frontend/src/app/globals.css:30-32` now points at the repo root correctly — and
**nothing in these ten resolves to nothing.** I checked the awkward ones by
`getComputedStyle` on the real elements rather than by scanning class strings:

| class | component | computed |
|---|---|---|
| `sm:grid-cols-[minmax(0,160px)_1fr]` | KeyValueList row | `grid-template-columns: 159.995px 784.003px` ✅ |
| `bg-[var(--color-success-500,theme(colors.emerald.500))]` | Avatar status dot | `oklch(0.696 0.17 162.48)` ✅ |
| `max-w-[140px]` | ApprovalStepper caption | `max-width: 140px` ✅ |
| `bg-[var(--color-primary-100,theme(colors.blue.100))]` | Badge primary | `oklch(0.932 0.032 255.585)` ✅ |
| `text-3xl` / `text-base` | Heading (level 1 / 4) | `30px` / `16px` ✅ |

I also enumerated all 2,136 selectors in the canvas stylesheet and confirmed the
rules exist by their escaped forms: `.\[overflow-wrap\:anywhere\]`,
`.grid-cols-\[1fr_auto\]`, `.max-w-\[140px\]`, `.text-\[9px\]`,
`.text-\[11px\]`, `.line-clamp-2`, `.sm\:grid-cols-\[minmax\(0\,160px\)_1fr\]`.
The v4 `theme()`-inside-arbitrary-value pattern these components lean on
resolves correctly.

## Bindings hold; Tokens unchanged

`{{expr}}` binding works on display components. VERIFIED on
`KeyValueList.items`: clicked the bind toggle (which correctly flipped to
*"items: bound to data — click to use a literal value"*), typed `items` into
*"pick a data source, or form.field / state.x"*, and the list re-rendered from
the project's fixture rows with **zero render errors and no issue badge**.
Round 2's `$binding` phase is holding for this set.

Tokens is the same global panel as rounds 2–3, full 50→950 ramps rendering.

---

# False positives I ruled out

Five things I chased that are **not** bugs. Each would have been wrong in the
report.

1. **"ActivityFeed and KeyValueList have the same `key={undefined}` bug as
   ApprovalStepper."** The brief predicted all three; only ApprovalStepper has
   it. `ActivityFeed` routes every row through `normalizeEntry(raw, i, fields)`
   which synthesises `id: e.id ?? \`entry-${i}\`` (`normalizeEntry.ts:26`), and
   `KeyValueList.tsx:56` keys on the index directly. Confirmed empirically —
   the console carried the ApprovalStepper warning **three times** and nothing
   from the other two, across a session in which I re-rendered all three
   repeatedly.

2. **"The canvas stylesheet is missing `grid-cols-[1fr_auto]`,
   `max-w-[140px]`, `text-[11px]`, `[overflow-wrap:anywhere]`…"** My first pass
   substring-matched `document.styleSheets` selector text and got `false` for
   every arbitrary value — which looked exactly like round 3's C2 recurring.
   It was my probe: `selectorText` returns the **CSS-escaped** form
   (`.max-w-\[140px\]`), so a plain `includes("max-w-[140px]")` can never
   match. Re-running with `s.replace(/\\/g,"")` found all of them, and
   `getComputedStyle` on the live elements confirmed they apply. Retracted
   entirely.

3. **"`Heading.level` as a string breaks the render."** It does not. `TAGS` and
   `LEVEL_CLASS` are JS objects, so `TAGS["2"]` and `TAGS[2]` are the same key.
   The render is correct at every level (measured `h4` / 16px). The bug is the
   *persisted type* (C3b) and the fact that the whole `HeadingProps` parse fails
   silently — not the visual.

4. **"The Style panel's BACKGROUND field is broken on every component."** My
   first attempt drove the free-text token input
   (placeholder `#3b82f6 · rebeccapurple · color.primary.500`) with a synthetic
   `input` event and nothing committed on any node, including MetricTile. That
   is the control's commit-on-real-blur path not firing for a synthetic event —
   my artifact. Re-running through the adjacent `<select>` (`color.primary.500`)
   committed cleanly, and *then* the MetricTile-vs-the-other-three split in C4
   showed up. C4 is graded on that second run only.

5. **"Binding `KeyValueList.items` to `items` produces a broken list."** It
   renders labels from the row data and `—` for every value, which looks like a
   bug. It is not: the fixture rows are `{id, name, category, …}` and
   `KeyValueList` wants `{label, value}`. The component's empty-value handling
   (`data-kv-empty`, the italic em-dash) is doing exactly what it says. The real
   observation is a **feature gap** — `KeyValueList` has no `labelField` /
   `valueField` mapping the way `ActivityFeed` has `fields` — so it is filed
   under recommendations, not findings.

Also not reported, per the brief: Fast Refresh reloads during insertion, and
selection loss after them. Neither recurred in a way that affected a
measurement — every finding above was re-measured after its own mutation.

One observation carried forward from round 2 that is **still** live and
**VERIFIED visually**: the **"1 Issue" badge overlaps the bottom rows of the
pages panel** (it sat on top of the `/display-lab-4` row for most of the
session). Round 2's recommendation 10, unfixed.

---

# Panel-by-panel verdict

| tab | verdict |
|---|---|
| **Props** | The failure surface again, but for a new reason. Round 3's props failed because the *control* was wrong; these fail because the *default* is wrong (C1) or the *component* ignores the control (C5). Plain text and enum controls all commit live and correctly. RowsControl (C-verified on KeyValueList) is a genuine improvement over round 2's state. Required markers are present and correct. |
| **Style** | **Inert on three of ten** (C4) — ApprovalStepper, PersonCard, ActivityFeed accept sizing via the wrapper and drop everything else on the floor, while persisting it to disk. Works correctly on the other seven; MetricTile took `background` + `padding` and rendered them. |
| **Bindings** | Works. Zero `$binding` errors, zero render errors, correct empty state, per-prop toggles with `aria-label` on every prop of every node. **Except** MoneyDisplay, where the only prop worth binding does not exist (C2). |
| **Tokens** | Works, unchanged. Global panel, identical for all ten. |

---

# Feature recommendations

1. **Fix the five seeds, and add the test that keeps them fixed.**
   `ActivityFeed.maxHeight: 0 → null` (or drop the descriptor's `default`
   entirely), `ActivityFeed.title: "" → "Activity"`,
   `MetricTile.delta.value: 12.5 → 0.125`, `Avatar.photoUrl`/`src` `"" → ` no
   default, `FeatureCard.description: "" → "Short feature description"`. Then a
   registry test that, for every entry, builds the default props object and
   asserts it parses against **both** the library schema and the node schema.
   That single test catches C1, C3a and C3b at once, and would have caught
   round 3's `FileUpload.maxSizeMb: 0` too. This is the highest-value change in
   this report.

2. **Delete one of the two defaults tables.** `paletteDefaults.ts` is dead code
   that is *more correct than the live table* on six props (C8). Either make
   `buildDroppedNode` consult it, or fold its values into `starter.ts` and
   remove it. Leaving both is how a fix lands in the wrong file and nobody
   notices — the same failure mode as round 2's D1.

3. **`Heading.level` must be `type: "number"`.** The registry declares an enum
   of strings for a prop that two schemas type as a number, and the editor's own
   page template already writes it correctly. A `NumberControl` with min 1 / max
   6, or a `type: "number"` descriptor whose `options` are numbers. This is the
   one change that makes palette Headings savable in an embedded editor.

4. **Give `MoneyDisplay` a `value` prop.** One registry line
   (`value: { type: "string", default: "", control: "text", group: "content" }`
   plus a `bind`), and the component goes from permanently blank to the most
   directly useful display node in the set. It has no strict node schema, so
   nothing else needs to change. Consider the same audit question for every
   `category: "display"` entry: *can the editor supply the thing this component
   displays?*

5. **Make `style` non-optional for library components.** Three of ten drop it
   (C4), and the failure is invisible because the wrapper handles sizing. Two
   options: have `LibraryDispatcher` fall back to applying the full
   `resolveStyle(style)` on the wrapper when the component's schema declares no
   `style` key, or add a library test that renders every registered component
   with a known `style` and asserts the property lands somewhere in its subtree.
   The second is cheap and would have found all three.

6. **Decide who owns `Badge.variant`.** Content inference is defensible as a
   *fallback* for generated pages and indefensible as an *override* in an
   editor. Invert the condition so an explicit non-default variant wins — which
   is what the comment already claims — and fix the comment either way. While
   in the file, add `accent` to the Zod enum and the registry options; the
   implementation is already there and carefully written.

7. **Fill in `Avatar.SIZE_CLASS`.** Two of five dropdown options silently
   render as `md` (C5b). Add `xs: "h-6 w-6 text-[10px]"` and
   `xl: "h-20 w-20 text-lg"`, and add a library test that asserts every value in
   a component's enum produces a distinct class — the same drift guard round 2's
   Phase 5 added for icons. `Badge`, `PersonCard` and `ApprovalStepper` all have
   lookup maps that would benefit.

8. **Key list rows on `id ?? index`, everywhere.** `ApprovalStepper` is the
   third component caught doing this (`Timeline` in round 2's integration pass,
   now this). `normalizeEntry`'s `e.id ?? \`entry-${i}\`` is the pattern to
   copy. A lint rule banning `key={x.id}` where `id` is optional would end the
   class.

9. **Never interpolate an unguarded map lookup into a className.**
   `STATUS_DOT[step.status]`, `STATUS_CONNECTOR[…]`, `PersonCard.STATUS_DOT[…]`
   all emit a literal `undefined` class on an out-of-enum value (C10).
   `delta.ts` already documents the fix for this exact bug; apply
   `?? FALLBACK` at every lookup site.

10. **Ship the icon picker, and make `FeatureCard` resolve icons.** `iconPicker`
    has been a `TextControl` since round 2 (C9), and `FeatureCard` compounds it
    by never calling `resolveIcon` at all, so the field is a guessing game whose
    right answer still renders a blank box. `MetricTile.tsx:222-236` is the
    three-line pattern to copy. `ICON_NAMES` is already exported for the grid.

11. **Expose `MetricTile.breakdown` and `MetricTile.threshold`.** Both are fully
    implemented, both are documented in the node schema as the widget-anatomy
    slice, and neither is reachable (C7). `threshold` in particular is what
    turns a number into a KPI — an inventory app cannot mark a low-stock tile
    red from the editor.

12. **A `labelField` / `valueField` mapping for list-shaped display components.**
    Binding `KeyValueList.items` to a real entity renders every value as `—`
    because the rows are `{id, name, …}` and the component wants
    `{label, value}`. `ActivityFeed.fields` is the right idea and is itself
    unreachable (C7). Both need the mapping *and* a control for it; otherwise
    binding a display list to data only works when the data was shaped for the
    component.
