# Missing Components — Wave 1: Form Inputs — Design Spec

**Date:** 2026-06-03
**Status:** Approved (design) — pending implementation plan
**Program:** "Implement all missing components" — 5 waves, each its own spec → plan → subagent-driven build with approval between waves. This spec covers **Wave 1**.
**Reference:** deep-research missing-components audit (verified 3-0 against shadcn/ui, Radix, MUI, Ant Design) + the component-addition recipe traced from `Checkbox`.

---

## 1. Goal

Add 6 standard form-input components to Tentoro Forge, **fully wired** so the AI generator can emit them and the renderer renders them:

**RadioGroup, Switch, Slider (with range mode), Combobox, FileUpload, NumberInput.**

Constraints (confirmed): **dependency-free** (plain React + Tailwind + StyleSlot, optional CVA `variants.ts`, reusing existing inline-dropdown patterns from `MultiSelect`/`FilterBar`); RadioGroup and Switch are **also added to `Form`'s field-kind union**.

## 2. The per-component recipe (identical for all 6)

Derived from tracing `Checkbox` end-to-end. For each `<Name>`:

1. **`packages/library/src/components/<Name>/<Name>.tsx`** — `"use client"` React component; accepts `style?: StyleSlotT` → `resolveStyle(style)` + `useMotion(style?.motion)`; named export (no default); `data-<name>` runtime hook attribute; optional `__on*` test-injection props following the `Button.__dispatch` convention where an interaction matters.
2. **`packages/library/src/components/<Name>/<Name>.schema.ts`** — softened Zod `<Name>Props = z.object({...}).strict()` (props optional/with defaults; include `className?` and `style?: z.record(z.unknown())`), `export type <Name>PropsType`.
3. **`packages/schema/src/nodes/inputs.ts`** — canonical strict `<Name>Node = z.object({ id?, type: z.literal("<Name>"), props: z.object({...}).strict(), style: StyleSlot.optional() }).strict()` + `export type <Name>NodeT`.
4. **`packages/schema/src/page.ts`** — import `<Name>Node` and add it to the `NodeV2` discriminated union array.
5. **`packages/registry/src/starter.ts`** — `<Name>Entry: RegistryEntry` (category `"input"`, Lucide `icon`, `description`, `slots: { type: "leaf" }`, `props` metadata with `control`/`group`/`default`) + add `<Name>: <Name>Entry` to the `starterRegistry` object → surfaced to the AI via `registryDigest()`.
6. **`packages/library/src/index.ts`** — 3 export lines (`<Name>`, `<Name>Props`, `type <Name>PropsType`).
7. **Tests** — `packages/library/tests/components/<Name>.test.tsx` (render + props + key interaction via `@testing-library/react`); plus `<Name>.schema.test.ts` for components with non-trivial props (Combobox, Slider, NumberInput).

The renderer requires **no change** — `LibraryDispatcher` renders any registered type automatically.

## 3. Component specifications (canonical node props)

- **RadioGroup** — `{ name?, label?, value?, options: { value: string; label: string; disabled?: boolean }[], orientation?: "vertical"|"horizontal" (default vertical), required?, disabled? }`. Single-select; keyboard arrow navigation; `data-radio-group`.
- **Switch** — `{ name?, label?, checked?: boolean (default false), disabled?, size?: "sm"|"md" }`. Boolean on/off; `role="switch"`, `aria-checked`; `data-switch`.
- **Slider** — `{ name?, label?, min? (0), max? (100), step? (1), value?: number | [number, number], range?: boolean (default false), showValue?: boolean }`. `range:true` → two thumbs returning `[lo, hi]`; `role="slider"`, `aria-valuenow/min/max`; `data-slider`.
- **Combobox** — `{ name?, label?, options: { value: string; label: string }[], value?, placeholder?, filterable?: boolean (default true), clearable?: boolean }`. Typeahead: text input filters the option list in an inline popover (reuse `MultiSelect`/`FilterBar` inline-dropdown approach); keyboard up/down/enter/escape; `data-combobox`.
- **FileUpload** — `{ name?, label?, accept?: string, multiple?: boolean, maxSizeMb?: number, hint?: string }`. Styled dropzone + hidden `<input type="file">`; drag-over highlight; lists selected files with size + remove; **client-only** (surfaces a `File[]`; no upload endpoint this wave). `data-file-upload`.
- **NumberInput** — `{ name?, label?, min?, max?, step? (1), value?: number, precision?: number, prefix?: string, suffix?: string, disabled? }`. Numeric `<input>` flanked by −/+ stepper buttons; clamps to min/max; respects `step`/`precision`; `data-number-input`. (Distinct from the existing `Form` `number` field kind — this is the richer standalone control.)

## 4. Form integration

`Form` (`packages/library/src/components/Form/Form.tsx`) defines a `Field` union (currently `text | email | number | textarea | select | checkbox | date`). Extend it with:
- `{ kind: "radio"; name; label; required?; options: { value; label }[] }` → renders `RadioGroup` inside the form, registered via react-hook-form.
- `{ kind: "switch"; name; label }` → renders `Switch`, registered via react-hook-form.

Both must round-trip through `react-hook-form` (`register`/`Controller`) so declarative forms collect their values into the submit payload (consistent with the existing dispatch-seam behavior).

## 5. Error handling / edge cases

- Empty/missing `options` (RadioGroup, Combobox) → render an empty control, not a crash.
- Slider `value` out of `[min,max]` → clamp; `range` with a scalar `value` → coerce to `[value, value]`.
- NumberInput non-numeric typed input → ignore/clamp on blur; respect `min`/`max`.
- FileUpload over `maxSizeMb` or wrong `accept` → reject the file with an inline message; never throw.
- All Zod node schemas `.strict()`; softened library schemas tolerate generator-emitted extras (`className`, `style`).

## 6. Testing

- **Per component (vitest + @testing-library/react):** renders with defaults; reflects controlled props; the key interaction fires the handler (RadioGroup select → value; Switch toggle → checked; Slider drag/keyboard → value; Combobox type→filter→select; FileUpload file-drop → files; NumberInput +/− → value, clamps at min/max).
- **Schema tests:** `Combobox/Slider/NumberInput.schema.test.ts` — valid props parse; bad shapes rejected; defaults applied.
- **Form integration test:** a declarative `Form` with `radio` + `switch` fields collects both values into the dispatched payload.
- **Wave verification:** rebuild `packages/{library,schema,registry}` (`tsc`); run `packages/library` + `packages/schema` test suites green; assert `registryDigest()` output now contains all 6 component names (so the AI generator can see them).

## 7. Risks

- **Combobox without a dependency** — building a robust typeahead/popover by hand is the most involved of the six; reuse the existing inline-dropdown pattern and keep scope to filter + select + keyboard nav (no async/remote options this wave).
- **Form field-kind extension** — must not break existing `Form` declarative or container modes; covered by the Form integration test.
- **Node-union growth** — `page.ts` `NodeV2` is a large discriminated union (it previously OOM'd before being switched to `z.discriminatedUnion`); adding 6 literals is safe, but keep node props lean.
- **Registry digest size** — 6 new entries grow the AI prompt slightly; keep `description`/prop metadata concise.
