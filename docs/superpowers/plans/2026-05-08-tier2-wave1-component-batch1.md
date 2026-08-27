# Tier 2 Wave 1 — Component Batch 1: Chart + Sparkline + DataGrid + Timeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Add the 4 highest-leverage missing components to the library. After this wave, the LLM can compose chart-driven dashboards, frozen/sortable tables, sparkline-enriched metric rows, and timeline visualisations — patterns that are ubiquitous in real enterprise UIs and currently impossible to express with the v1 component vocabulary.

**Architecture:** Each component is a new directory under `packages/library/src/components/<Name>/` containing `<Name>.tsx`, `<Name>.schema.ts`, and CVA `variants.ts`. Each gets a Zod node in `packages/schema/src/nodes/`, a registry entry in the render-scaffold's `buildRegistry()`, prop documentation in the schema agent's prompt, and a playground entry with visual-regression baseline. Components consume tokens via the Tier 1 hooks (`useDensity`, `useElevation`, `useTokens`).

**Tech Stack:** TypeScript / React 19 / Tailwind / CVA / Zod (existing). New deps: `recharts` (Chart implementation), `@tanstack/react-virtual` (DataGrid virtualisation). Both MIT-licensed, mature, no peer-dep conflicts.

**Spec:** `docs/superpowers/specs/2026-05-08-enterprise-depth-design.md` § Theme A (components batch 1).

---

## File structure

### New files

**Chart family (4 sub-types in one component dir):**
- `packages/library/src/components/Chart/Chart.tsx` — main component, dispatches to subtype
- `packages/library/src/components/Chart/Chart.schema.ts`
- `packages/library/src/components/Chart/variants.ts`
- `packages/library/src/components/Chart/LineChart.tsx`
- `packages/library/src/components/Chart/BarChart.tsx`
- `packages/library/src/components/Chart/AreaChart.tsx`

**Sparkline:**
- `packages/library/src/components/Sparkline/Sparkline.tsx`
- `packages/library/src/components/Sparkline/Sparkline.schema.ts`

**DataGrid:**
- `packages/library/src/components/DataGrid/DataGrid.tsx`
- `packages/library/src/components/DataGrid/DataGrid.schema.ts`
- `packages/library/src/components/DataGrid/variants.ts`
- `packages/library/src/components/DataGrid/useVirtualRows.ts` — wraps @tanstack/react-virtual

**Timeline:**
- `packages/library/src/components/Timeline/Timeline.tsx`
- `packages/library/src/components/Timeline/Timeline.schema.ts`
- `packages/library/src/components/Timeline/variants.ts`

**Schema package node definitions:**
- `packages/schema/src/nodes/charts.ts` — `ChartNode`, `LineChartNode`, `BarChartNode`, `AreaChartNode`, `SparklineNode`
- `packages/schema/src/nodes/data-display.ts` — `DataGridNode`, `TimelineNode`

### Modified files

- `packages/library/src/index.ts` — export 4 new components
- `packages/library/package.json` — add `recharts`, `@tanstack/react-virtual` deps
- `packages/schema/src/page.ts` — add new nodes to NodeV2 union
- `packages/schema/src/index.ts` — re-export new node files
- `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx` — register the 4 new components in `buildRegistry()`
- `frontend/src/app/(dev-only)/component-playground/page.tsx` — add 4 playground sections
- `apps/visual-regression/tests/components.spec.ts` — add 4 new component IDs to COMPONENTS array
- `backend/services/schema_prompt.py` — append component contract block for the 4 new components

---

## Task 1: Add deps + scaffolding

**Files:**
- Modify: `packages/library/package.json`

- [ ] **Step 1: Add deps**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library
# Append to dependencies in package.json:
#   "recharts": "^2.13.0",
#   "@tanstack/react-virtual": "^3.10.8"
```

Edit `packages/library/package.json` to add these to `"dependencies"`:
```json
"recharts": "^2.13.0",
"@tanstack/react-virtual": "^3.10.8"
```

- [ ] **Step 2: Install at root**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npm install --legacy-peer-deps
```

Verify both resolve:
```bash
node -e "console.log(require.resolve('recharts'))"
node -e "console.log(require.resolve('@tanstack/react-virtual'))"
```

