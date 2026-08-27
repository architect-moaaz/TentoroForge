# Tier 2 Wave 3 — Component Batch 3: EmptyStateRich + DateRangePicker + MultiSelect

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Ship 3 small but load-bearing components that fill real gaps in the existing component vocabulary: rich empty-state for first-render UX, date-range picker for analytics pages, multi-value select for filter ergonomics.

**Architecture:** Each component follows the established Wave 1/2 pattern: zod node in `packages/schema/src/nodes/`, library component in `packages/library/src/components/<Name>/`, registry entry in scaffold, playground baseline, schema_prompt guidance. **Zero new deps** — DateRangePicker rolls its own calendar atop native `<input type="date">` for v1; can upgrade to react-day-picker later.

**Spec:** `docs/superpowers/specs/2026-05-08-enterprise-depth-design.md` § Theme A (components batch 3).

---

## File structure

### New files

- `packages/library/src/components/EmptyStateRich/EmptyStateRich.tsx`
- `packages/library/src/components/EmptyStateRich/EmptyStateRich.schema.ts`
- `packages/library/src/components/DateRangePicker/DateRangePicker.tsx`
- `packages/library/src/components/DateRangePicker/DateRangePicker.schema.ts`
- `packages/library/src/components/MultiSelect/MultiSelect.tsx`
- `packages/library/src/components/MultiSelect/MultiSelect.schema.ts`

### Modified files

- `packages/schema/src/nodes/enterprise.ts` — append 3 new nodes (EmptyStateRichNode, DateRangePickerNode, MultiSelectNode)
- `packages/schema/src/page.ts` — add 3 nodes to NodeV2 union
- `packages/library/src/index.ts` — export 3 new components + props schemas
- `apps/render-scaffold/.../SchemaRendererWrapper.tsx` — register 3 new components
- `frontend/src/app/(dev-only)/component-playground/page.tsx` — 3 new playground sections
- `apps/visual-regression/tests/components.spec.ts` — 3 new component IDs
- `backend/services/schema_prompt.py` — append component contracts

---

## Task 1: EmptyStateRich

**Files:**
- Create: `packages/library/src/components/EmptyStateRich/EmptyStateRich.tsx`
- Create: `packages/library/src/components/EmptyStateRich/EmptyStateRich.schema.ts`
- Modify: `packages/schema/src/nodes/enterprise.ts` — append `EmptyStateRichNode`
- Modify: `packages/library/src/index.ts` — export

- [ ] **Step 1: EmptyStateRichNode**

```ts
// Append to packages/schema/src/nodes/enterprise.ts
export const EmptyStateRichNode = z.object({
  id: z.string(),
  type: z.literal("EmptyStateRich"),
  props: z.object({
    icon: z.string().optional(),         // Lucide icon name (placeholder until Tier 3 illustrations)
    illustration: z.string().optional(), // future-use: URL to illustration asset
    heading: z.string().min(1),
    body: z.string().optional(),
    primaryCta: z.object({
      label: z.string(),
      action: z.discriminatedUnion("type", [
        z.object({ type: z.literal("navigate"), to: z.string() }),
        z.object({ type: z.literal("workflow"), workflow: z.string() }),
      ]),
    }).optional(),
    sampleDataLink: z.object({
      label: z.string(),
      action: z.object({ type: z.literal("workflow"), workflow: z.string() }),
    }).optional(),
  }),
});
```

- [ ] **Step 2: EmptyStateRich component**

