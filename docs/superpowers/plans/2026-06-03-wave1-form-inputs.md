# Missing Components — Wave 1 (Form Inputs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 fully-wired form-input components to Tentoro Forge — `Switch`, `NumberInput`, `RadioGroup`, `Slider`, `FileUpload`, `Combobox` — so the AI generator can emit them and the renderer renders them.

**Architecture:** Each component follows the traced `Checkbox` recipe: a `"use client"` React component (plain React + Tailwind + StyleSlot, no new deps), a softened library Zod schema, a strict canonical schema node added to the `NodeV2` discriminated union, a `starterRegistry` metadata entry (so the AI sees it via `registryDigest()`), index exports, and vitest tests. The renderer's `LibraryDispatcher` renders any registered type automatically — no renderer change. Plus `Form` gains `radio` + `switch` field kinds.

**Tech Stack:** React + TypeScript + Tailwind, Zod (schema), Vitest + @testing-library/react. Monorepo packages: `@tentoroforge/library`, `@tentoroforge/schema`, `@tentoroforge/registry`.

**Reference spec:** `docs/superpowers/specs/2026-06-03-wave1-form-inputs-design.md`

---

## Conventions (confirmed from the codebase)

- Tests run from each package dir: `cd packages/library && ../../node_modules/.bin/vitest run <path>`. Component tests live in `packages/library/tests/components/`.
- Component file pattern (from `Checkbox.tsx`): `"use client"`; `import type { StyleSlotT } from "@tentoroforge/schema"`; `import { resolveStyle } from "../../style/resolveStyle"`; `import { useMotion } from "../../style/useMotion"`; named export; root element carries `data-<name>=""`, `style={resolveStyle(style)}`, `{...useMotion(style?.motion)}`.
- Library schema pattern (from `Checkbox.schema.ts`): softened `z.object({...})` with `className?: z.string().optional()` and `style?: z.record(z.unknown()).optional()`; `export type <Name>PropsType = z.infer<...>`.
- Node schema pattern (from `packages/schema/src/nodes/inputs.ts`): `import { StyleSlot } from "../style-slot"`; strict `z.object({ id: z.string().min(1).optional(), type: z.literal("<Name>"), props: z.object({...}).strict(), style: StyleSlot.optional() }).strict()`.
- Registry entry pattern (from `starter.ts` `checkboxEntry`): `RegistryEntry` = `{ name, category: "input", icon, description, slots: { type: "leaf" }, props: Record<string, PropDescriptor> }`; `PropDescriptor` = `{ type: "string"|"number"|"boolean"|"enum"|"action"|"binding", default?, options?, control: ControlType, group: "content"|"style"|"state"|"behavior"|"data", description? }`. `ControlType` includes `text|textarea|number|select|toggle|color|spacing|binding|actionPicker|iconPicker`.
- Wiring points: `packages/library/src/index.ts` (3 export lines per component, near the other input exports ~line 172-182); `packages/schema/src/page.ts` (import from `./nodes/inputs` at line 56, add node to the `z.discriminatedUnion("type", [...])` array ~line 373-412); `packages/registry/src/starter.ts` (`starterRegistry` object ~line 2278, add `<Name>: <name>Entry,`).

## File Structure (per component `<Name>`)
- Create `packages/library/src/components/<Name>/<Name>.tsx`
- Create `packages/library/src/components/<Name>/<Name>.schema.ts`
- Create `packages/library/tests/components/<Name>.test.tsx`
- Edit `packages/library/src/index.ts` (+3 export lines)
- Edit `packages/schema/src/nodes/inputs.ts` (+`<Name>Node`)
- Edit `packages/schema/src/page.ts` (+import, +union entry)
- Edit `packages/registry/src/starter.ts` (+`<name>Entry`, +`starterRegistry` line)

Tasks ordered simplest→hardest: **Switch → NumberInput → RadioGroup → Slider → FileUpload → Combobox**, then **Form integration**, then **wave verification**.

---

## Task 1: Switch

**Files:** Create `packages/library/src/components/Switch/Switch.{tsx,schema.ts}`, `packages/library/tests/components/Switch.test.tsx`; edit `packages/library/src/index.ts`, `packages/schema/src/nodes/inputs.ts`, `packages/schema/src/page.ts`, `packages/registry/src/starter.ts`.

- [ ] **Step 1: Write the failing test** — `packages/library/tests/components/Switch.test.tsx`

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Switch } from "../../src/components/Switch/Switch";
import { SwitchProps } from "../../src/components/Switch/Switch.schema";