- [ ] **Step 3: Bundle-size sanity check**

Recharts adds ~70KB gzipped. @tanstack/react-virtual is ~3KB. Acceptable but flag in commit.

- [ ] **Step 4: Commit**

```bash
git add packages/library/package.json package-lock.json
git commit -m "feat(library): add recharts + @tanstack/react-virtual for Chart/DataGrid"
```

---

## Task 2: Sparkline (smallest, builds confidence)

**Files:**
- Create: `packages/library/src/components/Sparkline/Sparkline.tsx`
- Create: `packages/library/src/components/Sparkline/Sparkline.schema.ts`
- Create: `packages/schema/src/nodes/charts.ts` (initial — Sparkline node only; expanded in Task 3)

- [ ] **Step 1: Sparkline node Zod schema**

```ts
// packages/schema/src/nodes/charts.ts (initial)
import { z } from "zod";

export const SparklineNode = z.object({
  id: z.string(),
  type: z.literal("Sparkline"),
  props: z.object({
    data: z.array(z.number()).min(2),
    width:  z.number().optional(),     // default 100
    height: z.number().optional(),     // default 24
    color:  z.string().optional(),     // CSS color or token path
    showDots: z.boolean().optional(),  // default false
  }),
});
```

Re-export from `packages/schema/src/index.ts`:
```ts
export * from "./nodes/charts";
```

- [ ] **Step 2: Sparkline.schema.ts (library-side wrapper)**

```ts
// packages/library/src/components/Sparkline/Sparkline.schema.ts
import { z } from "zod";
import { SparklineNode } from "@tentoroforge/schema";

export const SparklineProps = SparklineNode.shape.props;
export type SparklinePropsType = z.infer<typeof SparklineProps>;
```

- [ ] **Step 3: Sparkline component**

```tsx
// packages/library/src/components/Sparkline/Sparkline.tsx
import * as React from "react";
import type { SparklinePropsType } from "./Sparkline.schema";

export interface SparklineProps extends SparklinePropsType {}

/**
 * Inline mini-chart — just the shape, no axes, no tooltips.
 * Use inside DataGrid cells, MetricTile trends, dashboard rows.
 */
export function Sparkline({
  data, width = 100, height = 24, color = "currentColor", showDots = false,
}: SparklineProps) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 2) - 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" points={points.join(" ")} />
      {showDots && data.map((v, i) => {
        const x = (i / (data.length - 1)) * width;
        const y = height - ((v - min) / range) * (height - 2) - 1;
        return <circle key={i} cx={x} cy={y} r="1.5" fill={color} />;
      })}
    </svg>
  );
}
```

- [ ] **Step 4: Export + verify**

In `packages/library/src/index.ts` add:
```ts
export { Sparkline, type SparklineProps } from "./components/Sparkline/Sparkline";
export { SparklineProps as SparklinePropsSchema } from "./components/Sparkline/Sparkline.schema";
```

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add packages/library/src/components/Sparkline/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/charts.ts \
        packages/schema/src/index.ts
git commit -m "feat(library): Sparkline component — inline mini-chart for tables/metrics"
```

---

## Task 3: Chart family (LineChart / BarChart / AreaChart)

**Files:**
- Create: `packages/library/src/components/Chart/Chart.tsx` (dispatcher)
- Create: `packages/library/src/components/Chart/LineChart.tsx`
- Create: `packages/library/src/components/Chart/BarChart.tsx`
- Create: `packages/library/src/components/Chart/AreaChart.tsx`
- Create: `packages/library/src/components/Chart/Chart.schema.ts`
- Create: `packages/library/src/components/Chart/variants.ts`
- Modify: `packages/schema/src/nodes/charts.ts` — append ChartNode

- [ ] **Step 1: Chart node Zod schema**

Append to `packages/schema/src/nodes/charts.ts`:

```ts
const ChartSeries = z.object({
  name: z.string(),
  dataKey: z.string(),
  color: z.string().optional(),
});

