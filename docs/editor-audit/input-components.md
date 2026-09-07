# INPUT components — Props / Style / Bindings / Tokens audit
Scope: Input, Textarea, Select, Checkbox, Switch, NumberInput, MoneyInput, RadioGroup
Method: registry (`packages/registry/dist/starter.js`) + contracts
(`packages/registry/dist/component-contracts.json`) + Zod (`packages/schema/src/nodes/inputs.ts`)
compared against the live editor, all 8 added to a real page `/layout-inputs` via the palette.

## The headline

**Every one of the 8 is committed to disk in a state its own schema rejects.**
Stored props, verbatim, straight from a palette click:

```
Input        {"label":"Label","placeholder":"","type":"text","binding":null,"validation":""}
Textarea     {"label":"Label","placeholder":"","rows":4,"binding":null}
Select       {"label":"Label","options":"","binding":null,"multiple":false}
Checkbox     {"label":"Check me","binding":null}
Switch       {"label":"Enabled","checked":false,"binding":null}
NumberInput  {"label":"Quantity","min":0,"max":100,"step":1,"binding":null}
MoneyInput   {"label":"Amount","currency":"USD","currencyEditable":false,"min":0,"step":0.01,"placeholder":"0.00","binding":null}
RadioGroup   {"label":"Choose one","binding":null}
```

`name` is `z.string().min(1)` — REQUIRED on every input — and **not one node has it**, because the
Props panel does not expose it. It commits anyway: `validateForCommit` only checks id uniqueness
and component-type closure, never Zod prop validation.

## Field-by-field

| Component | Panel shows | MISSING (contract has, panel does not) | DEAD (panel has, contract does not) |
|---|---|---|---|
| Input | label, placeholder, type, binding, validation | **name**, validators, iconLeft, iconRight | `binding`->`bind`, `validation`->`validators` |
| Textarea | label, placeholder, rows, binding | **name**, validators | `binding` |
| Select | label, options, binding, multiple | **name**, validators, optionsFrom, inlineAdd | `binding`, **`multiple`** (not in contract at all) |
| Checkbox | label, binding | **name**, validators | `binding` |
| Switch | label, checked, binding | **name**, disabled, size | `binding`, **`checked`** (not in contract) |
| NumberInput | label, min, max, step, binding | **name**, prefix, suffix, disabled, align, showSteppers, tabularNums | `binding` |
| MoneyInput | label, currency, currencyEditable, min, step, placeholder, binding | **name**, max, currencies, disabled, readOnly, required, value | **`binding`** — MoneyInput has NO `bind` in its contract, so it cannot be data-bound at all |
| RadioGroup | label, binding | **name**, **options** (REQUIRED, min 1), orientation, required, disabled | `binding` |

### I1. `name` is unreachable on all 8 — HIGH
Required by schema, exposed by nothing. It is the form-wiring key; without it a field has no
identity in a submitted form.