describe("Switch", () => {
  it("renders a switch reflecting checked state", () => {
    render(<Switch name="active" label="Active" checked />);
    expect(screen.getByRole("switch", { name: "Active" })).toHaveAttribute("aria-checked", "true");
  });
  it("toggles via onChange when clicked", async () => {
    const onChange = vi.fn();
    render(<Switch name="active" label="Active" checked={false} onChange={onChange} />);
    await userEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith(true);
  });
  it("does not fire when disabled", async () => {
    const onChange = vi.fn();
    render(<Switch name="x" label="X" disabled onChange={onChange} />);
    await userEvent.click(screen.getByRole("switch"));
    expect(onChange).not.toHaveBeenCalled();
  });
  it("validates props via SwitchProps (softened)", () => {
    expect(() => SwitchProps.parse({ name: "a", label: "A" })).not.toThrow();
    expect(() => SwitchProps.parse({})).not.toThrow();
  });
});
```

- [ ] **Step 2: Run — expect FAIL** (module missing): `cd packages/library && ../../node_modules/.bin/vitest run tests/components/Switch.test.tsx`

- [ ] **Step 3: Implement** — `packages/library/src/components/Switch/Switch.schema.ts`

```ts
import { z } from "zod";

export const SwitchProps = z.object({
  name:      z.string().default("switch"),
  label:     z.string().optional(),
  disabled:  z.boolean().optional(),
  size:      z.enum(["sm", "md"]).default("md"),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type SwitchPropsType = z.infer<typeof SwitchProps>;
```

`packages/library/src/components/Switch/Switch.tsx`

```tsx
"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SwitchPropsType } from "./Switch.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface SwitchProps extends SwitchPropsType {
  style?: StyleSlotT;
  checked?: boolean;
  onChange?: (checked: boolean) => void;
}

export function Switch({ name, label, disabled, size = "md", style, checked = false, onChange }: SwitchProps) {
  const track = size === "sm" ? "h-4 w-7" : "h-5 w-9";
  const knob = size === "sm" ? "h-3 w-3" : "h-4 w-4";
  const shift = checked ? (size === "sm" ? "translate-x-3.5" : "translate-x-4") : "translate-x-0.5";
  return (
    <div className="flex items-center gap-2" data-switch="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label ?? name}
        disabled={disabled}
        onClick={onChange ? () => onChange(!checked) : undefined}
        className={`relative inline-flex ${track} shrink-0 cursor-pointer items-center rounded-full transition-colors ${checked ? "bg-primary" : "bg-input"} disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
      >
        <span className={`${knob} ${shift} inline-block transform rounded-full bg-white shadow transition-transform`} />
      </button>
      {label && <label className="text-sm font-medium text-foreground select-none">{label}</label>}
    </div>
  );
}
```

Edit `packages/library/src/index.ts` — add after the Checkbox export block (~line 182):

```ts
export { Switch } from "./components/Switch/Switch";
export { SwitchProps } from "./components/Switch/Switch.schema";
export type { SwitchPropsType } from "./components/Switch/Switch.schema";
```

Edit `packages/schema/src/nodes/inputs.ts` — append:

```ts
export const SwitchNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Switch"),
  props: z.object({
    name:     z.string().min(1),
    label:    z.string().min(1),
    checked:  z.boolean().optional(),
    disabled: z.boolean().optional(),
    size:     z.enum(["sm", "md"]).optional(),
    bind:     z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type SwitchNodeT = z.infer<typeof SwitchNode>;
```

Edit `packages/schema/src/page.ts` — line 56 import, add `SwitchNode`:
```ts
import { InputNode, SelectNode, TextareaNode, CheckboxNode, DatePickerNode, SwitchNode } from "./nodes/inputs";
```
and add `SwitchNode,` to the `z.discriminatedUnion("type", [...])` array (next to `CheckboxNode,` ~line 394).

Edit `packages/registry/src/starter.ts` — add entry (near `checkboxEntry`):
```ts
export const switchEntry: RegistryEntry = {
  name: "Switch",
  category: "input",
  icon: "ToggleLeft",
  description: "Boolean on/off toggle switch.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "Enabled", control: "text",    group: "content",  description: "Switch label." },
    checked: { type: "boolean", default: false,     control: "toggle",  group: "state",    description: "On/off state." },
    binding: { type: "binding", default: null,      control: "binding", group: "data",     description: "Data path to bind the on/off state." },
  },
};
```
and add to the `starterRegistry` object (~line 2292, next to `Checkbox: checkboxEntry,`): `Switch: switchEntry,`.

- [ ] **Step 4: Run — expect PASS** (4 tests): `cd packages/library && ../../node_modules/.bin/vitest run tests/components/Switch.test.tsx`

- [ ] **Step 5: Commit**
```bash
git add packages/library/src/components/Switch packages/library/tests/components/Switch.test.tsx packages/library/src/index.ts packages/schema/src/nodes/inputs.ts packages/schema/src/page.ts packages/registry/src/starter.ts
git commit -m "feat(library): add Switch component (fully wired, TDD)"
```

---

## Task 2: NumberInput

**Files:** same shape as Task 1, for `NumberInput`.

- [ ] **Step 1: Write the failing test** — `packages/library/tests/components/NumberInput.test.tsx`

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NumberInput } from "../../src/components/NumberInput/NumberInput";
import { NumberInputProps } from "../../src/components/NumberInput/NumberInput.schema";

describe("NumberInput", () => {
  it("renders the value", () => {
    render(<NumberInput name="qty" label="Qty" value={5} />);
    expect(screen.getByRole("spinbutton")).toHaveValue(5);
  });
  it("increments by step on + and clamps to max", async () => {
    const onChange = vi.fn();
    render(<NumberInput name="qty" label="Qty" value={9} max={10} step={1} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: /increment/i }));
    expect(onChange).toHaveBeenCalledWith(10);
    onChange.mockClear();
    render(<NumberInput name="q2" label="Q2" value={10} max={10} step={1} onChange={onChange} />);
    await userEvent.click(screen.getAllByRole("button", { name: /increment/i })[1]);
    expect(onChange).toHaveBeenCalledWith(10); // clamped
  });
  it("decrements and clamps to min", async () => {
    const onChange = vi.fn();
    render(<NumberInput name="q" label="Q" value={0} min={0} step={1} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: /decrement/i }));
    expect(onChange).toHaveBeenCalledWith(0); // clamped at min
  });
  it("validates props", () => {
    expect(() => NumberInputProps.parse({ name: "n", label: "N" })).not.toThrow();
    expect(() => NumberInputProps.parse({})).not.toThrow();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**: `cd packages/library && ../../node_modules/.bin/vitest run tests/components/NumberInput.test.tsx`

- [ ] **Step 3: Implement** — `NumberInput.schema.ts`

```ts
import { z } from "zod";
export const NumberInputProps = z.object({
  name:      z.string().default("number"),
  label:     z.string().optional(),
  min:       z.number().optional(),
  max:       z.number().optional(),
  step:      z.number().default(1),
  prefix:    z.string().optional(),
  suffix:    z.string().optional(),
  disabled:  z.boolean().optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type NumberInputPropsType = z.infer<typeof NumberInputProps>;
```

`NumberInput.tsx`

```tsx
"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { NumberInputPropsType } from "./NumberInput.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface NumberInputProps extends NumberInputPropsType {
  style?: StyleSlotT;
  value?: number;
  onChange?: (value: number) => void;
}

function clamp(n: number, min?: number, max?: number): number {
  if (min !== undefined && n < min) return min;
  if (max !== undefined && n > max) return max;
  return n;
}

export function NumberInput({ name, label, min, max, step = 1, prefix, suffix, disabled, style, value = 0, onChange }: NumberInputProps) {
  const set = (n: number) => onChange?.(clamp(n, min, max));
  return (
    <div className="flex flex-col gap-1" data-number-input="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label className="text-sm font-medium text-foreground">{label}</label>}
      <div className="inline-flex items-center rounded-md border border-input">
        <button type="button" aria-label="decrement" disabled={disabled} onClick={() => set(value - step)}
          className="px-2 py-1 text-foreground disabled:opacity-50">−</button>
        {prefix && <span className="pl-1 text-sm text-muted-foreground">{prefix}</span>}
        <input
          type="number" role="spinbutton" name={name} value={value} min={min} max={max} step={step} disabled={disabled}
          onChange={(e) => set(Number(e.target.value))}
          className="w-16 border-x border-input bg-transparent px-2 py-1 text-center text-sm focus-visible:outline-none" />
        {suffix && <span className="pr-1 text-sm text-muted-foreground">{suffix}</span>}
        <button type="button" aria-label="increment" disabled={disabled} onClick={() => set(value + step)}
          className="px-2 py-1 text-foreground disabled:opacity-50">+</button>
      </div>
    </div>
  );
}
```

`index.ts` (+3 lines):
```ts
export { NumberInput } from "./components/NumberInput/NumberInput";
export { NumberInputProps } from "./components/NumberInput/NumberInput.schema";
export type { NumberInputPropsType } from "./components/NumberInput/NumberInput.schema";
```

`packages/schema/src/nodes/inputs.ts` (append):
```ts
export const NumberInputNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("NumberInput"),
  props: z.object({
    name:     z.string().min(1),
    label:    z.string().min(1),
    min:      z.number().optional(),
    max:      z.number().optional(),
    step:     z.number().optional(),
    prefix:   z.string().optional(),
    suffix:   z.string().optional(),
    disabled: z.boolean().optional(),
    bind:     z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type NumberInputNodeT = z.infer<typeof NumberInputNode>;
```

`page.ts`: add `NumberInputNode` to the inputs import (line 56) and to the union array.

`starter.ts` entry + `starterRegistry` line `NumberInput: numberInputEntry,`:
```ts
export const numberInputEntry: RegistryEntry = {
  name: "NumberInput",
  category: "input",
  icon: "Hash",
  description: "Numeric input with +/- steppers.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "Quantity", control: "text",    group: "content",  description: "Field label." },
    min:     { type: "number",  default: 0,          control: "number",  group: "behavior", description: "Minimum value." },
    max:     { type: "number",  default: 100,        control: "number",  group: "behavior", description: "Maximum value." },
    step:    { type: "number",  default: 1,          control: "number",  group: "behavior", description: "Increment step." },
    binding: { type: "binding", default: null,       control: "binding", group: "data",     description: "Data path to bind the value." },
  },
};
```

- [ ] **Step 4: Run — expect PASS**: `cd packages/library && ../../node_modules/.bin/vitest run tests/components/NumberInput.test.tsx`
- [ ] **Step 5: Commit** `git add ... && git commit -m "feat(library): add NumberInput component (fully wired, TDD)"`

---

## Task 3: RadioGroup

- [ ] **Step 1: Failing test** — `packages/library/tests/components/RadioGroup.test.tsx`

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RadioGroup } from "../../src/components/RadioGroup/RadioGroup";
import { RadioGroupProps } from "../../src/components/RadioGroup/RadioGroup.schema";

const opts = [{ value: "a", label: "Option A" }, { value: "b", label: "Option B" }];

describe("RadioGroup", () => {
  it("renders a radio per option with the selected one checked", () => {
    render(<RadioGroup name="g" label="Pick" options={opts} value="b" />);
    expect(screen.getByRole("radio", { name: "Option B" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Option A" })).not.toBeChecked();
  });
  it("fires onChange with the option value when selected", async () => {
    const onChange = vi.fn();
    render(<RadioGroup name="g" label="Pick" options={opts} value="a" onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: "Option B" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });
  it("renders nothing for empty options without crashing", () => {
    render(<RadioGroup name="g" label="Pick" options={[]} />);
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
  });
  it("validates props", () => {
    expect(() => RadioGroupProps.parse({ name: "g", options: opts })).not.toThrow();
    expect(() => RadioGroupProps.parse({})).not.toThrow();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**.
- [ ] **Step 3: Implement** — `RadioGroup.schema.ts`

```ts
import { z } from "zod";
const Option = z.object({ value: z.string(), label: z.string(), disabled: z.boolean().optional() });
export const RadioGroupProps = z.object({
  name:        z.string().default("radio"),
  label:       z.string().optional(),
  options:     z.array(Option).default([]),
  orientation: z.enum(["vertical", "horizontal"]).default("vertical"),
  required:    z.boolean().optional(),
  disabled:    z.boolean().optional(),
  bind:        z.string().optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type RadioGroupPropsType = z.infer<typeof RadioGroupProps>;
```

`RadioGroup.tsx`

```tsx
"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { RadioGroupPropsType } from "./RadioGroup.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface RadioGroupProps extends RadioGroupPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

export function RadioGroup({ name, label, options = [], orientation = "vertical", disabled, style, value, onChange }: RadioGroupProps) {
  return (
    <div className="flex flex-col gap-1.5" role="radiogroup" aria-label={label ?? name}
      data-radio-group="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <span className="text-sm font-medium text-foreground">{label}</span>}
      <div className={orientation === "horizontal" ? "flex flex-row gap-4" : "flex flex-col gap-2"}>
        {options.map((o) => (
          <label key={o.value} className="flex items-center gap-2 text-sm text-foreground cursor-pointer select-none">
            <input
              type="radio" name={name} value={o.value} checked={value === o.value}
              disabled={disabled || o.disabled}
              onChange={onChange ? () => onChange(o.value) : undefined}
              className="h-4 w-4 border-input text-primary accent-primary focus-visible:ring-2 focus-visible:ring-ring" />
            {o.label}
          </label>
        ))}
      </div>
    </div>
  );
}
```

`index.ts` (+3 lines for `RadioGroup` / `RadioGroupProps` / `RadioGroupPropsType`).

`inputs.ts` (append):
```ts
const RadioOption = z.object({ value: z.string().min(1), label: z.string().min(1), disabled: z.boolean().optional() }).strict();
export const RadioGroupNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("RadioGroup"),
  props: z.object({
    name:        z.string().min(1),
    label:       z.string().optional(),
    options:     z.array(RadioOption).min(1),
    orientation: z.enum(["vertical", "horizontal"]).optional(),
    required:    z.boolean().optional(),
    bind:        z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type RadioGroupNodeT = z.infer<typeof RadioGroupNode>;
```

`page.ts`: import + union add `RadioGroupNode`.

`starter.ts` entry + `RadioGroup: radioGroupEntry,`:
```ts
export const radioGroupEntry: RegistryEntry = {
  name: "RadioGroup",
  category: "input",
  icon: "CircleDot",
  description: "Single-select radio option group.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "Choose one", control: "text",    group: "content", description: "Group label." },
    binding: { type: "binding", default: null,         control: "binding", group: "data",    description: "Data path to bind the selected value." },
  },
};
```

- [ ] **Step 4: Run — expect PASS**. **Step 5: Commit** `feat(library): add RadioGroup component (fully wired, TDD)`.

---

## Task 4: Slider

- [ ] **Step 1: Failing test** — `packages/library/tests/components/Slider.test.tsx`

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { Slider } from "../../src/components/Slider/Slider";
import { SliderProps } from "../../src/components/Slider/Slider.schema";

describe("Slider", () => {
  it("renders a single slider with aria values", () => {
    render(<Slider name="vol" label="Volume" min={0} max={10} value={4} />);
    const s = screen.getByRole("slider");
    expect(s).toHaveAttribute("aria-valuenow", "4");
    expect(s).toHaveAttribute("aria-valuemin", "0");
    expect(s).toHaveAttribute("aria-valuemax", "10");
  });
  it("fires onChange with the new numeric value", () => {
    const onChange = vi.fn();
    render(<Slider name="vol" label="Volume" min={0} max={10} value={4} onChange={onChange} />);
    fireEvent.change(screen.getByRole("slider"), { target: { value: "7" } });
    expect(onChange).toHaveBeenCalledWith(7);
  });
  it("renders two thumbs in range mode and emits a tuple", () => {
    const onChange = vi.fn();
    render(<Slider name="r" label="Range" min={0} max={100} range value={[20, 80]} onChange={onChange} />);
    const sliders = screen.getAllByRole("slider");
    expect(sliders).toHaveLength(2);
    fireEvent.change(sliders[1], { target: { value: "90" } });
    expect(onChange).toHaveBeenCalledWith([20, 90]);
  });
  it("validates props", () => {
    expect(() => SliderProps.parse({ name: "s" })).not.toThrow();
    expect(() => SliderProps.parse({})).not.toThrow();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**.
- [ ] **Step 3: Implement** — `Slider.schema.ts`

```ts
import { z } from "zod";
export const SliderProps = z.object({
  name:      z.string().default("slider"),
  label:     z.string().optional(),
  min:       z.number().default(0),
  max:       z.number().default(100),
  step:      z.number().default(1),
  range:     z.boolean().default(false),
  showValue: z.boolean().optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type SliderPropsType = z.infer<typeof SliderProps>;
```

`Slider.tsx`

```tsx
"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SliderPropsType } from "./Slider.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface SliderProps extends SliderPropsType {
  style?: StyleSlotT;
  value?: number | [number, number];
  onChange?: (value: number | [number, number]) => void;
}

export function Slider({ name, label, min = 0, max = 100, step = 1, range = false, showValue, style, value, onChange }: SliderProps) {
  const pair: [number, number] = Array.isArray(value) ? value : [typeof value === "number" ? value : min, typeof value === "number" ? value : max];
  const single = typeof value === "number" ? value : min;
  const base = "w-full accent-primary cursor-pointer";
  return (
    <div className="flex flex-col gap-1" data-slider="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label className="text-sm font-medium text-foreground">{label}{showValue && !range && <span className="ml-2 text-muted-foreground">{single}</span>}</label>}
      {range ? (
        <div className="flex flex-col gap-1">
          <input type="range" aria-label={`${label ?? name} minimum`} min={min} max={max} step={step} value={pair[0]} className={base}
            onChange={(e) => onChange?.([Number(e.target.value), pair[1]])} />
          <input type="range" aria-label={`${label ?? name} maximum`} min={min} max={max} step={step} value={pair[1]} className={base}
            onChange={(e) => onChange?.([pair[0], Number(e.target.value)])} />
        </div>
      ) : (
        <input type="range" name={name} aria-label={label ?? name} min={min} max={max} step={step} value={single} className={base}
          onChange={(e) => onChange?.(Number(e.target.value))} />
      )}
    </div>
  );
}
```

`index.ts` (+3 lines). `inputs.ts` (append):
```ts
export const SliderNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Slider"),
  props: z.object({
    name:      z.string().min(1),
    label:     z.string().optional(),
    min:       z.number().optional(),
    max:       z.number().optional(),
    step:      z.number().optional(),
    range:     z.boolean().optional(),
    showValue: z.boolean().optional(),
    bind:      z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type SliderNodeT = z.infer<typeof SliderNode>;
```
`page.ts`: import + union add `SliderNode`. `starter.ts`:
```ts
export const sliderEntry: RegistryEntry = {
  name: "Slider", category: "input", icon: "SlidersHorizontal",
  description: "Numeric slider (single value or range).",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "Value", control: "text",    group: "content",  description: "Slider label." },
    min:     { type: "number",  default: 0,       control: "number",  group: "behavior", description: "Minimum." },
    max:     { type: "number",  default: 100,     control: "number",  group: "behavior", description: "Maximum." },
    range:   { type: "boolean", default: false,   control: "toggle",  group: "behavior", description: "Two-thumb range mode." },
    binding: { type: "binding", default: null,    control: "binding", group: "data",     description: "Data path to bind the value." },
  },
};
```
plus `Slider: sliderEntry,`.

- [ ] **Step 4: Run — expect PASS**. **Step 5: Commit** `feat(library): add Slider component (fully wired, TDD)`.

---

## Task 5: FileUpload

- [ ] **Step 1: Failing test** — `packages/library/tests/components/FileUpload.test.tsx`

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileUpload } from "../../src/components/FileUpload/FileUpload";
import { FileUploadProps } from "../../src/components/FileUpload/FileUpload.schema";

describe("FileUpload", () => {
  it("renders a dropzone with the label/hint", () => {
    render(<FileUpload name="doc" label="Upload document" hint="PDF up to 5MB" />);
    expect(screen.getByText("Upload document")).toBeInTheDocument();
    expect(screen.getByText("PDF up to 5MB")).toBeInTheDocument();
  });
  it("emits selected files via onFiles", async () => {
    const onFiles = vi.fn();
    render(<FileUpload name="doc" label="Upload" onFiles={onFiles} />);
    const file = new File(["x"], "a.pdf", { type: "application/pdf" });
    const input = screen.getByTestId("file-upload-input") as HTMLInputElement;
    await userEvent.upload(input, file);
    expect(onFiles).toHaveBeenCalled();
    expect(onFiles.mock.calls[0][0][0].name).toBe("a.pdf");
  });
  it("validates props", () => {
    expect(() => FileUploadProps.parse({ name: "f", label: "F" })).not.toThrow();
    expect(() => FileUploadProps.parse({})).not.toThrow();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**.
- [ ] **Step 3: Implement** — `FileUpload.schema.ts`

```ts
import { z } from "zod";
export const FileUploadProps = z.object({
  name:      z.string().default("file"),
  label:     z.string().optional(),
  accept:    z.string().optional(),
  multiple:  z.boolean().optional(),
  maxSizeMb: z.number().optional(),
  hint:      z.string().optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type FileUploadPropsType = z.infer<typeof FileUploadProps>;
```

`FileUpload.tsx`

```tsx
"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { FileUploadPropsType } from "./FileUpload.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface FileUploadProps extends FileUploadPropsType {
  style?: StyleSlotT;
  onFiles?: (files: File[]) => void;
}

export function FileUpload({ name, label, accept, multiple, maxSizeMb, hint, style, onFiles }: FileUploadProps) {
  const [dragOver, setDragOver] = React.useState(false);
  const [files, setFiles] = React.useState<File[]>([]);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const accept_files = (list: FileList | null) => {
    if (!list) return;
    const arr = Array.from(list).filter((f) => maxSizeMb === undefined || f.size <= maxSizeMb * 1024 * 1024);
    setFiles(arr);
    onFiles?.(arr);
  };

  return (
    <div className="flex flex-col gap-1" data-file-upload="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label className="text-sm font-medium text-foreground">{label}</label>}
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); accept_files(e.dataTransfer.files); }}
        className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-md border-2 border-dashed px-4 py-6 text-center text-sm ${dragOver ? "border-primary bg-primary/5" : "border-input text-muted-foreground"}`}
      >
        <span>Drag &amp; drop or click to browse</span>
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
        <input
          ref={inputRef} data-testid="file-upload-input" type="file" name={name} accept={accept} multiple={multiple}
          className="hidden" onChange={(e) => accept_files(e.target.files)} />
      </div>
      {files.length > 0 && (
        <ul className="text-xs text-foreground">
          {files.map((f, i) => <li key={i}>{f.name} ({Math.round(f.size / 1024)} KB)</li>)}
        </ul>
      )}
    </div>
  );
}
```

`index.ts` (+3 lines). `inputs.ts` (append):
```ts
export const FileUploadNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("FileUpload"),
  props: z.object({
    name:      z.string().min(1),
    label:     z.string().optional(),
    accept:    z.string().optional(),
    multiple:  z.boolean().optional(),
    maxSizeMb: z.number().optional(),
    hint:      z.string().optional(),
    bind:      z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type FileUploadNodeT = z.infer<typeof FileUploadNode>;
```
`page.ts`: import + union add `FileUploadNode`. `starter.ts`:
```ts
export const fileUploadEntry: RegistryEntry = {
  name: "FileUpload", category: "input", icon: "Upload",
  description: "File upload dropzone (drag & drop + browse).",
  slots: { type: "leaf" },
  props: {
    label:    { type: "string",  default: "Upload file", control: "text",    group: "content",  description: "Field label." },
    accept:   { type: "string",  default: "",            control: "text",    group: "behavior", description: "Accepted MIME/extensions, e.g. image/*,.pdf." },
    multiple: { type: "boolean", default: false,         control: "toggle",  group: "behavior", description: "Allow multiple files." },
    binding:  { type: "binding", default: null,          control: "binding", group: "data",     description: "Data path to bind selected files." },
  },
};
```
plus `FileUpload: fileUploadEntry,`.

- [ ] **Step 4: Run — expect PASS**. **Step 5: Commit** `feat(library): add FileUpload component (fully wired, TDD)`.

---

## Task 6: Combobox

- [ ] **Step 1: Failing test** — `packages/library/tests/components/Combobox.test.tsx`

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Combobox } from "../../src/components/Combobox/Combobox";
import { ComboboxProps } from "../../src/components/Combobox/Combobox.schema";

const opts = [
  { value: "dxb", label: "Dubai" },
  { value: "auh", label: "Abu Dhabi" },
  { value: "shj", label: "Sharjah" },
];

describe("Combobox", () => {
  it("opens the option list on focus and shows all options", async () => {
    render(<Combobox name="city" label="City" options={opts} />);
    await userEvent.click(screen.getByRole("combobox"));
    expect(screen.getByText("Dubai")).toBeInTheDocument();
    expect(screen.getByText("Sharjah")).toBeInTheDocument();
  });
  it("filters options as you type", async () => {
    render(<Combobox name="city" label="City" options={opts} />);
    await userEvent.type(screen.getByRole("combobox"), "Abu");
    expect(screen.getByText("Abu Dhabi")).toBeInTheDocument();
    expect(screen.queryByText("Sharjah")).not.toBeInTheDocument();
  });
  it("selects an option and fires onChange with its value", async () => {
    const onChange = vi.fn();
    render(<Combobox name="city" label="City" options={opts} onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByText("Sharjah"));
    expect(onChange).toHaveBeenCalledWith("shj");
  });
  it("validates props", () => {
    expect(() => ComboboxProps.parse({ name: "c", options: opts })).not.toThrow();
    expect(() => ComboboxProps.parse({})).not.toThrow();
  });
});
```

- [ ] **Step 2: Run — expect FAIL**.
- [ ] **Step 3: Implement** — `Combobox.schema.ts`

```ts
import { z } from "zod";
const Option = z.object({ value: z.string(), label: z.string() });
export const ComboboxProps = z.object({
  name:        z.string().default("combobox"),
  label:       z.string().optional(),
  options:     z.array(Option).default([]),
  placeholder: z.string().optional(),
  filterable:  z.boolean().default(true),
  clearable:   z.boolean().optional(),
  bind:        z.string().optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type ComboboxPropsType = z.infer<typeof ComboboxProps>;
```

`Combobox.tsx`

```tsx
"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ComboboxPropsType } from "./Combobox.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface ComboboxProps extends ComboboxPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

export function Combobox({ name, label, options = [], placeholder, filterable = true, style, value, onChange }: ComboboxProps) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [active, setActive] = React.useState(0);
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const selectedLabel = options.find((o) => o.value === value)?.label ?? "";
  const filtered = filterable && query ? options.filter((o) => o.label.toLowerCase().includes(query.toLowerCase())) : options;
  const pick = (v: string) => { onChange?.(v); setOpen(false); setQuery(""); };

  return (
    <div className="relative flex flex-col gap-1" ref={ref} data-combobox="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label className="text-sm font-medium text-foreground">{label}</label>}
      <input
        role="combobox" aria-expanded={open} name={name} placeholder={placeholder ?? selectedLabel ?? "Select…"}
        value={open ? query : selectedLabel}
        onFocus={() => setOpen(true)}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, filtered.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          else if (e.key === "Enter" && filtered[active]) { e.preventDefault(); pick(filtered[active].value); }
          else if (e.key === "Escape") setOpen(false);
        }}
        className="rounded-md border border-input bg-transparent px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
      {open && (
        <ul role="listbox" className="absolute top-full z-10 mt-1 max-h-56 w-full overflow-auto rounded-md border border-input bg-white py-1 shadow-md">
          {filtered.length === 0 ? (
            <li className="px-3 py-1.5 text-sm text-muted-foreground">No matches</li>
          ) : filtered.map((o, i) => (
            <li key={o.value} role="option" aria-selected={value === o.value}
              onMouseDown={(e) => { e.preventDefault(); pick(o.value); }}
              onMouseEnter={() => setActive(i)}
              className={`cursor-pointer px-3 py-1.5 text-sm ${i === active ? "bg-muted" : ""} ${value === o.value ? "font-medium" : ""}`}>
              {o.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

`index.ts` (+3 lines). `inputs.ts` (append):
```ts
const ComboOption = z.object({ value: z.string().min(1), label: z.string().min(1) }).strict();
export const ComboboxNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Combobox"),
  props: z.object({
    name:        z.string().min(1),
    label:       z.string().optional(),
    options:     z.array(ComboOption).min(1),
    placeholder: z.string().optional(),
    filterable:  z.boolean().optional(),
    clearable:   z.boolean().optional(),
    bind:        z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type ComboboxNodeT = z.infer<typeof ComboboxNode>;
```
`page.ts`: import + union add `ComboboxNode`. `starter.ts`:
```ts
export const comboboxEntry: RegistryEntry = {
  name: "Combobox", category: "input", icon: "ChevronsUpDown",
  description: "Typeahead select with filterable suggestions.",
  slots: { type: "leaf" },
  props: {
    label:       { type: "string",  default: "Select", control: "text",    group: "content",  description: "Field label." },
    placeholder: { type: "string",  default: "Search…", control: "text",   group: "content",  description: "Placeholder text." },
    binding:     { type: "binding", default: null,     control: "binding", group: "data",     description: "Data path to bind the selected value." },
  },
};
```
plus `Combobox: comboboxEntry,`.

- [ ] **Step 4: Run — expect PASS**. **Step 5: Commit** `feat(library): add Combobox component (fully wired, TDD)`.

---

## Task 7: Form integration — `radio` + `switch` field kinds

**Files:** Modify `packages/library/src/components/Form/Form.tsx`; Test `packages/library/tests/components/form-fields-wave1.test.tsx`.

- [ ] **Step 1: Failing test**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Form } from "../../src/components/Form/Form";

describe("Form radio + switch field kinds", () => {
  it("collects radio and switch values into the workflow payload", async () => {
    const dispatch = vi.fn();
    render(
      <Form workflow="save" defaultValues={{ plan: "pro", active: false }}
        fields={[
          { kind: "radio", name: "plan", label: "Plan", options: [{ value: "free", label: "Free" }, { value: "pro", label: "Pro" }] },
          { kind: "switch", name: "active", label: "Active" },
        ]}
        __dispatch={dispatch} />
    );
    await userEvent.click(screen.getByRole("switch", { name: "Active" }));
    await userEvent.click(screen.getByRole("button", { name: /save|submit/i }));
    expect(dispatch).toHaveBeenCalledWith("save", { plan: "pro", active: true });
  });
});
```

- [ ] **Step 2: Run — expect FAIL** (radio/switch kinds unknown): `cd packages/library && ../../node_modules/.bin/vitest run tests/components/form-fields-wave1.test.tsx`

- [ ] **Step 3: Implement** — in `packages/library/src/components/Form/Form.tsx`:

(a) Extend the `Field` union (the `type Field = ...` block, lines 11-16) by adding:
```ts
  | { kind: "radio"; name: string; label: string; required?: boolean; options: { value: string; label: string }[] }
  | { kind: "switch"; name: string; label: string }
```

(b) Import the two components at the top of the file:
```ts
import { RadioGroup } from "../RadioGroup/RadioGroup";
import { Switch } from "../Switch/Switch";
```

(c) In `FormFieldImpl` add cases (uses react-hook-form's `Controller`; import `Controller` from `react-hook-form` and pass `control` into `FormFieldImpl` — `DeclarativeForm` already calls `useForm`; thread its `control` to `FormFieldImpl` the same way `register` is threaded). Add before the closing of the switch:
```tsx
    case "radio":
      return (
        <Controller name={field.name} control={control} render={({ field: f }) => (
          <RadioGroup name={field.name} label={field.label} options={field.options} value={f.value} onChange={f.onChange} />
        )} />
      );
    case "switch":
      return (
        <Controller name={field.name} control={control} render={({ field: f }) => (
          <Switch name={field.name} label={field.label} checked={!!f.value} onChange={f.onChange} />
        )} />
      );
```
Thread `control` from `DeclarativeForm` (which has `const { register, handleSubmit, control, formState } = useForm({ defaultValues })`) into the `<FormFieldImpl ... control={control} />` call and add `control` to `FormFieldImpl`'s props.

- [ ] **Step 4: Run — expect PASS**: `cd packages/library && ../../node_modules/.bin/vitest run tests/components/form-fields-wave1.test.tsx`
- [ ] **Step 5: Commit** `feat(library): Form radio + switch field kinds (TDD)`

---

## Task 8: Wave verification

**No new code** — prove the wave builds and the generator can see the 6.

- [ ] **Step 1: Build the three packages**
```bash
cd packages/schema   && ../../node_modules/.bin/tsc && cd ../registry && ../../node_modules/.bin/tsc && cd ../library && ../../node_modules/.bin/tsc
```
Expected: no NEW type errors in the new files (the repo has some pre-existing errors in unrelated components — only ensure the 6 new components + edited files are clean).

- [ ] **Step 2: Run the library + schema suites**
```bash
cd packages/library && ../../node_modules/.bin/vitest run
cd ../schema && ../../node_modules/.bin/vitest run
```
Expected: the 6 new component tests + Form test pass; no previously-passing test regresses (some pre-existing failures may exist — confirm they are unrelated by stashing if unsure).

- [ ] **Step 3: Assert the registry digest now lists all 6** (so the AI generator sees them)
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
node -e "const {registryDigest, starterRegistry} = require('./packages/registry/dist/registry/src/index.js'); const d = registryDigest(starterRegistry); for (const n of ['Switch','NumberInput','RadioGroup','Slider','FileUpload','Combobox']) { if (!d.includes(n)) { console.error('MISSING from digest:', n); process.exit(1);} } console.log('OK: all 6 in registry digest');"
```
Expected: `OK: all 6 in registry digest`. (If the dist path differs, build registry first and adjust the require path.)

- [ ] **Step 4: Commit any fixes** `git add -A && git commit -m "chore(wave1): build + verification fixes"`

---

## Self-Review (completed during authoring)

- **Spec coverage:** all 6 components (Tasks 1-6) with full recipe (component + library schema + node + page union + registry + index + tests); Form `radio`/`switch` kinds (Task 7); dependency-free (plain React, Combobox reuses inline-dropdown pattern); wave verification incl. registry digest (Task 8). All spec sections covered.
- **Placeholders:** none — every component/file has concrete code; the mechanical wiring lines (index 3-liners, page.ts import+union add, starterRegistry add) are given verbatim per component.
- **Type consistency:** each component uses `<Name>PropsType` from its `.schema.ts` extended by `<Name>Props` interface with `style?`, `value?/checked?`, `onChange?`; node types are `<Name>Node`; registry entries `<name>Entry` + `starterRegistry` key `<Name>`. Consistent across tasks. `resolveStyle`/`useMotion` import paths match `Checkbox.tsx`.
- **Known check:** Task 7 requires threading `control` from `useForm` into `FormFieldImpl` — the implementer must read the current `DeclarativeForm`/`FormFieldImpl` signatures and thread `control` exactly as `register` is threaded.