export const ChartNode = z.object({
  id: z.string(),
  type: z.literal("Chart"),
  props: z.object({
    chartType: z.enum(["line", "bar", "area"]),
    data: z.array(z.record(z.union([z.string(), z.number()]))),
    xKey: z.string(),
    series: z.array(ChartSeries).min(1),
    height: z.number().optional(),
    showGrid: z.boolean().optional(),
    showLegend: z.boolean().optional(),
    showTooltip: z.boolean().optional(),
  }),
});
```

- [ ] **Step 2: Chart.schema.ts**

```ts
// packages/library/src/components/Chart/Chart.schema.ts
import { z } from "zod";
import { ChartNode } from "@tentoroforge/schema";
export const ChartProps = ChartNode.shape.props;
export type ChartPropsType = z.infer<typeof ChartProps>;
```

- [ ] **Step 3: LineChart.tsx (uses recharts)**

```tsx
// packages/library/src/components/Chart/LineChart.tsx
import * as React from "react";
import {
  LineChart as ReLineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import type { ChartPropsType } from "./Chart.schema";
import { useTokens } from "../../theme/tokens-context";

const DEFAULT_PALETTE = ["var(--color-primary-500)", "var(--color-secondary-500)", "var(--color-accent-500)"];

export function LineChartImpl(props: ChartPropsType) {
  const tokens = useTokens();
  const numericFamily = tokens.typography?.numeric?.family;
  return (
    <div style={{ width: "100%", height: props.height ?? 240, fontFamily: numericFamily }}>
      <ResponsiveContainer>
        <ReLineChart data={props.data}>
          {props.showGrid !== false && <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />}
          <XAxis dataKey={props.xKey} stroke="var(--color-text-tertiary)" fontSize={11} />
          <YAxis stroke="var(--color-text-tertiary)" fontSize={11} />
          {props.showTooltip !== false && <Tooltip />}
          {props.showLegend !== false && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {props.series.map((s, i) => (
            <Line key={s.dataKey} type="monotone" dataKey={s.dataKey} name={s.name}
                  stroke={s.color ?? DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]}
                  strokeWidth={2} dot={{ r: 3 }} />
          ))}
        </ReLineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 4: BarChart.tsx + AreaChart.tsx**

Same pattern as LineChart.tsx, swapping recharts primitives:
- BarChart: `BarChart` + `Bar`
- AreaChart: `AreaChart` + `Area` (with `fill` prop using a 30% alpha of the color)

Each ~30 lines, follow LineChart structure.

- [ ] **Step 5: Chart dispatcher**

```tsx
// packages/library/src/components/Chart/Chart.tsx
import * as React from "react";
import type { ChartPropsType } from "./Chart.schema";
import { LineChartImpl } from "./LineChart";
import { BarChartImpl } from "./BarChart";
import { AreaChartImpl } from "./AreaChart";

export interface ChartProps extends ChartPropsType {}

export function Chart(props: ChartProps) {
  switch (props.chartType) {
    case "line": return <LineChartImpl {...props} />;
    case "bar":  return <BarChartImpl {...props} />;
    case "area": return <AreaChartImpl {...props} />;
  }
}
```

- [ ] **Step 6: Export + verify**

In `packages/library/src/index.ts`:
```ts
export { Chart, type ChartProps } from "./components/Chart/Chart";
export { ChartProps as ChartPropsSchema } from "./components/Chart/Chart.schema";
```

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true
```

- [ ] **Step 7: Commit**

```bash
git add packages/library/src/components/Chart/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/charts.ts
git commit -m "feat(library): Chart family (line/bar/area) using recharts"
```

---

## Task 4: DataGrid

**Files:**
- Create: `packages/library/src/components/DataGrid/DataGrid.tsx`
- Create: `packages/library/src/components/DataGrid/DataGrid.schema.ts`
- Create: `packages/library/src/components/DataGrid/variants.ts`
- Create: `packages/library/src/components/DataGrid/useVirtualRows.ts`
- Create: `packages/schema/src/nodes/data-display.ts`

- [ ] **Step 1: DataGrid node Zod schema**

```ts
// packages/schema/src/nodes/data-display.ts
import { z } from "zod";

const DataGridColumn = z.object({
  key: z.string(),
  label: z.string(),
  width: z.union([z.number(), z.string()]).optional(),
  sortable: z.boolean().optional(),
  frozen: z.boolean().optional(),
  align: z.enum(["left", "center", "right"]).optional(),
  render: z.object({
    component: z.string(),
    props: z.record(z.any()).optional(),
  }).optional(),
});

export const DataGridNode = z.object({
  id: z.string(),
  type: z.literal("DataGrid"),
  props: z.object({
    columns: z.array(DataGridColumn).min(1),
    rows: z.array(z.record(z.any())),  // open shape — row keys match column.key
    rowKey: z.string(),                // identifies a row's primary key
    virtualise: z.boolean().optional(),  // default: auto when rows > 100
    selectable: z.boolean().optional(),
    expandable: z.boolean().optional(),
    rowActions: z.array(z.object({
      label: z.string(),
      action: z.object({
        type: z.literal("workflow"),
        workflow: z.string(),
      }),
    })).optional(),
  }),
});
```

Re-export from `packages/schema/src/index.ts`:
```ts
export * from "./nodes/data-display";
```

- [ ] **Step 2: useVirtualRows.ts**

```ts
// packages/library/src/components/DataGrid/useVirtualRows.ts
import { useVirtualizer } from "@tanstack/react-virtual";
import * as React from "react";

export function useVirtualRows(
  scrollRef: React.RefObject<HTMLDivElement>,
  rowCount: number,
  rowHeight: number,
) {
  return useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 5,
  });
}
```

- [ ] **Step 3: DataGrid component**

```tsx
// packages/library/src/components/DataGrid/DataGrid.tsx
import * as React from "react";
import type { DataGridNode } from "@tentoroforge/schema";
import { useDensity } from "../../theme/tokens-context";
import { useVirtualRows } from "./useVirtualRows";

type Props = React.ComponentProps<"div"> & import("zod").infer<typeof DataGridNode>["props"];

const DENSITY_ROW_HEIGHT: Record<string, number> = {
  compact: 32, comfortable: 40, spacious: 52,
};

export function DataGrid({ columns, rows, rowKey, virtualise, selectable, expandable, rowActions }: Props) {
  const density = useDensity();
  const rowHeight = DENSITY_ROW_HEIGHT[density] ?? 40;
  const shouldVirtualise = virtualise ?? rows.length > 100;
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const virtualiser = useVirtualRows(scrollRef, rows.length, rowHeight);
  const [sortBy, setSortBy] = React.useState<{ key: string; dir: "asc" | "desc" } | null>(null);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());

  const sortedRows = React.useMemo(() => {
    if (!sortBy) return rows;
    return [...rows].sort((a, b) => {
      const av = a[sortBy.key];
      const bv = b[sortBy.key];
      if (av === bv) return 0;
      const cmp = av > bv ? 1 : -1;
      return sortBy.dir === "asc" ? cmp : -cmp;
    });
  }, [rows, sortBy]);

  const renderRow = (row: Record<string, any>, index: number) => (
    <tr key={String(row[rowKey] ?? index)}
        className="border-b border-border hover:bg-muted/30"
        style={{ height: rowHeight }}>
      {selectable && (
        <td className="w-10 px-2 align-middle">
          <input type="checkbox"
                 checked={selected.has(String(row[rowKey]))}
                 onChange={(e) => {
                   const next = new Set(selected);
                   if (e.target.checked) next.add(String(row[rowKey]));
                   else next.delete(String(row[rowKey]));
                   setSelected(next);
                 }} />
        </td>
      )}
      {columns.map((col) => (
        <td key={col.key} className={`px-3 align-middle ${col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : ""} ${col.frozen ? "sticky left-0 bg-card" : ""}`}
            style={{ width: col.width }}>
          {row[col.key] ?? "—"}
        </td>
      ))}
      {rowActions && rowActions.length > 0 && (
        <td className="w-10 px-2 align-middle">
          <button type="button" className="text-muted-foreground hover:text-foreground" data-row-actions={String(row[rowKey])}>⋯</button>
        </td>
      )}
    </tr>
  );

  return (
    <div ref={scrollRef} className="overflow-auto rounded border border-border bg-card" style={{ maxHeight: shouldVirtualise ? 480 : undefined }}>
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-muted/40 backdrop-blur">
          <tr>
            {selectable && <th className="w-10" />}
            {columns.map((col) => (
              <th key={col.key} className={`px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground ${col.frozen ? "sticky left-0 bg-muted/40 z-10" : ""}`}
                  style={{ width: col.width }}>
                {col.sortable ? (
                  <button type="button" onClick={() => {
                    if (sortBy?.key === col.key) {
                      setSortBy({ key: col.key, dir: sortBy.dir === "asc" ? "desc" : "asc" });
                    } else {
                      setSortBy({ key: col.key, dir: "asc" });
                    }
                  }} className="inline-flex items-center gap-1 hover:text-foreground">
                    {col.label}
                    {sortBy?.key === col.key && (sortBy.dir === "asc" ? " ↑" : " ↓")}
                  </button>
                ) : col.label}
              </th>
            ))}
            {rowActions && rowActions.length > 0 && <th className="w-10" />}
          </tr>
        </thead>
        <tbody>
          {shouldVirtualise ? (
            <>
              <tr style={{ height: virtualiser.getTotalSize() }} />
              {virtualiser.getVirtualItems().map((vi) => (
                <React.Fragment key={vi.key}>{renderRow(sortedRows[vi.index], vi.index)}</React.Fragment>
              ))}
            </>
          ) : (
            sortedRows.map((row, i) => renderRow(row, i))
          )}
        </tbody>
      </table>
    </div>
  );
}
```

NOTE: this is a v1. The next wave can add column-resize, group-by, filter-bar slot, expandable rows, and persisted-saved-views.

- [ ] **Step 4: Export + verify**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true
```

