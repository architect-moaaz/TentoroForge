# Tier 2 Wave 2 — Component Batch 2: ApprovalStepper + PersonCard + FilterBar + CommandPalette + ActivityFeed

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Add 5 enterprise-pattern components: ApprovalStepper (multi-stage approval flow visualisation), PersonCard (employee/user-card composite), FilterBar (URL-persisted filter management), CommandPalette (Cmd-K power-user modal), ActivityFeed (project-wide audit-trail sidebar). After this wave, the LLM can compose Workday-grade approval flows + employee directories + power-user navigation patterns.

**Architecture:** Each component follows the Tier 2 Wave 1 pattern: zod node in `packages/schema/src/nodes/`, library component in `packages/library/src/components/<Name>/`, registry entry in scaffold, playground baseline, schema_prompt guidance. New dep: `cmdk` for CommandPalette (small, MIT, well-maintained). FilterBar adds a `useUrlState` hook that other components (DataGrid future versions) will reuse.

**Tech Stack:** TypeScript / React 19 / Tailwind / CVA / Zod (existing). New dep: `cmdk` (~10KB gzipped).

**Spec:** `docs/superpowers/specs/2026-05-08-enterprise-depth-design.md` § Theme A (components batch 2).

---

## File structure

### New files

**ApprovalStepper:**
- `packages/library/src/components/ApprovalStepper/ApprovalStepper.tsx`
- `packages/library/src/components/ApprovalStepper/ApprovalStepper.schema.ts`

**PersonCard:**
- `packages/library/src/components/PersonCard/PersonCard.tsx`
- `packages/library/src/components/PersonCard/PersonCard.schema.ts`

**FilterBar + URL state hook:**
- `packages/library/src/components/FilterBar/FilterBar.tsx`
- `packages/library/src/components/FilterBar/FilterBar.schema.ts`
- `packages/library/src/style/useUrlState.ts` — generic URL-state hook

**CommandPalette:**
- `packages/library/src/components/CommandPalette/CommandPalette.tsx`
- `packages/library/src/components/CommandPalette/CommandPalette.schema.ts`

**ActivityFeed:**
- `packages/library/src/components/ActivityFeed/ActivityFeed.tsx`
- `packages/library/src/components/ActivityFeed/ActivityFeed.schema.ts`

**Schema package:**
- `packages/schema/src/nodes/enterprise.ts` — single file with all 5 new nodes (ApprovalStepperNode, PersonCardNode, FilterBarNode, CommandPaletteNode, ActivityFeedNode)

### Modified files

- `packages/library/package.json` — add `cmdk` dep
- `packages/library/src/index.ts` — export 5 new components + props schemas + useUrlState
- `packages/schema/src/index.ts` — re-export enterprise nodes
- `packages/schema/src/page.ts` — add 5 nodes to NodeV2 discriminated union
- `apps/render-scaffold/src/app/p/[projectId]/[...slug]/SchemaRendererWrapper.tsx` (or wherever the registry is built) — register 5 new components
- `frontend/src/app/(dev-only)/component-playground/page.tsx` — 5 new playground sections
- `apps/visual-regression/tests/components.spec.ts` — add 5 new component IDs
- `backend/services/schema_prompt.py` — append component contracts for the 5 new components

---

## Task 1: ApprovalStepper

**Files:**
- Create: `packages/library/src/components/ApprovalStepper/ApprovalStepper.tsx`
- Create: `packages/library/src/components/ApprovalStepper/ApprovalStepper.schema.ts`
- Create: `packages/schema/src/nodes/enterprise.ts` (initial — ApprovalStepper only)

- [ ] **Step 1: ApprovalStepperNode zod schema**

```ts
// packages/schema/src/nodes/enterprise.ts (initial)
import { z } from "zod";

const StepperStep = z.object({
  id: z.string(),
  label: z.string(),
  status: z.enum(["pending", "current", "approved", "rejected", "skipped"]),
  actor: z.string().optional(),
  timestamp: z.string().optional(),  // ISO 8601
});

export const ApprovalStepperNode = z.object({
  id: z.string(),
  type: z.literal("ApprovalStepper"),
  props: z.object({
    steps: z.array(StepperStep).min(1),
    orientation: z.enum(["horizontal", "vertical"]).optional(),  // default horizontal
    onStepClick: z.string().optional(),  // workflow ID to trigger on click; usually omitted
  }),
});
```

- [ ] **Step 2: ApprovalStepper component**

