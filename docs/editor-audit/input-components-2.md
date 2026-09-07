# Input audit, round 2 — 16 components

Slider · Combobox · FileUpload · Button · Form · IconButton · FilterBar ·
DateRangePicker · MultiSelect · DatePicker · TimePicker · ColorPicker ·
InputOTP · Rating · MaskedInput · KeyValueInput

Method: contract diff (component Zod schema vs. editor registry entry), then a
real editor session — page `/input-lab-2` in project `gh0mlpbp`, all 16 dropped
from the palette, then Props / Style / Bindings / Tokens exercised per node.

`className` and `style` are EXCLUDED from "missing" counts throughout — those
are the Style panel's job, not Props.

---

# P0 — controls that do not work at all

## C1 — Slider, Rating and ColorPicker are dead on arrival

Verified in the live editor canvas, not inferred: set the value, read it back.

| control | action | result |
|---|---|---|
| Slider | set range input to 75, fire input+change | reverts to `0` |
| Rating | click the 4th star | 0 stars filled |
| ColorPicker | set to `#ff0000` | reverts to `#000000` |

Cause — all three are **fully controlled with no state of their own**:

```tsx
// Slider.tsx:31   value is the prop; the handler calls an optional callback
<input type="range" value={single} onChange={(e) => onChange?.(Number(e.target.value))} />

// Rating.tsx:26   no onChange prop ⇒ onClick is undefined
<button onClick={onChange ? () => onChange(n) : undefined}>

// ColorPicker.tsx:20  no onChange prop ⇒ the input is controlled AND handler-less
<input type="color" value={value} onChange={onChange ? (e) => onChange(e.target.value) : undefined} />
```

Nothing supplies `value`/`onChange` when a node is rendered from a page schema,
so the value is pinned to its default forever. ColorPicker is the loud case —
React logs *"You provided a `value` prop to a form field without an `onChange`
handler"* and it surfaces in the editor as a **1 Issue** badge.

**The library is split across two incompatible contracts.** Self-managing (hold
their own `useState`, work standalone): Combobox, MultiSelect, DateRangePicker,
FileUpload, InputOTP, MaskedInput, KeyValueInput. Parent-controlled (dead
standalone): Slider, Rating, ColorPicker, DatePicker, TimePicker. Nothing in the
palette, the description or the Props panel tells the user which kind they just
dropped.

DatePicker and TimePicker are the quieter half of the same split: they are
*un*controlled (no `value`), so typing works locally but the value is stored
nowhere and no React warning fires.

## C2 — `ActionPicker` is wired to 7 props whose type it cannot produce

`ActionPicker` builds workflow/navigation actions. Its entire output vocabulary
is `{action:"navigate"|"workflow"|"submitForm"|"openModal", …}`. That is exactly
right for `Button.onClick` — the one correct use among the 8 in this set. It is
also the editor's only control for these seven array/object props, none of which
it can produce a legal value for:

| prop | real type | required? |
|---|---|---|
| `Form.fields` | array of field descriptors | the whole point of Form |
| `Form.defaultValues` | record | |
| `FilterBar.chips` | array of objects | **required** |
| `FilterBar.savedViews` | array of objects | |
| `DateRangePicker.presets` | array of enums | |
| `MultiSelect.options` | array of `{value,label}` | **required** |
| `MultiSelect.selected` | array of string | |

Pick any action and the prop becomes an object where an array belongs;
`validateProps` step 3 coerces it to `[]`, so the control silently empties the
very prop it was meant to fill. Observed: MultiSelect renders "Choose options…"
with nothing in it; FilterBar renders an empty 26px strip.

Identical to the AppShell composition-slot bug in `containment.md` #1, which is
why `JsonControl` exists. Same fix: `type:"array"` + `control:"json"` with a
seeded default — exactly what `Select.options` and `RadioGroup.options` got in
round 1.

## C3 — IconButton renders the literal text "Plus"