- [ ] **Step 5: Commit**

```bash
git add packages/library/src/components/DataGrid/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/data-display.ts \
        packages/schema/src/index.ts
git commit -m "feat(library): DataGrid v1 — frozen columns, virtualisation, sortable, selectable"
```

---

## Task 5: Timeline

**Files:**
- Create: `packages/library/src/components/Timeline/Timeline.tsx`
- Create: `packages/library/src/components/Timeline/Timeline.schema.ts`
- Modify: `packages/schema/src/nodes/data-display.ts` — append TimelineNode

- [ ] **Step 1: Timeline node**

Append to `packages/schema/src/nodes/data-display.ts`:

```ts
const TimelineEntry = z.object({
  id: z.string(),
  timestamp: z.string(),     // ISO 8601
  actor: z.string().optional(),
  status: z.enum(["pending", "approved", "rejected", "info", "completed"]).optional(),
  title: z.string(),
  detail: z.string().optional(),
});

export const TimelineNode = z.object({
  id: z.string(),
  type: z.literal("Timeline"),
  props: z.object({
    entries: z.array(TimelineEntry),
    orientation: z.enum(["vertical", "horizontal"]).optional(),  // default vertical
  }),
});
```

- [ ] **Step 2: Timeline component**

```tsx
// packages/library/src/components/Timeline/Timeline.tsx
import * as React from "react";
import type { TimelineNode } from "@tentoroforge/schema";
import { z } from "zod";

type Props = z.infer<typeof TimelineNode>["props"];

const STATUS_DOT: Record<string, string> = {
  pending:   "bg-amber-500",
  approved:  "bg-emerald-500",
  rejected:  "bg-rose-500",
  completed: "bg-emerald-500",
  info:      "bg-blue-500",
};

export function Timeline({ entries, orientation = "vertical" }: Props) {
  if (orientation === "horizontal") {
    return (
      <ol className="flex items-start gap-3 overflow-x-auto pb-2">
        {entries.map((e) => (
          <li key={e.id} className="flex-shrink-0 w-48 border-l-2 border-border pl-3">
            <div className={`h-2 w-2 rounded-full ${STATUS_DOT[e.status ?? "info"] ?? STATUS_DOT.info} -ml-4 mb-1`} />
            <p className="text-xs text-muted-foreground">{new Date(e.timestamp).toLocaleString()}</p>
            <p className="text-sm font-medium">{e.title}</p>
            {e.actor && <p className="text-xs text-muted-foreground">{e.actor}</p>}
            {e.detail && <p className="mt-1 text-xs text-muted-foreground">{e.detail}</p>}
          </li>
        ))}
      </ol>
    );
  }
  return (
    <ol className="space-y-3">
      {entries.map((e) => (
        <li key={e.id} className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className={`h-3 w-3 rounded-full ${STATUS_DOT[e.status ?? "info"] ?? STATUS_DOT.info} mt-1.5`} />
            <div className="flex-1 w-px bg-border mt-1" />
          </div>
          <div className="flex-1 pb-3">
            <p className="text-xs text-muted-foreground">{new Date(e.timestamp).toLocaleString()}</p>
            <p className="text-sm font-medium">{e.title}</p>
            {e.actor && <p className="text-xs text-muted-foreground">— {e.actor}</p>}
            {e.detail && <p className="mt-1 text-xs text-muted-foreground">{e.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}
```