```tsx
// packages/library/src/components/ApprovalStepper/ApprovalStepper.tsx
import * as React from "react";
import { z } from "zod";
import type { ApprovalStepperNode } from "@tentoroforge/schema";

type Props = z.infer<typeof ApprovalStepperNode>["props"];

const STATUS_DOT: Record<string, string> = {
  pending:  "bg-muted text-muted-foreground border border-border",
  current:  "bg-primary text-primary-foreground border-2 border-primary ring-2 ring-primary/20",
  approved: "bg-emerald-600 text-white",
  rejected: "bg-rose-600 text-white",
  skipped:  "bg-muted text-muted-foreground/60 border border-dashed border-border",
};

const STATUS_GLYPH: Record<string, string> = {
  pending:  "",
  current:  "●",
  approved: "✓",
  rejected: "✕",
  skipped:  "—",
};

const STATUS_CONNECTOR: Record<string, string> = {
  pending: "bg-border",
  current: "bg-primary/30",
  approved: "bg-emerald-600",
  rejected: "bg-rose-600",
  skipped: "bg-border opacity-50",
};

export function ApprovalStepper({ steps, orientation = "horizontal" }: Props) {
  if (orientation === "vertical") {
    return (
      <ol className="space-y-4">
        {steps.map((step, idx) => (
          <li key={step.id} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${STATUS_DOT[step.status]}`}>
                {STATUS_GLYPH[step.status] || (idx + 1)}
              </div>
              {idx < steps.length - 1 && (
                <div className={`flex-1 w-0.5 mt-1 ${STATUS_CONNECTOR[steps[idx + 1]?.status === "pending" ? "pending" : step.status]}`} style={{ minHeight: 24 }} />
              )}
            </div>
            <div className="flex-1 pb-2">
              <p className="text-sm font-medium leading-tight">{step.label}</p>
              {step.actor && <p className="text-xs text-muted-foreground mt-0.5">{step.actor}</p>}
              {step.timestamp && (
                <p className="text-[11px] text-muted-foreground/80 mt-0.5">
                  {new Date(step.timestamp).toLocaleString()}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
    );
  }
  return (
    <ol className="flex items-start w-full">
      {steps.map((step, idx) => (
        <li key={step.id} className="flex flex-1 flex-col items-center relative">
          <div className="flex items-center w-full">
            <div className={`flex-1 h-0.5 ${idx === 0 ? "invisible" : STATUS_CONNECTOR[step.status]}`} />
            <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${STATUS_DOT[step.status]}`}>
              {STATUS_GLYPH[step.status] || (idx + 1)}
            </div>
            <div className={`flex-1 h-0.5 ${idx === steps.length - 1 ? "invisible" : STATUS_CONNECTOR[steps[idx + 1]?.status === "pending" ? "pending" : step.status]}`} />
          </div>
          <div className="text-center mt-2 px-1 max-w-[140px]">
            <p className="text-xs font-medium leading-tight">{step.label}</p>
            {step.actor && <p className="text-[11px] text-muted-foreground mt-0.5 truncate">{step.actor}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}
```

- [ ] **Step 3: Schema wrapper + library index**

```ts
// ApprovalStepper.schema.ts
import { z } from "zod";
import { ApprovalStepperNode } from "@tentoroforge/schema";
export const ApprovalStepperProps = ApprovalStepperNode.shape.props;
export type ApprovalStepperPropsType = z.infer<typeof ApprovalStepperProps>;
```

In `packages/schema/src/index.ts` add:
```ts
export * from "./nodes/enterprise";
```

In `packages/library/src/index.ts` add:
```ts
export { ApprovalStepper } from "./components/ApprovalStepper/ApprovalStepper";
export { ApprovalStepperProps as ApprovalStepperPropsSchema, type ApprovalStepperPropsType } from "./components/ApprovalStepper/ApprovalStepper.schema";
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

git add packages/library/src/components/ApprovalStepper/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/enterprise.ts \
        packages/schema/src/index.ts
git commit -m "feat(library): ApprovalStepper — multi-stage approval flow visualisation"
```

---

## Task 2: PersonCard

**Files:**
- Create: `packages/library/src/components/PersonCard/PersonCard.tsx`
- Create: `packages/library/src/components/PersonCard/PersonCard.schema.ts`
- Modify: `packages/schema/src/nodes/enterprise.ts` — append PersonCardNode

- [ ] **Step 1: PersonCardNode**

Append to `packages/schema/src/nodes/enterprise.ts`:

```ts
export const PersonCardNode = z.object({
  id: z.string(),
  type: z.literal("PersonCard"),
  props: z.object({
    name: z.string().min(1),
    role: z.string().optional(),
    department: z.string().optional(),
    avatarUrl: z.string().optional(),
    avatarInitials: z.string().optional(),  // fallback if no avatarUrl
    email: z.string().optional(),
    status: z.enum(["active", "away", "on-leave", "offline"]).optional(),
    manager: z.object({
      name: z.string(),
      role: z.string().optional(),
    }).optional(),
    layout: z.enum(["compact", "expanded"]).optional(),  // default compact
  }),
});
```

- [ ] **Step 2: PersonCard component**

```tsx
// packages/library/src/components/PersonCard/PersonCard.tsx
import * as React from "react";
import { z } from "zod";
import type { PersonCardNode } from "@tentoroforge/schema";

type Props = z.infer<typeof PersonCardNode>["props"];

const STATUS_DOT: Record<string, string> = {
  active:    "bg-emerald-500",
  away:      "bg-amber-500",
  "on-leave": "bg-rose-500",
  offline:   "bg-muted-foreground",
};

const STATUS_LABEL: Record<string, string> = {
  active: "Active",
  away: "Away",
  "on-leave": "On leave",
  offline: "Offline",
};

function getInitials(name: string, fallback?: string): string {
  if (fallback) return fallback;
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function PersonCard({ name, role, department, avatarUrl, avatarInitials, email, status, manager, layout = "compact" }: Props) {
  const initials = getInitials(name, avatarInitials);
  const expanded = layout === "expanded";

  return (
    <div className={`flex ${expanded ? "flex-col gap-3 rounded-lg border border-border bg-card p-4" : "flex-row items-center gap-3"}`}>
      <div className={`relative flex shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary font-semibold ${expanded ? "h-16 w-16 text-xl" : "h-10 w-10 text-sm"}`}>
        {avatarUrl ? (
          <img src={avatarUrl} alt={name} className="h-full w-full rounded-full object-cover" />
        ) : (
          <span>{initials}</span>
        )}
        {status && (
          <span
            className={`absolute bottom-0 right-0 ${expanded ? "h-4 w-4" : "h-2.5 w-2.5"} rounded-full ring-2 ring-card ${STATUS_DOT[status]}`}
            aria-label={STATUS_LABEL[status]}
          />
        )}
      </div>
      <div className={`min-w-0 flex-1 ${expanded ? "text-center" : ""}`}>
        <p className="font-medium text-sm leading-tight truncate">{name}</p>
        {role && <p className="text-xs text-muted-foreground truncate">{role}</p>}
        {expanded && department && <p className="text-xs text-muted-foreground mt-0.5">{department}</p>}
        {expanded && email && <p className="text-xs text-muted-foreground mt-1 truncate">{email}</p>}
        {expanded && manager && (
          <div className="mt-3 pt-3 border-t border-border w-full">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">Reports to</p>
            <p className="text-xs font-medium">{manager.name}</p>
            {manager.role && <p className="text-[11px] text-muted-foreground">{manager.role}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Schema wrapper + library exports**

```ts
// PersonCard.schema.ts
import { z } from "zod";
import { PersonCardNode } from "@tentoroforge/schema";
export const PersonCardProps = PersonCardNode.shape.props;
export type PersonCardPropsType = z.infer<typeof PersonCardProps>;
```

In `packages/library/src/index.ts`:
```ts
export { PersonCard } from "./components/PersonCard/PersonCard";
export { PersonCardProps as PersonCardPropsSchema, type PersonCardPropsType } from "./components/PersonCard/PersonCard.schema";
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

git add packages/library/src/components/PersonCard/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/enterprise.ts
git commit -m "feat(library): PersonCard — avatar + name + role + manager + status composite"
```

---

## Task 3: FilterBar + useUrlState hook

**Files:**
- Create: `packages/library/src/style/useUrlState.ts` — generic URL-state hook
- Create: `packages/library/src/components/FilterBar/FilterBar.tsx`
- Create: `packages/library/src/components/FilterBar/FilterBar.schema.ts`
- Modify: `packages/schema/src/nodes/enterprise.ts` — append FilterBarNode

- [ ] **Step 1: useUrlState hook**

```ts
// packages/library/src/style/useUrlState.ts
import * as React from "react";

/**
 * Generic URL-state hook. Reads + writes a single key in the URL's search
 * params. Falls back gracefully outside browser environments (SSR — no-op).
 *
 * Usage:
 *   const [filter, setFilter] = useUrlState("filter", "active");
 *
 * The default value is used when the URL doesn't yet have the key. Setting
 * to the default removes the key from the URL (clean URLs).
 */
export function useUrlState(key: string, defaultValue: string = ""): [string, (next: string) => void] {
  const isClient = typeof window !== "undefined";
  const [value, setValue] = React.useState<string>(() => {
    if (!isClient) return defaultValue;
    const params = new URLSearchParams(window.location.search);
    return params.get(key) ?? defaultValue;
  });

  React.useEffect(() => {
    if (!isClient) return;
    const onPop = () => {
      const params = new URLSearchParams(window.location.search);
      setValue(params.get(key) ?? defaultValue);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [key, defaultValue, isClient]);

  const update = React.useCallback((next: string) => {
    setValue(next);
    if (!isClient) return;
    const params = new URLSearchParams(window.location.search);
    if (next === defaultValue || next === "") {
      params.delete(key);
    } else {
      params.set(key, next);
    }
    const newUrl = `${window.location.pathname}${params.toString() ? "?" + params.toString() : ""}${window.location.hash}`;
    window.history.replaceState({}, "", newUrl);
  }, [key, defaultValue, isClient]);

  return [value, update];
}
```

- [ ] **Step 2: FilterBarNode**

Append to `packages/schema/src/nodes/enterprise.ts`:

```ts
const FilterChip = z.object({
  key: z.string(),       // URL param key
  label: z.string(),     // Visible label
  options: z.array(z.object({
    value: z.string(),
    label: z.string(),
  })).min(1),
  defaultValue: z.string().optional(),
});

const SavedView = z.object({
  id: z.string(),
  label: z.string(),
  filters: z.record(z.string()),  // key → value
});

export const FilterBarNode = z.object({
  id: z.string(),
  type: z.literal("FilterBar"),
  props: z.object({
    chips: z.array(FilterChip).min(1),
    savedViews: z.array(SavedView).optional(),
    showSearch: z.boolean().optional(),
  }),
});
```

- [ ] **Step 3: FilterBar component**

```tsx
// packages/library/src/components/FilterBar/FilterBar.tsx
import * as React from "react";
import { z } from "zod";
import type { FilterBarNode } from "@tentoroforge/schema";
import { useUrlState } from "../../style/useUrlState";

type Props = z.infer<typeof FilterBarNode>["props"];

function FilterChipDropdown({ filter }: { filter: Props["chips"][number] }) {
  const [value, setValue] = useUrlState(filter.key, filter.defaultValue ?? "");
  const [open, setOpen] = React.useState(false);
  const current = filter.options.find((o) => o.value === value)?.label ?? "Any";

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-card px-2.5 text-xs font-medium hover:bg-muted/50"
      >
        <span className="text-muted-foreground">{filter.label}:</span>
        <span className="text-foreground">{current}</span>
        <span className="opacity-60">▾</span>
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 min-w-[160px] rounded-md border border-border bg-popover py-1 shadow-md z-10">
          <button
            type="button"
            onClick={() => { setValue(filter.defaultValue ?? ""); setOpen(false); }}
            className={`block w-full px-3 py-1.5 text-left text-xs hover:bg-muted ${!value ? "font-semibold" : ""}`}
          >
            Any
          </button>
          {filter.options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => { setValue(opt.value); setOpen(false); }}
              className={`block w-full px-3 py-1.5 text-left text-xs hover:bg-muted ${value === opt.value ? "font-semibold text-foreground" : "text-muted-foreground"}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function FilterBar({ chips, savedViews, showSearch }: Props) {
  const [search, setSearch] = useUrlState("q", "");

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-card p-2">
      {showSearch && (
        <input
          type="text"
          placeholder="Search…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 rounded-md border border-border bg-background px-2.5 text-xs flex-1 min-w-[180px]"
        />
      )}
      {chips.map((chip) => (
        <FilterChipDropdown key={chip.key} filter={chip} />
      ))}
      {savedViews && savedViews.length > 0 && (
        <div className="ml-auto">
          <select
            onChange={(e) => {
              const view = savedViews.find((v) => v.id === e.target.value);
              if (!view) return;
              const params = new URLSearchParams();
              for (const [k, v] of Object.entries(view.filters)) params.set(k, v);
              const newUrl = `${window.location.pathname}?${params.toString()}`;
              window.history.replaceState({}, "", newUrl);
              window.dispatchEvent(new PopStateEvent("popstate"));
            }}
            className="h-8 rounded-md border border-border bg-card px-2 text-xs"
            defaultValue=""
          >
            <option value="" disabled>Saved views…</option>
            {savedViews.map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Schema wrapper + library exports**

```ts
// FilterBar.schema.ts
import { z } from "zod";
import { FilterBarNode } from "@tentoroforge/schema";
export const FilterBarProps = FilterBarNode.shape.props;
export type FilterBarPropsType = z.infer<typeof FilterBarProps>;
```

In `packages/library/src/index.ts`:
```ts
export { FilterBar } from "./components/FilterBar/FilterBar";
export { FilterBarProps as FilterBarPropsSchema, type FilterBarPropsType } from "./components/FilterBar/FilterBar.schema";
export { useUrlState } from "./style/useUrlState";
```

- [ ] **Step 5: Verify + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

git add packages/library/src/components/FilterBar/ \
        packages/library/src/style/useUrlState.ts \
        packages/library/src/index.ts \
        packages/schema/src/nodes/enterprise.ts
git commit -m "feat(library): FilterBar with URL-persisted state + saved views + useUrlState hook"
```

---

## Task 4: CommandPalette

**Files:**
- Modify: `packages/library/package.json` — add `cmdk` dep
- Create: `packages/library/src/components/CommandPalette/CommandPalette.tsx`
- Create: `packages/library/src/components/CommandPalette/CommandPalette.schema.ts`
- Modify: `packages/schema/src/nodes/enterprise.ts` — append CommandPaletteNode

- [ ] **Step 1: Add cmdk dep**

In `packages/library/package.json`, add to dependencies:
```json
"cmdk": "^1.0.0"
```

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npm install --legacy-peer-deps
node -e "console.log(require.resolve('cmdk'))"
```

- [ ] **Step 2: CommandPaletteNode**

Append to `packages/schema/src/nodes/enterprise.ts`:

```ts
const CommandItem = z.object({
  id: z.string(),
  label: z.string(),
  group: z.string().optional(),       // for grouping (Pages / Actions / Records)
  shortcut: z.string().optional(),    // visible hint, e.g. "⌘N"
  action: z.discriminatedUnion("type", [
    z.object({ type: z.literal("navigate"), to: z.string() }),
    z.object({ type: z.literal("workflow"), workflow: z.string() }),
  ]),
});

export const CommandPaletteNode = z.object({
  id: z.string(),
  type: z.literal("CommandPalette"),
  props: z.object({
    items: z.array(CommandItem).min(1),
    placeholder: z.string().optional(),
    triggerKey: z.string().optional(),  // default "k" (i.e. Cmd+K / Ctrl+K)
  }),
});
```

- [ ] **Step 3: CommandPalette component**

```tsx
// packages/library/src/components/CommandPalette/CommandPalette.tsx
"use client";

import * as React from "react";
import { Command } from "cmdk";
import { z } from "zod";
import type { CommandPaletteNode } from "@tentoroforge/schema";

type Props = z.infer<typeof CommandPaletteNode>["props"];

export function CommandPalette({ items, placeholder = "Type a command or search…", triggerKey = "k" }: Props) {
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === triggerKey) {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape" && open) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [triggerKey, open]);

  // Group items by group prop
  const groups = React.useMemo(() => {
    const out: Record<string, typeof items> = {};
    for (const item of items) {
      const g = item.group ?? "General";
      if (!out[g]) out[g] = [];
      out[g].push(item);
    }
    return out;
  }, [items]);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex h-8 items-center gap-2 rounded-md border border-border bg-muted/40 px-2.5 text-xs text-muted-foreground hover:bg-muted/60"
        title={`Open command palette (${navigator?.platform?.includes("Mac") ? "⌘" : "Ctrl"}+${triggerKey.toUpperCase()})`}
      >
        <span>Search…</span>
        <kbd className="rounded border border-border bg-background px-1 font-mono text-[10px]">
          {navigator?.platform?.includes("Mac") ? "⌘" : "Ctrl"}+{triggerKey.toUpperCase()}
        </kbd>
      </button>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-foreground/20 backdrop-blur-sm pt-[12vh]"
      onClick={() => setOpen(false)}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl rounded-lg border border-border bg-popover shadow-2xl"
      >
        <Command label="Command palette" className="flex flex-col">
          <Command.Input
            placeholder={placeholder}
            className="h-12 w-full bg-transparent px-4 text-sm outline-none border-b border-border"
          />
          <Command.List className="max-h-[400px] overflow-auto p-1">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
              No results.
            </Command.Empty>
            {Object.entries(groups).map(([groupName, groupItems]) => (
              <Command.Group key={groupName} heading={groupName} className="text-[10px] uppercase tracking-wide text-muted-foreground px-2 pt-2">
                {groupItems.map((item) => (
                  <Command.Item
                    key={item.id}
                    value={`${item.label} ${item.group ?? ""}`}
                    onSelect={() => {
                      if (item.action.type === "navigate") {
                        window.location.assign(item.action.to);
                      } else {
                        // Workflow — emit a custom event so the host can handle dispatch
                        window.dispatchEvent(new CustomEvent("command-palette:workflow", {
                          detail: { workflow: item.action.workflow, itemId: item.id },
                        }));
                      }
                      setOpen(false);
                    }}
                    className="flex items-center justify-between rounded-md px-2 py-1.5 text-sm cursor-pointer hover:bg-muted aria-selected:bg-muted"
                  >
                    <span>{item.label}</span>
                    {item.shortcut && (
                      <kbd className="ml-2 rounded border border-border bg-background px-1.5 font-mono text-[10px] text-muted-foreground">
                        {item.shortcut}
                      </kbd>
                    )}
                  </Command.Item>
                ))}
              </Command.Group>
            ))}
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Schema wrapper + library exports**

```ts
// CommandPalette.schema.ts
import { z } from "zod";
import { CommandPaletteNode } from "@tentoroforge/schema";
export const CommandPaletteProps = CommandPaletteNode.shape.props;
export type CommandPalettePropsType = z.infer<typeof CommandPaletteProps>;
```

In `packages/library/src/index.ts`:
```ts
export { CommandPalette } from "./components/CommandPalette/CommandPalette";
export { CommandPaletteProps as CommandPalettePropsSchema, type CommandPalettePropsType } from "./components/CommandPalette/CommandPalette.schema";
```

- [ ] **Step 5: Verify + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

git add packages/library/package.json package-lock.json \
        packages/library/src/components/CommandPalette/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/enterprise.ts
git commit -m "feat(library): CommandPalette — Cmd-K modal with fuzzy search via cmdk"
```

---

## Task 5: ActivityFeed

**Files:**
- Create: `packages/library/src/components/ActivityFeed/ActivityFeed.tsx`
- Create: `packages/library/src/components/ActivityFeed/ActivityFeed.schema.ts`
- Modify: `packages/schema/src/nodes/enterprise.ts` — append ActivityFeedNode

ActivityFeed is project-wide (multiple actors / multiple targets), distinct from Timeline (single-entity history). Visually uses smaller rows and richer per-row metadata.

- [ ] **Step 1: ActivityFeedNode**

Append to `packages/schema/src/nodes/enterprise.ts`:

```ts
const ActivityEntry = z.object({
  id: z.string(),
  timestamp: z.string(),  // ISO 8601
  actor: z.object({
    name: z.string(),
    avatarInitials: z.string().optional(),
    avatarUrl: z.string().optional(),
  }),
  action: z.string(),     // e.g. "approved", "submitted", "commented on"
  target: z.string(),     // e.g. "Q1 Vacation Request" (the thing acted on)
  detail: z.string().optional(),  // one-line additional context
  category: z.enum(["create", "update", "approve", "reject", "comment", "system"]).optional(),
});

export const ActivityFeedNode = z.object({
  id: z.string(),
  type: z.literal("ActivityFeed"),
  props: z.object({
    entries: z.array(ActivityEntry),
    title: z.string().optional(),
    showFilter: z.boolean().optional(),
    maxHeight: z.number().optional(),  // px
  }),
});
```

- [ ] **Step 2: ActivityFeed component**

```tsx
// packages/library/src/components/ActivityFeed/ActivityFeed.tsx
import * as React from "react";
import { z } from "zod";
import type { ActivityFeedNode } from "@tentoroforge/schema";

type Props = z.infer<typeof ActivityFeedNode>["props"];

const CATEGORY_TONE: Record<string, string> = {
  create:  "bg-emerald-500/10 text-emerald-700 border-emerald-200",
  update:  "bg-blue-500/10 text-blue-700 border-blue-200",
  approve: "bg-emerald-500/10 text-emerald-700 border-emerald-200",
  reject:  "bg-rose-500/10 text-rose-700 border-rose-200",
  comment: "bg-violet-500/10 text-violet-700 border-violet-200",
  system:  "bg-muted text-muted-foreground border-border",
};

function formatRelative(iso: string): string {
  const date = new Date(iso);
  const diff = Date.now() - date.getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return date.toLocaleDateString();
}

function getInitials(name: string, fallback?: string): string {
  if (fallback) return fallback;
  const parts = name.trim().split(/\s+/);
  return parts.length === 1
    ? parts[0].slice(0, 2).toUpperCase()
    : (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function ActivityFeed({ entries, title = "Activity", maxHeight }: Props) {
  return (
    <section className="rounded-md border border-border bg-card">
      <header className="border-b border-border px-3 py-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      </header>
      <ol
        className="overflow-y-auto"
        style={{ maxHeight: maxHeight ?? 480 }}
      >
        {entries.length === 0 ? (
          <li className="px-3 py-8 text-center text-xs text-muted-foreground">No activity yet.</li>
        ) : entries.map((e) => (
          <li key={e.id} className="flex gap-3 border-b border-border last:border-b-0 px-3 py-2.5 hover:bg-muted/30">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary text-[11px] font-semibold">
              {e.actor.avatarUrl
                ? <img src={e.actor.avatarUrl} alt={e.actor.name} className="h-full w-full rounded-full object-cover" />
                : <span>{getInitials(e.actor.name, e.actor.avatarInitials)}</span>}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs leading-tight">
                <span className="font-medium">{e.actor.name}</span>
                <span className="text-muted-foreground"> {e.action} </span>
                <span className="font-medium">{e.target}</span>
              </p>
              {e.detail && <p className="mt-0.5 text-[11px] text-muted-foreground line-clamp-2">{e.detail}</p>}
              <div className="mt-1 flex items-center gap-2">
                <span className="text-[10px] text-muted-foreground/70">{formatRelative(e.timestamp)}</span>
                {e.category && (
                  <span className={`rounded border px-1.5 py-0 text-[9px] uppercase tracking-wide ${CATEGORY_TONE[e.category] ?? CATEGORY_TONE.system}`}>
                    {e.category}
                  </span>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
```

- [ ] **Step 3: Schema wrapper + library exports**

```ts
// ActivityFeed.schema.ts
import { z } from "zod";
import { ActivityFeedNode } from "@tentoroforge/schema";
export const ActivityFeedProps = ActivityFeedNode.shape.props;
export type ActivityFeedPropsType = z.infer<typeof ActivityFeedProps>;
```

In `packages/library/src/index.ts`:
```ts
export { ActivityFeed } from "./components/ActivityFeed/ActivityFeed";
export { ActivityFeedProps as ActivityFeedPropsSchema, type ActivityFeedPropsType } from "./components/ActivityFeed/ActivityFeed.schema";
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

git add packages/library/src/components/ActivityFeed/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/enterprise.ts
git commit -m "feat(library): ActivityFeed — project-wide audit-trail with relative timestamps"
```

---

## Task 6: NodeV2 union + render-scaffold registry

- [ ] **Step 1: Add new nodes to NodeV2 union**

Edit `packages/schema/src/page.ts`. Find the existing `NodeV2 = z.discriminatedUnion("type", [...])`. Add the 5 new nodes:

```ts
import {
  ApprovalStepperNode, PersonCardNode, FilterBarNode,
  CommandPaletteNode, ActivityFeedNode,
} from "./nodes/enterprise";

// In the discriminatedUnion array:
ApprovalStepperNode,
PersonCardNode,
FilterBarNode,
CommandPaletteNode,
ActivityFeedNode,
```

- [ ] **Step 2: Register in scaffold**

Read `apps/render-scaffold/src/app/p/[projectId]/[...slug]/SchemaRendererWrapper.tsx` (or wherever the registry is built — see Wave 1's commits for the pattern). Add 5 new imports + reg() calls:

```tsx
import {
  ApprovalStepper, PersonCard, FilterBar, CommandPalette, ActivityFeed,
  ApprovalStepperPropsSchema, PersonCardPropsSchema, FilterBarPropsSchema,
  CommandPalettePropsSchema, ActivityFeedPropsSchema,
} from "@tentoroforge/library";

reg("ApprovalStepper", ApprovalStepper, ApprovalStepperPropsSchema, "data");
reg("PersonCard",      PersonCard,      PersonCardPropsSchema,      "static");
reg("FilterBar",       FilterBar,       FilterBarPropsSchema,       "navigation");
reg("CommandPalette",  CommandPalette,  CommandPalettePropsSchema,  "navigation");
reg("ActivityFeed",    ActivityFeed,    ActivityFeedPropsSchema,    "data");
```

- [ ] **Step 3: Library + schema rebuild**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema && npm run build 2>&1 | tail -3
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npm run build 2>&1 | tail -3
```

- [ ] **Step 4: Verify scaffold boots**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
lsof -ti:6503 | xargs kill -9 2>/dev/null || true
cd apps/render-scaffold && npm run dev > /tmp/scaffold-t2w2.log 2>&1 &
sleep 10
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:6503/
lsof -ti:6503 | xargs kill -9 2>/dev/null || true
```

Expected: 200.

- [ ] **Step 5: Commit**

```bash
git add packages/schema/src/page.ts \
        apps/render-scaffold/src/app/p/\[projectId\]/\[...slug\]/SchemaRendererWrapper.tsx
git commit -m "feat(scaffold): register ApprovalStepper/PersonCard/FilterBar/CommandPalette/ActivityFeed in NodeV2 + render registry"
```

---

## Task 7: Playground entries + visual regression baselines

- [ ] **Step 1: Add 5 playground sections**

Edit `frontend/src/app/(dev-only)/component-playground/page.tsx` (the inner client component PlaygroundInner). Add:

```tsx
import {
  ApprovalStepper, PersonCard, FilterBar, CommandPalette, ActivityFeed,
} from "@tentoroforge/library";

// Section: ApprovalStepper
<section data-component="ApprovalStepper" className={SECTION}>
  <p className={TITLE}>ApprovalStepper</p>
  <ApprovalStepper steps={[
    { id: "1", label: "Submitted",      status: "approved", actor: "Sarah Chen",   timestamp: "2026-04-29T09:00:00Z" },
    { id: "2", label: "Manager Review", status: "approved", actor: "Marcus Lee",   timestamp: "2026-04-30T14:00:00Z" },
    { id: "3", label: "HR Review",      status: "current",  actor: "Priya Shah" },
    { id: "4", label: "Final",          status: "pending" },
  ]} />
</section>

// Section: PersonCard
<section data-component="PersonCard" className={SECTION}>
  <p className={TITLE}>PersonCard — compact + expanded</p>
  <div className="flex gap-6">
    <PersonCard name="Sarah Chen" role="Senior Engineer" status="active" />
    <div className="w-64">
      <PersonCard name="Marcus Lee" role="Engineering Manager" department="Engineering"
                   email="marcus.lee@example.com" status="active"
                   manager={{ name: "Diego Alvarez", role: "VP Engineering" }}
                   layout="expanded" />
    </div>
  </div>
</section>

// Section: FilterBar
<section data-component="FilterBar" className={SECTION}>
  <p className={TITLE}>FilterBar</p>
  <FilterBar
    showSearch
    chips={[
      { key: "dept", label: "Department", options: [
        { value: "eng", label: "Engineering" },
        { value: "design", label: "Design" },
        { value: "sales", label: "Sales" },
      ]},
      { key: "status", label: "Status", options: [
        { value: "active", label: "Active" },
        { value: "leave", label: "On Leave" },
      ]},
    ]}
    savedViews={[
      { id: "recent-eng", label: "Recent Engineering Hires", filters: { dept: "eng" } },
    ]}
  />
</section>

// Section: CommandPalette
<section data-component="CommandPalette" className={SECTION}>
  <p className={TITLE}>CommandPalette — Cmd+K to open</p>
  <CommandPalette items={[
    { id: "n1", label: "New Leave Request",   group: "Actions", shortcut: "⌘N",
      action: { type: "navigate", to: "/leave-requests/new" }},
    { id: "n2", label: "Browse Employees",    group: "Pages",
      action: { type: "navigate", to: "/employees" }},
    { id: "n3", label: "Approve all pending", group: "Actions",
      action: { type: "workflow", workflow: "ApproveAllPending" }},
  ]} />
</section>

// Section: ActivityFeed
<section data-component="ActivityFeed" className={SECTION}>
  <p className={TITLE}>ActivityFeed</p>
  <div className="max-w-md">
    <ActivityFeed entries={[
      { id: "1", timestamp: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
        actor: { name: "Sarah Chen" }, action: "approved", target: "Q1 Vacation Request",
        category: "approve" },
      { id: "2", timestamp: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
        actor: { name: "Marcus Lee" }, action: "commented on", target: "Engineering Hiring Plan",
        detail: "Great progress; let's discuss Q2 priorities tomorrow.",
        category: "comment" },
      { id: "3", timestamp: new Date(Date.now() - 86400 * 1000).toISOString(),
        actor: { name: "HR System" }, action: "created", target: "Annual Review Cycle",
        category: "system" },
    ]} />
  </div>
</section>
```

- [ ] **Step 2: Update visual regression spec**

In `apps/visual-regression/tests/components.spec.ts`, append to COMPONENTS array:
```ts
"ApprovalStepper", "PersonCard", "FilterBar", "CommandPalette", "ActivityFeed",
```

- [ ] **Step 3: Capture baselines**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
npm run dev -- -p 6501 > /tmp/frontend-t2w2-baseline.log 2>&1 &
sleep 15
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test --grep "ApprovalStepper|PersonCard|FilterBar|CommandPalette|ActivityFeed" --update-snapshots
npx playwright test --grep "ApprovalStepper|PersonCard|FilterBar|CommandPalette|ActivityFeed"
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: 5 new tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/\(dev-only\)/component-playground/ \
        apps/visual-regression/tests/
git commit -m "feat(playground): add ApprovalStepper/PersonCard/FilterBar/CommandPalette/ActivityFeed + baselines"
```

---

## Task 8: schema_prompt teaches new components

Append to `backend/services/schema_prompt.py`:

```python
TIER2_BATCH2_GUIDANCE = """
## TIER 2 COMPONENTS BATCH 2 (enterprise patterns)

  ApprovalStepper { steps: { id, label, status, actor?, timestamp? }[],
                    orientation?: "horizontal"|"vertical" }
    For multi-stage approval flows. Each step's status is one of:
    pending|current|approved|rejected|skipped. Use horizontal for top-of-page
    progress indicators; vertical for sidebar/detail-panel approval history.

  PersonCard { name, role?, department?, avatarUrl?, avatarInitials?,
               email?, status?, manager?, layout?: "compact"|"expanded" }
    Avatar + name + role + manager + status combined. Use compact in lists +
    inline. Use expanded as a sidebar widget for "you are managed by X".
    Status enum: active|away|on-leave|offline.

  FilterBar { chips, savedViews?, showSearch? }
    URL-persisted filter management. Each chip is {key, label, options[]}.
    State writes to URL search params via useUrlState. Use ABOVE DataGrid
    for filterable lists. The savedViews dropdown applies a preset of
    multiple filter values at once.

  CommandPalette { items, placeholder?, triggerKey? }
    Cmd-K modal with fuzzy search. Each item has id + label + group? +
    shortcut? + action (navigate or workflow). Use as a top-level page
    affordance for power users — typically mounted once per app shell, not
    per page. Lists pages + actions + recent records.

  ActivityFeed { entries, title?, showFilter?, maxHeight? }
    Project-wide audit-trail sidebar. Different from Timeline (which is
    per-entity history). Each entry is {actor, action, target, timestamp,
    category?, detail?}. Categories: create|update|approve|reject|comment|
    system. Use as a right-rail widget on dashboards / console pages.

ANTI-PATTERNS:
  - Using Timeline for project-wide activity: prefer ActivityFeed
  - Using ApprovalStepper as the only content of a page: combine with
    DataGrid or KeyValueList showing the request being approved
  - Using FilterBar without DataGrid: filters with no list to filter is dead UI
  - Using PersonCard.expanded inline in a row: layout="compact" is for rows
"""
```

Insert after the existing TIER2_COMPONENTS_GUIDANCE block.

- [ ] **Step 1: Verify schema_prompt tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_schema_prompt.py -v 2>&1 | tail -10
```

Expected: existing tests still pass.

- [ ] **Step 2: Commit**

```bash
git add backend/services/schema_prompt.py
git commit -m "feat(schema-prompt): teach Tier 2 batch 2 components + anti-patterns"
```

---

## Task 9: Final verification

- [ ] **Step 1: Backend tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/integration/test_schema_migration.py tests/services/test_schema_prompt.py -v 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 2: Library + schema build**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema && npm run build 2>&1 | tail -3
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npm run build 2>&1 | tail -3
```

- [ ] **Step 3: Bundle-size sanity**

cmdk adds ~10KB; should not be a concern.

If everything passes, no separate commit needed.

---

## Self-review

### Spec coverage

| Spec section | Tasks |
|---|---|
| ApprovalStepper | 1 |
| PersonCard | 2 |
| FilterBar + useUrlState | 3 |
| CommandPalette | 4 |
| ActivityFeed | 5 |
| NodeV2 + scaffold registry | 6 |
| Playground + baselines | 7 |
| schema_prompt | 8 |
| Verification | 9 |

✓ All Wave 2 scope covered.

### Type consistency

- Each new node defined in `packages/schema/src/nodes/enterprise.ts`
- Each library component re-exports `<Name>Props` as `<Name>PropsSchema` (matches Wave 1 pattern)
- All 5 nodes added to NodeV2 discriminated union

✓ Consistent.

---

## Out of scope (deferred to Wave 3+)

- **OrgChart** — explicitly deferred per spec (Tier 2.5)
- **MultiSelect** — Wave 3
- **DataGrid integration with FilterBar** — Wave 6 (schema patterns) demonstrates the composition
- **Reference bank re-seed with new components** — Wave 6