Dropped with its registry default `icon: "Plus"`, IconButton renders the **word**
"Plus" instead of a plus glyph. `control: "iconPicker"` is mapped to
`TextControl` in `PropControls/index.tsx:222` ("fallback — proper icon picker is
future work"), so the user also has no way to discover a valid icon name.

---

# P1 — props the component supports that the editor cannot reach

Counts exclude `className`/`style`.

| component | unreachable props |
|---|---|
| Button | `loading`, `workflow`, `args`, `submit`, `navigate`, `icon`, `iconSrc`, `iconPosition`, `togglesSidebar`, `aria-label`, `dataJourney` (11) |
| FileUpload | `maxSizeMb`, `hint`, `filenameField`, `mimeTypeField`, `resumable`, `retryOn5xx`, `chunkSizeMb` (7) |
| IconButton | `iconSrc`, `loading`, `args`, `navigate` (4) |
| TimePicker | `min`, `max`, `step`, `disabled` (4) |
| Combobox | `options`, `filterable`, `clearable` (3) |
| Slider | `step`, `showValue` (2) |
| MultiSelect | `optionsFrom`, `maxSelectionLabel` (2) |
| Form | `onSuccess`, `onError`, `autoSave` (3) |
| ColorPicker / InputOTP / Rating / KeyValueInput | `disabled` (1 each) |
| DatePicker | `validators` (1) |

Standouts:
- **`Combobox.options` does not exist in the editor at all.** A dropped Combobox
  is a search box that can never have anything to search. Same class as the
  `Select.options` bug fixed in round 1.
- **`Button.navigate` and `Button.workflow` are both unreachable**, so the only
  way to make a button do anything is the `onClick` ActionPicker.
- **`Slider.step` unreachable** ⇒ no 0.5-step or currency slider is expressible.
- **`FileUpload.maxSizeMb` unreachable** ⇒ no upload size limit can be set from
  the editor, on the one component where that is a real constraint.

## C4 — `Button.variant` is missing `accent` and `danger`

Registry offers `primary | secondary | ghost`; the component accepts
`primary | secondary | accent | danger | ghost`
(`packages/registry/src/starter.ts:750`). **A red destructive button cannot be
built from the editor** — on an inventory app whose item rows have a Delete
action.

## C5 — three components cannot be data-bound at all

`FilterBar`, `DateRangePicker` and `MultiSelect` have no `bind` prop in either
the component or the registry, so the Bindings tab has nothing to offer for
them. Every other input in this set has one.

## C6 — `FilterBar.chips` is required but defaults to `null`

The component declares `chips` as a **required** array; the registry default is
`null`. Every freshly-dropped FilterBar is therefore invalid on arrival and
renders as an empty strip. (The empty-node hint overlay is what makes this
visible at all — "FilterBar — set 'chips' in the Properties panel".)

---

# Notes

- The **1 Issue** badge overlaps and obscures the bottom rows of the layer tree
  (it sat on top of the `Slider` row throughout this session).

---

# P0 — the Bindings tab corrupts any node you use it on

**This is the most serious finding of the round.** Reproduced live on
`/input-lab-2`, Button `label`:

1. Click the **Aa** ("Literal — click to bind") toggle next to LABEL.
2. The Button in the canvas *immediately* becomes **⚠ Button: render error**.
   The issue counter goes 1 → 3. No expression has been entered yet.
3. Console: `Error: Objects are not valid as a React child (found: object with
   keys {$binding})` — caught by `NodeErrorBoundary`.
4. Typing a **complete, valid** expression (`items[0].name`) does **not** fix it.
   The node stays broken.
5. Autosave writes it to disk:

```json
// output/gh0mlpbp/src/schemas/input-lab-2.json
{ "id": "button-uuwwf9", "type": "Button",
  "props": { "label": { "$binding": "items[0].name" }, … } }
```

**Root cause.** `$binding` is the editor's own wire format for a bound prop, and
**nothing outside the editor has ever heard of it**:

```
grep -rn '$binding' packages/renderer/src packages/engine/src \
                    packages/library/src packages/schema/src
→ 0 matches
```

It appears only in `frontend/src/components/properties/{BindingsPanel,
PropertiesPanel}.tsx`. So the object flows through `interpolateDeep` untouched
(it isn't a string), through `validateProps` (it isn't a type Zod can coerce),
and lands in React child position as a raw object.

The renderer already has a working binding format — the `{{expr}}` string that
`interpolate.ts` resolves, which `PropertiesPanel.tsx:305` even mentions
("{{…}} string; the editor's {$binding} object stays an object"). Two formats
exist; the editor writes the one that does not work.

**Blast radius.** Every prop rendered in child position — `label`, `content`,
`text`, `title`, `placeholder` — on every component. And because it persists,
the broken prop ships into the generated app; `validateForCommit` does not catch
it (it checks id-uniqueness and registry-type closure only).

**Recovery.** Toggling the control back to Literal restores the node — but see
the next finding for why that is hard to reach.

## A node in render-error state cannot be selected from the canvas

Clicking the ⚠ error box selects the **parent** (the Stack), because the error
boundary's placeholder carries no `data-node-id`. So the user cannot open the
Props panel for the node they just broke, and cannot undo it there. The only
route back is the layer tree. The thing you most need to select is the one thing
you cannot click.

## Ctrl+Z is swallowed by the palette search box

With focus in the component-search field, Ctrl+Z performed a text undo in that
input (`KeyValueInput` → `KeyV`) instead of undoing the design change. The
editor's undo does not preempt a focused text field, so undo silently does
something unrelated at the moment the user most expects it to work.

---

# Panel-by-panel verdict

| tab | verdict |
|---|---|
| **Props** | Works, but see the missing-props table and C2/C4. The per-prop **Aa** bind toggles have a `title` and no `aria-label`, and "Aa" is not an obvious glyph for "bind". |
| **Style** | Works. Width/maxWidth/background/padding/radius/shadow/motion all write to `node.style` and render. Breakpoint switcher (ALL/SM/MD/LG/XL) present. |
| **Bindings** | **Broken** — see above. |
| **Tokens** | Works. Full 50→950 colour ramps render (the round-1 ramp-truncation fix is holding). Note it is a **global** panel, not per-node, so it is identical for all 16 components. |

---

# Feature recommendations

1. **Declare the state contract in the registry.** Add `selfManaged: true|false`
   per input. Palette and Props can then say "this control needs a Form or a
   binding to hold its value" instead of shipping a dead widget. Fixes the C1
   class at the root rather than per component.
2. **Make standalone inputs self-managing by default** — `useState` seeded from
   the prop, calling `onChange` when present. Slider/Rating/ColorPicker/
   DatePicker/TimePicker become usable on their own, and stay controlled when a
   parent supplies both halves.
3. **One binding format.** Have the editor write `{{expr}}` — the format the
   renderer already resolves — and drop `$binding` entirely. Add a
   `validateForCommit` rule that rejects any `$binding` object so the class can
   never regress.
4. **A real options editor** for `options` / `chips` / `presets` / `fields`: a
   repeating row list (value + label), with "fill from a data source" for
   relational dropdowns. `control:"json"` is the correct stopgap; a row editor is
   the real fix, and it retires 7 misapplied ActionPickers here, and ~30 of the 36 across the registry.
5. **A real icon picker.** `iconPicker` currently falls back to a plain text
   field, which is why IconButton renders the word "Plus". A searchable grid of
   the actual icon set removes a guessing game.
6. **Per-prop "required" marking in the Props panel.** `FilterBar.chips` and
   `MultiSelect.options` are required by the component and default to `null`;
   nothing in the UI says so until the node renders blank.
7. **Validators on every input, not just some.** `validators` exists on
   DatePicker but is unreachable, and is absent from Slider/TimePicker/
   ColorPicker/Rating/InputOTP. Min/max/required/pattern belongs on all of them.
8. **Make the error boundary's placeholder selectable** (carry `data-node-id`),
   and show the failing prop name in it.
9. **Scope undo to the editor** when focus is in a panel/palette text field, or
   at minimum do not let a design-level Ctrl+Z silently edit a search box.
10. **Move the issue badge** — it overlaps the bottom rows of the layer tree.

---

# Deeper findings from the fix-planning pass

Three things surfaced while tracing the code to plan the fixes. Each changes the
shape of the work, and two of them correct claims made earlier in this document.

## D1 — The round-1 `Select.options` fix never reached the panel

`PropertiesPanel.tsx` keeps a name-based allowlist:

```ts
const DATA_SOURCE_PROPS = new Set(["data", "rows", "options", "items", "entries", "records"]);
```

and then, at the render site:

```ts
const showBinding = isBound || isDataSourceProp;
…
{showBinding ? ( <BindingControl … /> ) : ( <Control … /> )}
```

It is an **either/or**. Any prop with one of those six names renders
`BindingControl` *instead of* whatever control the registry declared. So
converting `Select.options` and `RadioGroup.options` to `type:"array",
control:"json"` in the previous session was correct in the registry and
**invisible in the editor** — the seeded defaults still land on drop, so the
component renders options, but the user cannot edit the list.

Nine of the 36 `actionPicker` props are shadowed the same way and never show
ActionPicker at all. Unshadowing has to happen *before* any registry conversion
means anything.

## D2 — A component's `value` is unrepresentable, so "self-managing" needs a prop first

The node schemas are `.strict()` and carry no `value` key
(`packages/schema/src/nodes/inputs.ts:154-168` for Slider, likewise Rating /
ColorPicker / DatePicker / TimePicker). The library prop schemas omit it too, and
the renderer never injects a handler — `dispatch.tsx:350-368` passes only
validated props plus style.

So the fix is not merely "add `useState`": there is **nothing to seed from**.
Each affected component needs a `defaultValue` prop added to its `.schema.ts`,
to the strict node schema, and to its registry entry. `Switch` already sets this
precedent with `defaultValue` / `defaultChecked`.

`Switch.tsx:26-55` is also the idiom to copy — it is the only variant in the repo
that re-syncs from the prop, which is what makes a Properties-panel edit move the
control on the canvas:

```ts
const isControlled = checked !== undefined && onChange !== undefined;
const [internal, setInternal] = React.useState(() => checked ?? defaultChecked ?? …);
React.useEffect(() => {
  if (checked !== undefined && onChange === undefined) setInternal(checked);
}, [checked, onChange]);
```

`SegmentedControl:15-17` gates on `value !== undefined` alone — the exact trap
the Switch comment warns about. Do not copy that one.

## D3 — Corrections to the C1/C2 counts above

- **`MaskedInput` and `Combobox` are not self-managing.** MaskedInput is
  conditionally controlled like DatePicker/TimePicker; Combobox owns its
  `open`/`query` state but its *selection* is parent-owned, so standalone it
  closes the list and shows nothing selected. The dead list is wider than C1 says
  and also includes `Input`, `Select` and `Textarea` under the same shape.
- **`Rating` has no named form control at all** — no input, no hidden field — so
  even once it is editable it submits nothing. `Slider` range mode renders two
  range inputs with no `name`. Both need a hidden input like `Switch.tsx:75`.
- **C2 said 8 misapplied ActionPickers; it is 7.** `Button.onClick` is the one
  legitimate use. Registry-wide the split is: 1 correct, 5 CTA-wrapper objects
  that merely look like actions (`FeatureCard.cta` needs an `href` ActionPicker
  cannot emit), 26 arrays, 4 objects.

---

# FIX LOG

## Phase 1 — `{$binding}` → `{{expr}}` — DONE, verified end to end

**What was wrong.** Three binding formats existed and the editor wrote the only
one nobody implemented:

| format | who emits it | who resolves it |
|---|---|---|
| `node.bind` | the v2 spec | only `Repeat` and `Text`; every input destructures and discards it |
| `"{{expr}}"` | the generation pipeline | `renderer/src/runtime/interpolate.ts` |
| `{$binding:"expr"}` | **the editor's Bindings tab** | **nothing** |

**Changes.**

- **`packages/patches/src/binding.ts` (new)** — single owner of the format:
  `isBinding` / `isMustacheBinding` / `isLegacyBinding` / `bindingExpression` /
  `toBindingValue` / `migrateBindingsDeep`. The predicates were previously
  duplicated in two panels, which is how the editor came to write a format it
  could read but not render.
- **`apply.ts:318`** — `bindProp` writes `toBindingValue(binding)`. An empty bind
  writes `""`, deliberately **not** `"{{}}"`: an empty template would resolve to
  nothing while still reading as bound, which is the same bug in a quieter form.
- **`apply.ts` unbind inverse** — used to test the *truthiness* of
  `prev.$binding`, so a toggled-but-unfilled bind took a different undo path.
  Now tests the shape, so undo is symmetric for empty and filled alike.
- **`Canvas.tsx` `normaliseSchema`** — runs `migrateBindingsDeep` over every
  node's props. This is the single path every page load goes through, so a page
  saved with the legacy object heals the moment it is opened. Also **exported**;
  `selection-integration.test.tsx` held a verbatim copy marked "(not exported)"
  that could drift while still passing, so it now imports the real one.
- **`validate.ts` `validateNoLegacyBindings`** — a commit-boundary guard naming
  the prop and its replacement. Prop *values* were previously unvalidated at
  commit, which is exactly why the object walked through to disk unnoticed.
- **`interpolate.ts` `interpolateDeep`** — the renderer now *forgives* a legacy
  object, resolving it as the template it meant to be. The editor heals pages it
  opens, but a project generated before the fix may never be opened again, so
  the renderer is where already-shipped apps get repaired.
- **Panels** — the write forks in `PropertiesPanel` and `BindingsPanel` (one
  branch wrote `"{{…}}"`, the other the object) collapsed to a single
  `bindProp` dispatch, and both now import the shared predicates.
- **`PropertiesPanel` bind-mode state** — new. With an empty bind now `""`, the
  value alone can no longer distinguish "bound, not yet typed" from "empty
  literal", so clicking *bind* and pausing dropped the user back to a text box.
  Bind-mode is an editor affordance, not document data, so it is held in panel
  state keyed by `nodeId::propName` and never reaches the schema.

**Also fixed on the way:** `interpolate.test.ts` "number formats with thousand
separators" asserted Western 3-digit grouping while the implementation correctly
uses the runtime's own locale. On a machine defaulting to `en-IN` it failed
against the perfectly correct `12,34,567`, and had been red in every run for
months. It now asserts that grouping *happened*, not which convention was used.

**Verification.** A legacy `{"$binding":"items[0].name"}` was planted in
`output/gh0mlpbp/src/schemas/input-lab-2.json`, then the page was opened:

- Button rendered **"Wireless Bluetooth Headphones"** — the binding resolved,
  rather than crashing. 0 render errors, no issue badge.
- Binding the Slider's `label` to `items[1].category` through the UI rendered
  **"Kitchen & Dining"** live, with no error at any point — including the
  toggle-before-typing state that used to break the node instantly.
- On disk afterwards: `"label": "{{items[1].category}}"` and
  `"label": "{{items[0].name}}"`, **0 occurrences of `$binding`**.

**Test baselines** (so later phases can tell regressions from pre-existing noise;
both sides freshly built, since a stale `dist/` silently changes these numbers):

| suite | before | after |
|---|---|---|
| frontend | 43/43 files | **44/44 files** (+1 new file) |
| patches | 5 files / 56 tests | **6 files / 68 tests** (+12) |
| renderer | 31 failing / 240 passing | **30 failing** (the locale fix) |
| engine | 2 failing | 2 failing |
| library | 37 failing / 935 passing | 37 failing / 935 passing |

17 new assertions across `packages/patches/tests/binding.test.ts` and
`frontend/src/__tests__/binding-migration.test.ts`.

**Known residue.** A page that is opened but not edited keeps the legacy object
on disk until its next save — the heal is in memory. This is harmless now that
the renderer forgives the shape, and it self-corrects on the next edit; rewriting
a user's file merely because they looked at a page would be worse.

## Phase 2 — one state contract for every input — DONE, verified in the live editor

**What was wrong.** The library had grown two incompatible contracts with nothing
to tell them apart. Roughly half the inputs held their own state and worked when
dropped on a page; the other half were fully controlled and expected a parent to
supply `value` AND `onChange`. Nothing supplies either when a node is rendered
from a page schema, so that half was dead — and, per D2, a component's `value`
was not even *expressible* in a `.strict()` node schema, so there was nothing to
seed from either.

**The contract, in one place.** New `packages/library/src/util/useFieldValue.ts`:

```ts
const isControlled = value !== undefined && onChange !== undefined;
```

Controlled requires **both**. `value` alone is a declarative INITIAL value —
the only thing a schema node can express — not a demand to be driven from
outside. Gating on `value !== undefined` alone is what produced "the toggle that
cannot be toggled": the registry supplies a default prop, the component decides
it is therefore controlled, and it waits forever for a parent that does not
exist. `SegmentedControl:15-17` still has that shape and is called out in the
hook's comment as the anti-pattern.

The declarative seed is re-read when it changes, so editing the prop in the
Properties panel moves the control on the canvas — without that the `useState`
initialiser has already run and the panel edit is invisible. A `firstRun` guard
keeps the effect from clobbering what the user just typed.

**A deliberate deviation from the plan.** The plan said to inline the pattern per
component, matching how Switch / NumberInput / MoneyInput / Calendar each carry
their own copy. I wrote a shared hook instead, because *per-component divergence
is the bug*: five components each invented their own answer to "am I controlled?"
and three got it wrong. Copying a twelve-line block into nine more files
preserves exactly the conditions that produced the split.

**Components moved onto the hook:** Slider, Rating, ColorPicker, DatePicker,
TimePicker, MaskedInput, Input, Select, Textarea. (`Select`'s hook call sits
above its empty-options early return — hooks cannot live behind a conditional.)

**Schema plumbing** — `defaultValue` added at all three levels, since it did not
previously exist anywhere:

- `packages/schema/src/nodes/inputs.ts` — on the shared `baseField` (covers
  Input, Textarea, Select, DatePicker, TimePicker, Checkbox…) plus individually
  on the nodes that don't use it (Slider, Rating, ColorPicker, MaskedInput).
  Slider's accepts a `[number, number]` pair for range mode.
- The library `.schema.ts` files that declare their own shape.
- The registry entries, so it is editable in the Properties panel.

**Form serialization gaps closed.**

- **Rating had no named form control at all** — no input, no hidden field — so
  inside a Form it submitted nothing even once it worked. It now carries a hidden
  input like `Switch.tsx:75`.
- **Slider range mode rendered two nameless inputs**, so a range slider
  contributed nothing to FormData. One hidden field now carries the pair.
- The two documented constraints were preserved: `FileUpload` renders its hidden
  input only when it has a value (FormData keeps the last value per name), and
  `KeyValueInput`'s hidden input is what makes a jsonb object visible.

**Behaviour improvements that fell out of the work.**

- Rating: clicking the current rating clears it. Previously a rating could be
  raised and lowered but never withdrawn.
- Slider: `showValue` now works in range mode too, showing `20 – 80`.
- Slider: the two range thumbs can no longer cross each other.
- Select: seeds from the first option rather than `""` — a native `<select>`
  whose value matches no `<option>` renders blank, which reads as broken.

**Registry props unblocked while in the entries** (early Phase 4 credit):
`Slider.step`, `Slider.showValue`, `TimePicker.min/max/step/disabled`,
`Rating.disabled`, `ColorPicker.disabled`.

**Verification — live editor, `/input-lab-2`:**

| control | before | after |
|---|---|---|
| Rating, click 4th star | 0 stars filled | **4 filled**, hidden input `"4"` |
| ColorPicker | no `onChange` at all → React read-only warning | **has `onChange`** |
| Slider / TimePicker / DatePicker / MaskedInput | frozen or value-less | **all have `onChange`** |
| page issue badge | **1 Issue** (the ColorPicker warning) | **none** |
| render errors | 0 | 0 |

**Tests.** New `packages/library/tests/field-value-contract.test.tsx` — 17
assertions across four groups: self-managing with no props; `value` without
`onChange` is a seed and stays editable; `value` + `onChange` defers to the
parent; `defaultValue` seeds, re-seeds on a panel edit, and does not clobber
typing in between. Plus FormData coverage for Rating and Slider range.

| suite | before | after |
|---|---|---|
| library | 37 failing / 935 passing | **24 failing / 988 passing** |
| frontend | 44/44 files | 44/44 files, 574 tests |
| patches | 68 passing | 68 passing |
| renderer | 30 failing | 30 failing |
| engine | 2 failing | 2 failing |

Library improved by 13 — the pre-existing failures were partly stale-`dist`
artifacts. None of the 24 remaining are in files this phase touched, and every
existing controlled-behaviour test (Slider / Rating / ColorPicker / TimePicker /
DatePicker) still passes, which is the regression net that matters here.

### Incident: recovered work lost to a silenced `git stash pop`

While establishing the library baseline I ran `git stash push` / `git stash pop`
with `>/dev/null 2>&1`. The pop **failed** — the intervening rebuild had modified
`packages/registry/dist/starter.json`, a *tracked* build artifact that was also
in the stash, so git refused to overwrite it — and the `&&` chain swallowed the
error. That silently reverted 582 files of tracked work from every prior session
(the registry `binding`→`bind` rename, renderer layout fixes, and all of Phase 1).

Caught it when registry entries showed `binding:` where the audit had recorded
`bind:`. Recovered by resetting the one blocking artifact (`git checkout --
packages/registry/dist/starter.json`) and re-popping; all 582 files restored,
stash list empty, six packages rebuilt with 0 errors, all phases verified intact.

Two lessons worth keeping: never silence a `git stash pop`, and `dist/` being
tracked means build artifacts can block a merge.

## Phases 3–7 — DONE (parallel agents, integrated)

Partitioned by **file ownership** rather than by phase, because 3b and 4 both
rewrite `starter.ts` and would have corrupted each other, while Phase 7 splits
across two packages.

### Phase 3a — the registry is no longer shadowed

`PropertiesPanel.isDataSourcePropFor` now excludes authorable types:

```ts
const AUTHORABLE_TYPES = new Set<string>(["array", "object"]);
DATA_SOURCE_PROPS.has(propName) && descriptor.type !== "number"
  && !AUTHORABLE_TYPES.has(descriptor.type)
```

(A `Set<string>` on purpose: `"object"` was being added to `PropDescriptor` by a
parallel agent, and a literal comparison would not have compiled until it landed.)

A prop the panel can author now gets its control **and** the bind toggle. With 13
data-named props converted to `type:"array"` the same pass, the only prop still
opening straight onto the data picker is `ResourceTimeline.items`. Chart/Table
therefore open on their (seeded) content with binding one clearly-labelled click
away — a deliberate trade, and arguably better: a dropped Chart now renders
sample data instead of an empty picker.

### Phase 3b — 35 of 36 ActionPickers retired

Exactly one remains, `Button.onClick`, and `registry.test.ts` now asserts the set
literally equals `["Button.onClick"]` so it cannot drift back. 26 arrays and 9
objects/CTA-wrappers moved to `control:"json"`; `"object"` added to
`PropDescriptor["type"]`.

**Four seeds deliberately left empty**, each because seeding would have caused a
real regression:

- `Form.fields` — `isDeclarative = fields.length > 0` (Form.tsx:131), so a seed
  flips every dropped Form to declarative mode and it **stops rendering its
  children**: the palette's droppable Form would silently ignore everything
  dragged into it.
- `Tabs.tabs` / `TabPanelWithDeepLink.tabs` — `buildTabDefs` reads each label
  from the TabPanel child, so a seeded entry overrides the label the user typed.
- `EmptyStateRich.illustration` — `{slug}` resolves to
  `frontend/public/illustrations/<slug>.svg`, **a directory that does not
  exist**, so any seed is a broken `<img>` on every drop.
- `MultiSelect.selected` — the initial selection; a seed hands every dropped node
  a choice the user never made.

Three defaults that would have broken things were caught in review and given the
component's own value instead: `FileUpload.maxSizeMb: 0` rejects *every* file
("over the 0 MB limit"); `MultiSelect.maxSelectionLabel: 0` collapses to
"N selected" instantly so chips never render; `Form.onSuccess.navigate: ""` wins
the `??` merge and kills the redirect. `Button["aria-label"]` is deliberately
left with **no** default, because the component renders it unguarded and a seeded
`""` would blank the accessible name of every button.

**Correction to the round-2 report:** `TableSortable.onSort` is not a `{key,dir}`
descriptor — the component *calls* it, `onSort(key, dir)` (TableSortable.tsx:31).
`{key,dir}` is the argument, not the value. Any non-null JSON there throws
"onSort is not a function" on the first header click, so it stays `null`.

### Phase 4 — 39 prop descriptors added

Button +11, FileUpload +7, IconButton +4, Combobox +3 (including `options`, which
did not exist at all — a search box that could never have anything to search),
Form +3, MultiSelect +3, DatePicker +1, `bind` for FilterBar/DateRangePicker, and
`validators` for Slider/ColorPicker/Rating/InputOTP/TimePicker.
**`Button.variant` widened** to `primary|secondary|accent|danger|ghost` — a red
destructive button is now expressible.

### Phase 5 — the icon picker

`IconButton` **never called `resolveIcon`**; that is why `icon: "Plus"` painted
the word "Plus". Now resolved, with an honest fallback: a string that looks like
an icon name but does not resolve renders a dashed placeholder carrying
`data-unresolved-icon`, while a deliberate glyph (`"✕"`, `"🗑"`) still renders
verbatim. `resolveIcon` matches on a canonical form, so `chevron-down`,
`ChevronDown` and `chevronDown` all land on the same icon — the tree had two
conventions and only one worked. `ICON_MAP` grew ~110 → ~185 rows to cover every
name the catalogue actually uses, and `ICON_NAMES` is exported to drive the
picker UI.

Found on the way: the backend shell generator maps doctor/physician to a
`stethoscope` icon that **had no row in ICON_MAP**, so every clinical nav item
generated with no glyph. Fixed, plus a drift guard that fails if any backend icon
or catalogue icon stops resolving.

### Phase 6 — a real options editor

`RowsControl` — rows with add / remove / reorder, per-field commit on blur (one
undo entry per edit, not per keystroke), Escape reverts. It sniffs the shape and
**refuses to touch what it does not understand**: arrays of strings and arrays of
objects sharing a `value`/`key`/`id` are editable; anything else falls back to
raw JSON with the reason shown. Recognised rows spread the original object, so
extra keys survive an edit.

Registered *both* as `control:"rows"` and as a delegation from `JsonControl` when
the value is an array — deliberately, because the registry emits `control:"json"`
today and shipping a better control that only activates after a different package
rebuilds is exactly the D1 failure repeating.

### Phase 7 — papercuts

- **A broken node is selectable again.** `NodeErrorBoundary`'s placeholder
  carried no `data-node-id`, so clicking the ⚠ box selected the *parent* and the
  user could not open Props for the node they had just broken. It now carries the
  id and names the failing prop.
- **Required props are marked**, derived from `component-contracts.json` — the
  snapshot the registry build extracts from the components' own Zod schemas
  (54 props resolve as required, including `FilterBar.chips` and
  `MultiSelect.options`). Advisory, never a gate; its limits are documented.
- **The bind toggle** gained `aria-label`/`aria-pressed` and now sits next to the
  word for its current mode (`Aa value` / `{ } bound`), so "Aa" no longer has to
  carry the meaning alone.

### Integration fixes (mine, not the agents')

- **`bind` on FilterBar / DateRangePicker / MultiSelect was authorable but
  inert.** Those three live in `packages/schema/src/nodes/enterprise.ts`, whose
  props objects declared no `bind`, so `validateProps` stripped the value before
  the component saw it — the control would have written into a void. Slot added
  to all three.
- **`Timeline` keyed its rows on an OPTIONAL `id`**, so every row got
  `key={undefined}`. Latent while the list was empty; the seeded entries exposed
  it. Now falls back to the index.
- **The whole-catalogue render sweep** in `editor-validation.test.tsx` crossed the
  5s default timeout as the catalogue grew 106 → 133 and the seeded defaults made
  components actually render content — turning the entire frontend suite red for
  a purely timing reason while the sweep itself reported
  `invalidProps=0 unknownType=0`. Given an explicit 30s with the reasoning in
  place, and its floor tightened from 102 to 129.

### Integration test results — zero new failures anywhere

| suite | baseline | after phases 3–7 |
|---|---|---|
| frontend | 44 files / 574 tests, 0 fail | **46 files / 607 tests, 0 fail** |
| patches | 68 pass | 68 pass |
| registry | — | **23 pass** |
| library | 24 fail / 988 pass | 24 fail / **1012** pass |
| renderer | 30 fail / 246 pass | 30 fail / **249** pass |
| engine | 2 fail / 45 pass | 2 fail / 45 pass |

All six packages build with 0 TS errors. The library/renderer/engine failures are
the pre-existing set (theming-contract, Heading type-scale, DescriptionList,
CameraCapture, Money, Stagger, Sidebar, no-rhythm-classes, data-feedback-nav) —
unchanged in count and identity, and outside the scope of these phases.

**Measurement note:** a suite run taken *while* packages were rebuilding reported
library at 1008 tests instead of 1036. Stale/mid-write `dist/` silently changes
these numbers, as it did once before in Phase 2. Always rebuild, then measure.