- [ ] **Step 3: Schema + export**

```ts
// packages/library/src/components/Timeline/Timeline.schema.ts
import { z } from "zod";
import { TimelineNode } from "@tentoroforge/schema";
export const TimelineProps = TimelineNode.shape.props;
export type TimelinePropsType = z.infer<typeof TimelineProps>;
```

In `packages/library/src/index.ts`:
```ts
export { Timeline } from "./components/Timeline/Timeline";
export { TimelineProps as TimelinePropsSchema } from "./components/Timeline/Timeline.schema";
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

git add packages/library/src/components/Timeline/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/data-display.ts
git commit -m "feat(library): Timeline component — vertical/horizontal status-marked event log"
```

---

## Task 6: Wire NodeV2 union + render-scaffold registry

**Files:**
- Modify: `packages/schema/src/page.ts` — add new nodes to NodeV2 union
- Modify: `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx` — register components

- [ ] **Step 1: NodeV2 union**

Read `packages/schema/src/page.ts`. Find the `NodeV2` discriminated union. Add the 4 new nodes to it:
```ts
import {
  ChartNode, SparklineNode,
} from "./nodes/charts";
import {
  DataGridNode, TimelineNode,
} from "./nodes/data-display";

// Inside the NodeV2 union:
//   z.discriminatedUnion("type", [
//     ...existing,
//     ChartNode,
//     SparklineNode,
//     DataGridNode,
//     TimelineNode,
//   ])
```

