// PLACEHOLDER of the generated `src/sdk/widgets.ts` — not copied into apps. The
// real one is `emit_widgets` in services/blueprint/app_sdk.py (identical to the
// web app's): the analytics the Blueprint attaches to pages.
import type { EntityName } from "./schema";

export type WidgetUnit = "number" | "currency" | "percent" | "duration" | "date" | "text";
export type ChartMark = "bar" | "line" | "area" | "pie" | "donut" | "funnel" | "radar" | "scatter" | "heatmap" | "treemap" | "sunburst" | "graph" | "map";
export type WidgetSource =
  | { op: "query"; entity: EntityName;
      measures: readonly { key: string; label?: string; aggregation: "count" | "count_distinct" | "sum" | "avg" | "min" | "max"; field?: string }[];
      dimensions: readonly { field: string; bucket?: "day" | "week" | "month" | "quarter" | "year";
                             ranges?: readonly { label?: string; from?: number; to?: number }[] }[];
      filter: Readonly<Record<string, unknown>>; timeField?: string;
      sort?: { by: string; order?: "asc" | "desc" }; limit?: number }
  | { op: "list"; entity: EntityName; fields: readonly string[];
      filter: Readonly<Record<string, unknown>>; sort?: string; limit: number };

/** An analytic the Blueprint attaches to a page. */
export interface WidgetRef {
  id: string;
  page: string;
  label: string;
  description?: string;
  kind: "metric" | "chart" | "list" | "table" | "feed" | "gauge" | "text";
  unit: WidgetUnit;
  size?: "sm" | "md" | "lg" | "full";
  chart?: { mark: ChartMark; stacked?: boolean; horizontal?: boolean };
  source: WidgetSource;
}

export const widgets = {
  openTasks: {
    id: "WID-001", page: "PAGE-001", label: "Open tasks", kind: "metric", unit: "number",
    source: { op: "query", entity: "Task", measures: [{ key: "value", aggregation: "count" }], dimensions: [], filter: { status: "open" } },
  } as const satisfies WidgetRef,
} as const;