```tsx
// packages/library/src/components/EmptyStateRich/EmptyStateRich.tsx
import * as React from "react";
import { z } from "zod";
import type { EmptyStateRichNode } from "@tentoroforge/schema";

type Props = z.infer<typeof EmptyStateRichNode>["props"];

export function EmptyStateRich({ icon, illustration, heading, body, primaryCta, sampleDataLink }: Props) {
  return (
    <div className="flex flex-col items-center justify-center text-center px-6 py-12 rounded-lg border border-dashed border-border bg-muted/20">
      {illustration ? (
        <img src={illustration} alt="" className="mb-4 h-32 w-32 object-contain opacity-80" aria-hidden="true" />
      ) : (
        <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
          <span className="text-3xl text-muted-foreground" data-icon={icon ?? "inbox"} aria-hidden="true">
            {icon === "calendar" ? "📅" :
             icon === "users" ? "👥" :
             icon === "file" ? "📄" :
             icon === "search" ? "🔍" :
             icon === "chart" ? "📊" :
             "📦"}
          </span>
        </div>
      )}
      <h3 className="text-lg font-semibold text-foreground mb-1">{heading}</h3>
      {body && (
        <p className="max-w-sm text-sm text-muted-foreground mb-5">{body}</p>
      )}
      {primaryCta && (
        <button
          type="button"
          className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          data-cta-action={primaryCta.action.type === "navigate"
            ? `navigate:${primaryCta.action.to}`
            : `workflow:${primaryCta.action.workflow}`}
        >
          {primaryCta.label}
        </button>
      )}
      {sampleDataLink && (
        <button
          type="button"
          className="mt-3 text-xs text-primary underline-offset-2 hover:underline"
          data-cta-action={`workflow:${sampleDataLink.action.workflow}`}
        >
          {sampleDataLink.label}
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Schema wrapper + library exports**

```ts
// packages/library/src/components/EmptyStateRich/EmptyStateRich.schema.ts
import { z } from "zod";
import { EmptyStateRichNode } from "@tentoroforge/schema";
export const EmptyStateRichProps = EmptyStateRichNode.shape.props;
export type EmptyStateRichPropsType = z.infer<typeof EmptyStateRichProps>;
```

In `packages/library/src/index.ts`:
```ts
export { EmptyStateRich } from "./components/EmptyStateRich/EmptyStateRich";
export { EmptyStateRichProps as EmptyStateRichPropsSchema, type EmptyStateRichPropsType } from "./components/EmptyStateRich/EmptyStateRich.schema";
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

git add packages/library/src/components/EmptyStateRich/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/enterprise.ts
git commit -m "feat(library): EmptyStateRich — illustrated empty-state with primary CTA + sample-data link"
```

---

## Task 2: DateRangePicker

**Files:**
- Create: `packages/library/src/components/DateRangePicker/DateRangePicker.tsx`
- Create: `packages/library/src/components/DateRangePicker/DateRangePicker.schema.ts`
- Modify: `packages/schema/src/nodes/enterprise.ts` — append `DateRangePickerNode`

- [ ] **Step 1: DateRangePickerNode**

```ts
// Append to packages/schema/src/nodes/enterprise.ts
export const DateRangePickerNode = z.object({
  id: z.string(),
  type: z.literal("DateRangePicker"),
  props: z.object({
    name: z.string(),                    // form field name; URL key when standalone
    label: z.string().optional(),
    startDate: z.string().optional(),    // ISO date YYYY-MM-DD
    endDate: z.string().optional(),
    presets: z.array(z.enum([
      "today", "yesterday", "last-7-days", "last-30-days",
      "quarter-to-date", "year-to-date", "custom",
    ])).optional(),
    minDate: z.string().optional(),
    maxDate: z.string().optional(),
  }),
});
```

- [ ] **Step 2: DateRangePicker component**

```tsx
// packages/library/src/components/DateRangePicker/DateRangePicker.tsx
"use client";

import * as React from "react";
import { z } from "zod";
import type { DateRangePickerNode } from "@tentoroforge/schema";
import { useUrlState } from "../../style/useUrlState";

type Props = z.infer<typeof DateRangePickerNode>["props"];

const PRESET_LABELS: Record<string, string> = {
  "today":             "Today",
  "yesterday":         "Yesterday",
  "last-7-days":       "Last 7 days",
  "last-30-days":      "Last 30 days",
  "quarter-to-date":   "Quarter to date",
  "year-to-date":      "Year to date",
  "custom":            "Custom range",
};

const DEFAULT_PRESETS: NonNullable<Props["presets"]> = [
  "last-7-days", "last-30-days", "quarter-to-date", "year-to-date", "custom",
];

function formatDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function presetToRange(preset: string): { start: string; end: string } | null {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  switch (preset) {
    case "today":
      return { start: formatDate(today), end: formatDate(today) };
    case "yesterday":
      return { start: formatDate(yesterday), end: formatDate(yesterday) };
    case "last-7-days": {
      const start = new Date(today);
      start.setDate(today.getDate() - 6);
      return { start: formatDate(start), end: formatDate(today) };
    }
    case "last-30-days": {
      const start = new Date(today);
      start.setDate(today.getDate() - 29);
      return { start: formatDate(start), end: formatDate(today) };
    }
    case "quarter-to-date": {
      const q = Math.floor(today.getMonth() / 3);
      const start = new Date(today.getFullYear(), q * 3, 1);
      return { start: formatDate(start), end: formatDate(today) };
    }
    case "year-to-date": {
      const start = new Date(today.getFullYear(), 0, 1);
      return { start: formatDate(start), end: formatDate(today) };
    }
    default:
      return null;
  }
}