- [ ] **Step 2: Render-scaffold registry**

Read the scaffold's `buildRegistry()` function (or its inline `reg(...)` calls). Add:

```tsx
import {
  Chart, Sparkline, DataGrid, Timeline,
  ChartPropsSchema, SparklinePropsSchema, TimelinePropsSchema,
} from "@tentoroforge/library";
import {
  DataGridNode,  // for prop schema
} from "@tentoroforge/schema";

reg("Chart",     Chart,     ChartPropsSchema,         "data");
reg("Sparkline", Sparkline, SparklinePropsSchema,     "data");
reg("DataGrid",  DataGrid,  DataGridNode.shape.props, "data");
reg("Timeline",  Timeline,  TimelinePropsSchema,      "data");
```

- [ ] **Step 3: Verify scaffold boots**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npm run build 2>&1 | tail -5
cd /Users/m/Work/code/poc/design2ui-forge-v3
lsof -ti:6503 | xargs kill -9 2>/dev/null || true
cd apps/render-scaffold && npm run dev > /tmp/scaffold-tier2.log 2>&1 &
sleep 10
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:6503/
lsof -ti:6503 | xargs kill -9 2>/dev/null || true
```

Expected: 200.

- [ ] **Step 4: Commit**

```bash
git add packages/schema/src/page.ts \
        apps/render-scaffold/src/app/p/\[projectId\]/\[...slug\]/page.tsx
git commit -m "feat(scaffold): register Chart/Sparkline/DataGrid/Timeline in NodeV2 + render registry"
```

---

## Task 7: Component playground entries + visual regression baselines

**Files:**
- Modify: `frontend/src/app/(dev-only)/component-playground/page.tsx`
- Modify: `apps/visual-regression/tests/components.spec.ts`

- [ ] **Step 1: Add playground sections**

Append 4 new sections to the playground:

```tsx
// In component-playground/page.tsx (PlaygroundInner client component):
import { Sparkline, Chart, DataGrid, Timeline } from "@tentoroforge/library";