### I2. `binding` is a dead prop name on all 8 — HIGH
Registry declares `binding`; every consumer reads `bind` (`packages/schema/src/nodes/inputs.ts`
`baseField.bind`, and the compiler's `node.bind`). Zod is non-strict on the way in, so the value is
silently dropped. This is the 39-component defect the panel audit found, confirmed for the whole
input set.

### I3. `RadioGroup` cannot be given options — HIGH
`options: z.array(RadioOption).min(1)` is REQUIRED and the panel offers no control for it. A
dropped RadioGroup renders its label and nothing else. Live: `radiogroup-27sqeo` renders
"Choose one" with zero options.

### I4. `Select.options` is the wrong TYPE — HIGH
Panel control is `textarea` and stores `options: ""` (a string). Contract requires a non-empty
ARRAY of `{value,label}`. Every dropped Select is invalid and optionless.

### I5. `Switch.checked` and `Select.multiple` are dead controls — MEDIUM
Neither appears in its component contract. `checked` is also the prop that made Switch permanently
uncontrolled (fixed separately).

### I6. Autosave of tokens is rate-limited — HIGH (NEW, seen live)
Editor banner: `COULDN'T SAVE — Save failed: src/theme/tokens.custom.json -> HTTP 429`.
The user's changes stay unsaved. Token writes are hitting a rate limit.

## What DOES work
- **Style**: all 8 consume `node.style` (`resolveStyle` + `useMotion` present in each component;
  MoneyInput lives in `components/Money/Money.tsx`). Padding/radius/shadow/motion reach them.
- **Tokens**: the TOKENS tab is fully populated — full `primary` ramp `50:#c0c8d3` .. `950:#172554`,
  plus secondary/accent/surface/border/muted/text/sidebar/success/warning/error/info, Font family,
  Scale. (Was empty headings before the TokenEditor fix.)
- **Rendering**: Input, Textarea, Select, NumberInput, MoneyInput all render real controls at 520px.
  Checkbox / Switch / RadioGroup render their control but their `data-node-id` element is a
  `display:contents` wrapper measuring 0x0.
- **Click-to-insert** worked for all 8 (the B3 fix).
- Breakpoint switcher (ALL/SM/MD/LG/XL) is present on the Props panel.

---

# BEHAVIOURAL PASS (HMR quiet) — what actually works

## Exhaustive structural sweep: 30 of 41 input components have gaps
`binding` is a DEAD prop name on **24** of them (every consumer reads `bind`).
`name` — required by schema — is unreachable on ~20.
Clean (11): FilterBar, DateRangePicker, AddToCart, BulkActionBar, SavedViewsPicker,
GlobalSearch, SearchInput, KeyboardShortcuts, ThemeToggle, Wizard, FilterBuilder.
Worst: Calendar (12 props missing), FileUpload (9), NumberInput (8), MoneyInput (7).

## Props — WORKS end to end
Edited on the live Input and verified in the DOM:
`label` -> "Product name" OK · `placeholder` -> "e.g. Blue widget" OK · `type` -> `email` OK.
Panel fields for Input: label, placeholder, type, validation, binding(select).
The panel WRITES correctly; the defect is only WHICH fields it exposes.

## Style — PARTIALLY works. Padding + radius YES, background NO.
Written to disk correctly:
`{"width":"100%","maxWidth":"520px","background":"color.primary.100","padding":"spacing.6","radius":"radius.lg"}`
Rendered: padding **24px OK**, border-radius **12px OK**, background **transparent FAIL**.

### I7. The primary colour ramp is truncated to ONE step — HIGH (root cause of the above)
CSS vars actually emitted on the canvas root (206 total):
```
primary   : [50]                                             <-- 1 of 11
secondary : [50,100,200,300,400,500,600,700,800,900,950]     <-- 11
accent    : [50,100,200,300,400,500,600,700,800,900,950]     <-- 11
```
`--token-color-primary-100` and `-500` are UNSET, so any style referencing them paints nothing.
Cause: `output/gh0mlpbp/**/tokens.custom.json` declares `color.primary = {50: ...}` (and
`success = {50: ...}`), and the merge REPLACES the ramp instead of merging per-step, so
steps 100..950 never reach CSS.
**The Style panel offers exactly three primary options and TWO of them are dead.**

### I8. The Tokens panel shows a ramp the canvas cannot use — MEDIUM
The TOKENS tab deep-merges defaults for DISPLAY, so it shows a full 11-step primary ramp
(`50:#c0c8d3` .. `950:#172554`) while only step 50 exists as a CSS var. The panel disagrees
with what renders.

## Interaction — tested in the PREVIEW (:6503), not the editor
NOTE: in the EDITOR, controls deliberately do not respond — `useCanvasClick` calls
`preventDefault()` + `stopPropagation()` so a click selects the node. That is correct, not a bug.
Typing DOES reach the editor canvas (keystrokes are not intercepted).

| Control | Preview result |
|---|---|
| Input | typing works (value "hello") |
| Checkbox | **toggles** false -> true |
| Switch | **DOES NOT TOGGLE** — stuck at false |
| Select | **0 options** |
| RadioGroup | **0 radio inputs** |

### I9. Switch is permanently off in the preview and generated app — HIGH
`Switch.tsx` logic is CORRECT (`isControlled = checked !== undefined && onChange !== undefined`).
The preview supplies an `onChange`, so with the palette's baked-in `checked: false` the switch
becomes genuinely controlled by a prop that never changes. Checkbox toggles precisely because it
carries no `checked`.
**Fix: drop `checked` from the registry defaults — it is not in Switch's contract either.**

## STILL NOT VERIFIED (honest list)
- Bindings tab end-to-end: the binding control is a `<select>` reporting "No page data sources —",
  so nothing could be bound on this page. Needs a page WITH a dataSource.
- Breakpoint switcher (SM/MD/LG/XL) on an input.
- Undo/redo of a prop edit.
- Behaviour (not structure) of the other 33 input components.

---

# FIXES APPLIED + FINAL VERIFICATION

| ID | Bug | Status | Evidence |
|---|---|---|---|
| I2 | `binding` — a prop name NO contract has — exposed on 39 entries | **FIXED** | 30 renamed to `bind`, 9 removed (their contracts have neither). Now: **0 entries expose `binding`**, 32 expose `bind`, 0 expose `bind` without contract support. |
| I1 | `name` required by schema, unreachable on every input | **FIXED** | Added to 21 registry entries AND auto-seeded in `buildDroppedNode` from the node id, so a fresh field is valid with no typing. Live: `{"name":"input_mb4j6x", ...}`. Panel now shows a NAME control. |
| I4 | `Select.options` was a comma-separated STRING via textarea | **FIXED** | Now `type:"array"`, `control:"json"`, seeded with two real options. Live: `select.options.length` 0 -> **2**. |
| I3 | `RadioGroup.options` REQUIRED and exposed by nothing | **FIXED** | Added options + orientation + required + disabled. Live: `input[type=radio]` 0 -> **2**. |
| I5 | `Switch.checked` / `Select.multiple` — props no contract has | **FIXED** | Removed. |
| — | `Input.validation` (string) vs contract `validators` (object) | **FIXED** | Renamed to `validators`, `control:"json"`. |
| I7 | Primary colour ramp truncated to ONE step | **FIXED** | `Canvas.tsx` merged `liveTokens.color` over `defaultTokens.color` at the RAMP level, so `{primary:{50}}` annihilated steps 100..950. Now merges per step. Live: primary `[50]` -> **all 11**, total CSS vars 206 -> 230, and `--token-color-primary-100` resolves `#dbeafe` with the Input's background computing `rgb(219,234,254)` — **Style->Background now paints**. |
| I9 | "Switch permanently off" | **WITHDRAWN — my diagnosis was wrong** | The preview does not hydrate schema-rendered nodes (`hasReactProps: false` on the switch button; only 8 of 54 sampled elements have React fibers). The Checkbox "toggling" was native HTML, not React. No Switch defect demonstrated. Removing the dead `checked` prop stands on its own merits. |
| I6 | Token autosave `HTTP 429` | **NOT FIXED** | Rate limit on `src/theme/tokens.custom.json` writes. Untouched. |

## Final structural state — input category (41 components)
- **DEAD props: 0** (was 24 components exposing dead `binding`)
- Fully clean: **13** (was 11)
- Still missing at least one contract prop: **28**

## The three previously-unverified behaviours — ALL NOW VERIFIED
1. **Bindings end-to-end — WORKS.** On `/items` (a page with real dataSources) the bind select
   offers `items`, `totalInventoryValue.itemCount`, `totalInventoryValue.totalValue`,
   `lowStockCount.lowStockCount`, plus scopes `form.` `row.` `state.` `global.user.id`.
   The earlier "No page data sources —" was CORRECT: that page has none.
2. **Undo/redo — WORKS, and precisely.** After binding a new Input: undo #1 reverted the
   *binding* (18 nodes), undo #2 removed the *node* (17). `/items` restored to its original state.
3. **Breakpoint switcher — WORKS.** Selected SM, set a label, DOM rendered "SM only label" with
   **no raw-JSON envelope leak** — Phase 0's fix confirmed.

## Also confirmed live while testing
- Props edits reach the DOM: label / placeholder / type all verified.
- Style padding + radius apply (24px / 12px) — and now background too.
- DENSITY offers compact/comfortable/**spacious**; RADIUS SCALE offers sharp/soft/**round**.
- **Editor canvas deliberately swallows clicks** (`useCanvasClick` preventDefault+stopPropagation)
  so a click selects the node. Controls not responding in the EDITOR is correct, not a bug.

## STILL OPEN
- **I6** token autosave 429.
- **28 components still missing contract props** — `name` is fixed everywhere it was required, but
  e.g. NumberInput lacks prefix/suffix/disabled/align/showSteppers/tabularNums (6), Calendar 10,
  Button 11, FileUpload 7, MoneyInput 6. These are additive panel work, not breakage.