export function DateRangePicker({
  name, label, startDate, endDate, presets = DEFAULT_PRESETS, minDate, maxDate,
}: Props) {
  const [start, setStart] = useUrlState(`${name}_start`, startDate ?? "");
  const [end, setEnd] = useUrlState(`${name}_end`, endDate ?? "");
  const [open, setOpen] = React.useState(false);
  const [activePreset, setActivePreset] = React.useState<string>("custom");

  const display = React.useMemo(() => {
    if (!start && !end) return "Any date";
    if (start === end && start) return start;
    if (start && end) return `${start} → ${end}`;
    if (start) return `From ${start}`;
    return `Until ${end}`;
  }, [start, end]);

  function applyPreset(preset: string) {
    setActivePreset(preset);
    if (preset === "custom") return;  // keep dropdown open for manual date input
    const range = presetToRange(preset);
    if (range) {
      setStart(range.start);
      setEnd(range.end);
      setOpen(false);
    }
  }

  function clear() {
    setStart("");
    setEnd("");
    setActivePreset("custom");
    setOpen(false);
  }

  return (
    <div className="relative inline-block">
      {label && (
        <label className="mr-2 text-xs font-medium text-muted-foreground">{label}:</label>
      )}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-card px-2.5 text-xs font-medium hover:bg-muted/50"
      >
        <span>{display}</span>
        <span className="opacity-60">▾</span>
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 w-72 rounded-md border border-border bg-popover p-3 shadow-md z-10">
          <ul className="mb-3 space-y-1">
            {presets.map((p) => (
              <li key={p}>
                <button
                  type="button"
                  onClick={() => applyPreset(p)}
                  className={`block w-full rounded px-2 py-1 text-left text-xs hover:bg-muted ${activePreset === p ? "bg-muted font-semibold" : ""}`}
                >
                  {PRESET_LABELS[p] ?? p}
                </button>
              </li>
            ))}
          </ul>
          {activePreset === "custom" && (
            <div className="space-y-2 border-t border-border pt-3">
              <div>
                <label className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">From</label>
                <input
                  type="date"
                  value={start}
                  min={minDate}
                  max={maxDate}
                  onChange={(e) => setStart(e.target.value)}
                  className="h-8 w-full rounded border border-border bg-background px-2 text-xs"
                />
              </div>
              <div>
                <label className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">To</label>
                <input
                  type="date"
                  value={end}
                  min={start || minDate}
                  max={maxDate}
                  onChange={(e) => setEnd(e.target.value)}
                  className="h-8 w-full rounded border border-border bg-background px-2 text-xs"
                />
              </div>
            </div>
          )}
          <div className="mt-3 flex justify-between border-t border-border pt-2">
            <button
              type="button"
              onClick={clear}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Schema wrapper + library exports**

```ts
// DateRangePicker.schema.ts
import { z } from "zod";
import { DateRangePickerNode } from "@tentoroforge/schema";
export const DateRangePickerProps = DateRangePickerNode.shape.props;
export type DateRangePickerPropsType = z.infer<typeof DateRangePickerProps>;
```

In `packages/library/src/index.ts`:
```ts
export { DateRangePicker } from "./components/DateRangePicker/DateRangePicker";
export { DateRangePickerProps as DateRangePickerPropsSchema, type DateRangePickerPropsType } from "./components/DateRangePicker/DateRangePicker.schema";
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

git add packages/library/src/components/DateRangePicker/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/enterprise.ts
git commit -m "feat(library): DateRangePicker — preset list + native date inputs + URL state"
```

---

## Task 3: MultiSelect

**Files:**
- Create: `packages/library/src/components/MultiSelect/MultiSelect.tsx`
- Create: `packages/library/src/components/MultiSelect/MultiSelect.schema.ts`
- Modify: `packages/schema/src/nodes/enterprise.ts` — append `MultiSelectNode`

- [ ] **Step 1: MultiSelectNode**

```ts
// Append to packages/schema/src/nodes/enterprise.ts
export const MultiSelectNode = z.object({
  id: z.string(),
  type: z.literal("MultiSelect"),
  props: z.object({
    name: z.string(),                    // URL key / form field
    label: z.string().optional(),
    placeholder: z.string().optional(),
    options: z.array(z.object({
      value: z.string(),
      label: z.string(),
    })).min(1),
    selected: z.array(z.string()).optional(),  // initial value
    showSearch: z.boolean().optional(),  // auto when options.length > 8
    maxSelectionLabel: z.number().optional(),  // show "N selected" instead of chips when count > this
  }),
});
```

- [ ] **Step 2: MultiSelect component**

```tsx
// packages/library/src/components/MultiSelect/MultiSelect.tsx
"use client";

import * as React from "react";
import { z } from "zod";
import type { MultiSelectNode } from "@tentoroforge/schema";
import { useUrlState } from "../../style/useUrlState";

type Props = z.infer<typeof MultiSelectNode>["props"];

export function MultiSelect({
  name, label, placeholder = "Select…", options, selected,
  showSearch, maxSelectionLabel = 3,
}: Props) {
  const initialCsv = (selected ?? []).join(",");
  const [valueCsv, setValueCsv] = useUrlState(name, initialCsv);
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");

  const selectedSet = React.useMemo(() => new Set(valueCsv ? valueCsv.split(",") : []), [valueCsv]);

  const visibleOptions = React.useMemo(() => {
    if (!search.trim()) return options;
    const q = search.toLowerCase();
    return options.filter((o) =>
      o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q),
    );
  }, [options, search]);

  function toggle(val: string) {
    const next = new Set(selectedSet);
    if (next.has(val)) next.delete(val);
    else next.add(val);
    setValueCsv(Array.from(next).join(","));
  }

  function clear() {
    setValueCsv("");
  }

  const showSearchBox = showSearch ?? options.length > 8;

  const triggerLabel = (() => {
    if (selectedSet.size === 0) return placeholder;
    if (selectedSet.size > maxSelectionLabel) return `${selectedSet.size} selected`;
    return options
      .filter((o) => selectedSet.has(o.value))
      .map((o) => o.label)
      .join(", ");
  })();

  return (
    <div className="relative inline-block">
      {label && <label className="mr-2 text-xs font-medium text-muted-foreground">{label}:</label>}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 min-w-[140px] items-center justify-between gap-1.5 rounded-md border border-border bg-card px-2.5 text-xs font-medium hover:bg-muted/50"
      >
        <span className={selectedSet.size === 0 ? "text-muted-foreground" : ""}>{triggerLabel}</span>
        <span className="opacity-60">▾</span>
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 min-w-[240px] rounded-md border border-border bg-popover shadow-md z-10">
          {showSearchBox && (
            <div className="border-b border-border p-2">
              <input
                type="text"
                placeholder="Search…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-7 w-full rounded border border-border bg-background px-2 text-xs"
                autoFocus
              />
            </div>
          )}
          <ul className="max-h-64 overflow-y-auto py-1">
            {visibleOptions.length === 0 && (
              <li className="px-3 py-2 text-xs text-muted-foreground">No options match.</li>
            )}
            {visibleOptions.map((opt) => {
              const checked = selectedSet.has(opt.value);
              return (
                <li key={opt.value}>
                  <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-xs hover:bg-muted">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(opt.value)}
                      className="h-3.5 w-3.5 rounded border-border"
                    />
                    <span className={checked ? "font-medium text-foreground" : "text-muted-foreground"}>
                      {opt.label}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
          <div className="flex items-center justify-between border-t border-border p-2">
            <button
              type="button"
              onClick={clear}
              disabled={selectedSet.size === 0}
              className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              Clear ({selectedSet.size})
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Schema wrapper + library exports**

```ts
// MultiSelect.schema.ts
import { z } from "zod";
import { MultiSelectNode } from "@tentoroforge/schema";
export const MultiSelectProps = MultiSelectNode.shape.props;
export type MultiSelectPropsType = z.infer<typeof MultiSelectProps>;
```

In `packages/library/src/index.ts`:
```ts
export { MultiSelect } from "./components/MultiSelect/MultiSelect";
export { MultiSelectProps as MultiSelectPropsSchema, type MultiSelectPropsType } from "./components/MultiSelect/MultiSelect.schema";
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

git add packages/library/src/components/MultiSelect/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/enterprise.ts
git commit -m "feat(library): MultiSelect — checkbox-list dropdown with search + URL state (CSV)"
```

---

## Task 4: NodeV2 union + render-scaffold registry

**Files:**
- Modify: `packages/schema/src/page.ts` — add 3 new nodes to NodeV2
- Modify: `apps/render-scaffold/src/app/p/[projectId]/[...slug]/SchemaRendererWrapper.tsx` — register

### Step 1: NodeV2 union

In `packages/schema/src/page.ts`, find the import block + discriminated union:

```ts
import {
  ApprovalStepperNode, PersonCardNode, FilterBarNode,
  CommandPaletteNode, ActivityFeedNode,
  EmptyStateRichNode, DateRangePickerNode, MultiSelectNode,  // ← add these 3
} from "./nodes/enterprise";

// Add to discriminatedUnion array:
EmptyStateRichNode,
DateRangePickerNode,
MultiSelectNode,
```

### Step 2: Scaffold registry

In `SchemaRendererWrapper.tsx`, follow the pattern from W2 Task 6:

```tsx
import {
  EmptyStateRich, DateRangePicker, MultiSelect,
  EmptyStateRichPropsSchema, DateRangePickerPropsSchema, MultiSelectPropsSchema,
} from "@tentoroforge/library";

reg("EmptyStateRich",   EmptyStateRich,   EmptyStateRichPropsSchema,   "feedback");
reg("DateRangePicker",  DateRangePicker,  DateRangePickerPropsSchema,  "form");
reg("MultiSelect",      MultiSelect,      MultiSelectPropsSchema,      "form");
```

### Step 3: Build packages

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema && npm run build 2>&1 | tail -3
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npm run build 2>&1 | tail -3
```

### Step 4: Scaffold boot test

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
lsof -ti:6503 | xargs kill -9 2>/dev/null || true
cd apps/render-scaffold && npm run dev > /tmp/scaffold-t2w3.log 2>&1 &
sleep 10
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:6503/
lsof -ti:6503 | xargs kill -9 2>/dev/null || true
```

Expected: 200.

### Step 5: Commit

```bash
git add packages/schema/src/page.ts \
        apps/render-scaffold/src/app/p/\[projectId\]/\[...slug\]/SchemaRendererWrapper.tsx
git commit -m "feat(scaffold): register EmptyStateRich/DateRangePicker/MultiSelect in NodeV2 + render registry"
```

---

## Task 5: Playground entries + visual regression baselines

**Files:**
- Modify: `frontend/src/app/(dev-only)/component-playground/page.tsx`
- Modify: `apps/visual-regression/tests/components.spec.ts`

### Step 1: Add 3 playground sections

In the inner client component (PlaygroundInner), append:

```tsx
import { EmptyStateRich, DateRangePicker, MultiSelect } from "@tentoroforge/library";

// Section: EmptyStateRich
<section data-component="EmptyStateRich" className={SECTION}>
  <p className={TITLE}>EmptyStateRich</p>
  <div className="max-w-lg">
    <EmptyStateRich
      icon="calendar"
      heading="No leave requests yet"
      body="Submit your first PTO request to see it tracked here, including approval status and remaining balance."
      primaryCta={{ label: "Submit a Request", action: { type: "navigate", to: "/leave-requests/new" }}}
      sampleDataLink={{ label: "Try with sample data", action: { type: "workflow", workflow: "SeedSampleLeaveData" }}}
    />
  </div>
</section>

// Section: DateRangePicker
<section data-component="DateRangePicker" className={SECTION}>
  <p className={TITLE}>DateRangePicker</p>
  <DateRangePicker name="reportRange" label="Date range" />
</section>

// Section: MultiSelect
<section data-component="MultiSelect" className={SECTION}>
  <p className={TITLE}>MultiSelect</p>
  <MultiSelect
    name="depts"
    label="Departments"
    placeholder="All departments"
    options={[
      { value: "eng", label: "Engineering" },
      { value: "design", label: "Design" },
      { value: "sales", label: "Sales" },
      { value: "ops", label: "Operations" },
      { value: "hr", label: "HR" },
    ]}
  />
</section>
```

### Step 2: Add to visual regression spec

In `apps/visual-regression/tests/components.spec.ts`, append to COMPONENTS array:
```ts
"EmptyStateRich", "DateRangePicker", "MultiSelect",
```

### Step 3: Capture baselines

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
npm run dev -- -p 6501 > /tmp/frontend-t2w3-baseline.log 2>&1 &
sleep 15
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test --grep "EmptyStateRich|DateRangePicker|MultiSelect" --update-snapshots
npx playwright test --grep "EmptyStateRich|DateRangePicker|MultiSelect"
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: 3 new tests pass.

### Step 4: Commit

```bash
git add frontend/src/app/\(dev-only\)/component-playground/ \
        apps/visual-regression/tests/
git commit -m "feat(playground): add EmptyStateRich/DateRangePicker/MultiSelect + baselines"
```

---

## Task 6: schema_prompt teaches new components + final verify

Append to `backend/services/schema_prompt.py` (after the existing TIER2_BATCH2_GUIDANCE block):

```python
TIER2_BATCH3_GUIDANCE = """
## TIER 2 COMPONENTS BATCH 3 (filter ergonomics + first-render UX)

  EmptyStateRich { icon?, illustration?, heading, body?, primaryCta?,
                   sampleDataLink? }
    Replaces basic EmptyState for first-render contexts. Heading + body copy
    + primary CTA + optional "try with sample data" link. Wrap every
    DataGrid / Table / list-page-content in a `rows.length === 0 ?
    <EmptyStateRich/> : <DataGrid/>` guard.

  DateRangePicker { name, label?, startDate?, endDate?, presets?,
                    minDate?, maxDate? }
    Calendar popover with preset list (today / yesterday / last-7-days /
    last-30-days / quarter-to-date / year-to-date / custom). URL-persisted
    via {name}_start + {name}_end keys. Use on report / analytics / audit
    pages where time-range filtering is the primary axis. Combine with
    FilterBar for status/department filters.

  MultiSelect { name, label?, placeholder?, options[], selected?,
                showSearch?, maxSelectionLabel? }
    Checkbox-list dropdown for multi-value filters. Auto-shows search when
    options > 8. Same prop shape as Select; use INSTEAD OF Select when
    multiple values can be selected (e.g. "show employees in [Eng, Design,
    Sales]"). URL state is comma-separated CSV.

ANTI-PATTERNS:
  - Plain "No data" text under a DataGrid → use EmptyStateRich
  - Two separate <Input type="date"> for date filtering → use DateRangePicker
  - Three separate Select chips for the same filter axis → use MultiSelect
  - DateRangePicker WITHOUT a list/chart it filters → noise, no purpose
"""
```

### Step 1: Verify schema_prompt tests

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_schema_prompt.py -v 2>&1 | tail -10
```

Expected: existing tests still pass.

### Step 2: Final verification

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/integration/test_schema_migration.py tests/services/test_schema_prompt.py -v 2>&1 | tail -10

cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema && npm run build 2>&1 | tail -3
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npm run build 2>&1 | tail -3
```

### Step 3: Commit

```bash
git add backend/services/schema_prompt.py
git commit -m "feat(schema-prompt): teach Tier 2 batch 3 components + anti-patterns"
```

---

## Self-review

### Spec coverage

| Component | Tasks |
|---|---|
| EmptyStateRich | 1 |
| DateRangePicker | 2 |
| MultiSelect | 3 |
| NodeV2 + scaffold registry | 4 |
| Playground + baselines | 5 |
| schema_prompt + verify | 6 |

✓ All Wave 3 scope covered.

### Type consistency

- 3 new nodes in `packages/schema/src/nodes/enterprise.ts`
- Each library component re-exports `<Name>Props as <Name>PropsSchema` (matches Wave 1/2 pattern)
- All 3 in NodeV2 discriminated union
- DateRangePicker + MultiSelect use the existing `useUrlState` hook from Wave 2 — consistent state management

✓ Consistent.

---

## Out of scope (deferred)

- **Branded illustrations** for EmptyStateRich — Tier 3 Wave 5 (uses emoji placeholders for now)
- **react-day-picker calendar** for DateRangePicker — v1 uses native `<input type="date">` per browser; upgrade later if cross-browser inconsistencies bite
- **Async option loading** for MultiSelect (server-side) — needs data engine extensions from Wave 5
- **Combobox / autocomplete** for MultiSelect — separate component, not blocking