// Section: Sparkline
<section data-component="Sparkline" className={SECTION}>
  <p className={TITLE}>Sparkline</p>
  <div className="flex items-center gap-4">
    <Sparkline data={[2,4,3,7,6,9,8]} color="hsl(221.2 83.2% 53.3%)" />
    <Sparkline data={[10,8,9,5,6,3,2]} color="hsl(0 84.2% 60.2%)" />
    <Sparkline data={[5,5,5,6,5,5,5]} color="hsl(215.4 16.3% 46.9%)" showDots />
  </div>
</section>

// Section: Chart
<section data-component="Chart" className={SECTION}>
  <p className={TITLE}>Chart — line</p>
  <Chart chartType="line" data={[
    {month:"Jan", users:100, revenue:120},
    {month:"Feb", users:150, revenue:180},
    {month:"Mar", users:140, revenue:170},
    {month:"Apr", users:200, revenue:240},
    {month:"May", users:220, revenue:280},
  ]} xKey="month" series={[
    {name:"Users", dataKey:"users"},
    {name:"Revenue", dataKey:"revenue"},
  ]} height={200} />
</section>

// Section: DataGrid
<section data-component="DataGrid" className={SECTION}>
  <p className={TITLE}>DataGrid</p>
  <DataGrid
    columns={[
      {key:"name",       label:"Name",       sortable:true, frozen:true, width:160},
      {key:"department", label:"Department", sortable:true},
      {key:"role",       label:"Role"},
      {key:"status",     label:"Status",     align:"right" as const},
    ]}
    rows={[
      {id:"1", name:"Sarah Chen",     department:"Engineering", role:"Senior Eng",      status:"Active"},
      {id:"2", name:"Marcus Lee",     department:"Engineering", role:"Manager",         status:"Active"},
      {id:"3", name:"Ana Martins",    department:"Design",      role:"Product Designer",status:"On Leave"},
      {id:"4", name:"Kenji Tanaka",   department:"Engineering", role:"Staff Eng",       status:"Active"},
    ]}
    rowKey="id"
    selectable
  />
</section>

// Section: Timeline
<section data-component="Timeline" className={SECTION}>
  <p className={TITLE}>Timeline</p>
  <Timeline entries={[
    {id:"1", timestamp:"2026-05-01T09:00:00Z", actor:"Sarah Chen",   status:"info" as const,
     title:"Submitted leave request"},
    {id:"2", timestamp:"2026-05-01T14:30:00Z", actor:"Marcus Lee (manager)", status:"approved" as const,
     title:"Approved request", detail:"Coverage confirmed via Diego."},
    {id:"3", timestamp:"2026-05-02T10:00:00Z", actor:"HR System",    status:"completed" as const,
     title:"Request finalised + calendar updated"},
  ]} />
</section>
```

- [ ] **Step 2: Add to visual regression spec**

In `apps/visual-regression/tests/components.spec.ts`, append to the COMPONENTS array:
```ts
"Sparkline", "Chart", "DataGrid", "Timeline",
```

- [ ] **Step 3: Capture baselines**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
npm run dev -- -p 6501 > /tmp/frontend-tier2-baseline.log 2>&1 &
sleep 12
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test --grep "Sparkline|Chart|DataGrid|Timeline" --update-snapshots
npx playwright test --grep "Sparkline|Chart|DataGrid|Timeline"   # confirm passing
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: 4 new tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/\(dev-only\)/component-playground/page.tsx \
        apps/visual-regression/tests/
git commit -m "feat(playground): add Sparkline/Chart/DataGrid/Timeline to playground + baselines"
```

---

## Task 8: schema_prompt teaches new components

**Files:**
- Modify: `backend/services/schema_prompt.py`

- [ ] **Step 1: Append component contracts**

Find the existing component contracts block in `schema_prompt.py`. Append a TIER 2 COMPONENTS section:

```python
TIER2_COMPONENTS_GUIDANCE = """
## TIER 2 COMPONENTS (data-heavy enterprise patterns)

  Sparkline { data: number[], width?, height?, color?, showDots? }
    Inline mini-chart. Use INSIDE DataGrid cells, MetricTile trends, or
    dashboard rows where the shape of a trend matters more than exact values.
    NOT a standalone visualisation — wrap in another component.

  Chart { chartType: "line"|"bar"|"area", data: object[], xKey: string,
          series: { name, dataKey, color? }[], height?, showGrid?, showLegend? }
    Full chart with axes/grid/tooltip/legend. Use for dashboard pages and
    reporting pages. Pick line for time-series, bar for comparisons,
    area for cumulative metrics.

  DataGrid { columns: ColumnDef[], rows: object[], rowKey: string,
             virtualise?, selectable?, expandable?, rowActions? }
    For data-heavy pages with > 20 rows. Use INSTEAD OF Table for list pages
    when columns need sorting/freezing/bulk-select. Each column can specify
    sortable, frozen, align, and a custom render component (e.g. render a
    StatusPill for the status column).

  Timeline { entries: TimelineEntry[], orientation?: "vertical"|"horizontal" }
    For audit logs, approval history, activity feeds tied to a single entity.
    Each entry has timestamp + actor + status + title + optional detail.

ANTI-PATTERNS to avoid:
  - Using Table for > 50 rows: use DataGrid (gets virtualisation for free)
  - Using a chart on every page: only dashboard/console/report archetypes
  - Sparkline standalone: always nest inside MetricTile.trend / DataGrid cell
  - Timeline as the primary content of a list page: use DataGrid + Timeline
    in an InspectorPanel for the selected row's history
"""
```

Append `TIER2_COMPONENTS_GUIDANCE` to the prompt builder right after the existing component contracts block.

- [ ] **Step 2: Verify**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_schema_prompt.py -v 2>&1 | tail -10
```

Expected: existing tests still pass.

- [ ] **Step 3: Commit**

```bash
git add backend/services/schema_prompt.py
git commit -m "feat(schema-prompt): teach Tier 2 components + anti-patterns"
```

---

## Task 9: Schema migration corpus + final verification

- [ ] **Step 1: Run migration test**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/integration/test_schema_migration.py -v 2>&1 | tail -10
```

Expected: 17/17 PASS — existing schemas don't use new components, so no parsing changes.

- [ ] **Step 2: Run all backend tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/ -v 2>&1 | tail -15
```

Expected: all PASS.

- [ ] **Step 3: Library build**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npm run build 2>&1 | tail -5
```

- [ ] **Step 4: Bundle-size check**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run build 2>&1 | grep -i "first load\|size" | head -10 || true
```

Note any pages that gained > 50KB. If only Charts/DataGrid pages did (which is correct since they import recharts), that's expected and acceptable.

---

## Self-review

### Spec coverage

| Spec section | Tasks |
|---|---|
| Theme A — Sparkline | 2 |
| Theme A — Chart family | 3 |
| Theme A — DataGrid | 4 |
| Theme A — Timeline | 5 |
| Schema package node definitions | 2, 3, 4, 5 |
| Render-scaffold registration | 6 |
| Playground + visual regression | 7 |
| Schema agent guidance | 8 |
| Migration safety + verification | 9 |

✓ All Wave 1 scope covered.

### Type consistency

- Each new node defined in `packages/schema/src/nodes/{charts,data-display}.ts`
- Each library component re-exports the corresponding zod props as `<Name>Props`
- Render-scaffold registry uses `<Name>Props as <Name>PropsSchema` from library + node-side `.shape.props` for ones not exposed by the library
- All 4 components added to NodeV2 discriminated union

✓ Consistent.

### No placeholders

The DataGrid implementation in Task 4 is intentionally a v1 — the next wave can extend with column-resize, group-by, filter-bar, expandable rows, persisted saved-views. The plan documents this as v1; future tasks can layer.

---

## Out of scope (deferred to Tier 2 Wave 2+)

- **Chart register-aware variants** — colour palette already token-driven; full Workday-tier Chart with custom legend treatment is a follow-up
- **DataGrid advanced features** — column-resize, group-by, expandable rows, filter-bar slot, persisted saved-views (Wave 2)
- **Reference bank re-seed with new components** — Tier 2 Wave 6 (after all components ship)
- **OrgChart** — explicitly out-of-scope per spec; Tier 2.5 if needed
