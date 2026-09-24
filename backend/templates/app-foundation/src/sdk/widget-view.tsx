"use client";
// The app SDK — drawing a widget. A widget is an analytic the Blueprint
// attaches to a page: its query (measures by dimensions) and how it is drawn.
// `load.ts` reads it with `runWidget(widgets.x)`; the view hands the result
// here, and the encoding follows from the query's own shape, so a chart
// cannot be drawn against columns its data does not have.

import * as React from "react";
import { Table2, BarChart3 } from "lucide-react";
import { Chart, MetricTile, Gauge, DataGrid, type ChartSelection } from "@tentoroforge/library";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { WidgetRef } from "./widgets";

type Row = Record<string, string | number | null>;

/** What `runWidget` returned (from "@/sdk/server"). */
export interface WidgetViewData {
  rows: Row[];
  value: number | null;
  /** A metric read over a range: its change against the period before (0.12 = up 12%). */
  previous?: number | null;
  delta?: number | null;
}

type Format = "number" | "currency" | "percent" | "duration";

function formatOf(unit: WidgetRef["unit"]): Format {
  return unit === "currency" || unit === "percent" || unit === "duration" ? unit : "number";
}

function humanize(key: string): string {
  return key.replace(/Label$/, "").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ")
    .replace(/^./, (c) => c.toUpperCase());
}

function formatCell(v: unknown, format: Format, currency: string): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v !== "number") return String(v);
  if (format === "currency") return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(v);
  if (format === "percent") return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 }).format(v);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(v);
}

/** The Chart props a query-backed widget draws with. */
export function chartPropsFor(widget: WidgetRef, rows: Row[], currency = "USD") {
  const src = widget.source;
  if (src.op !== "query") return null;
  const dims = src.dimensions;
  const ms = src.measures;
  const mark = widget.chart?.mark ?? (dims[0]?.bucket ? "line" : "bar");
  const series = ms.map((m) => ({ name: m.label ?? humanize(m.key), dataKey: m.key }));
  const base = {
    chartType: mark,
    data: rows,
    series,
    format: formatOf(widget.unit),
    currency,
    encoding: { stacked: widget.chart?.stacked, horizontal: widget.chart?.horizontal },
  };
  // NAMES, NEVER IDS — on an axis too. A breakdown by a foreign key comes
  // back with the record's name beside the id (`<field>Label`, from the data
  // engine and the editor's sample server alike); the axis reads the name.
  // "Most administered vaccines" was labelled sample-vaccine-3 (2026-09-24).
  const named = (field?: string) => (field && rows.length && `${field}Label` in rows[0] ? `${field}Label` : field);
  if (mark === "scatter") {
    return { ...base, xKey: ms[0]?.key, yKey: ms[1]?.key, sizeKey: ms[2]?.key,
             labelKey: named(dims[0]?.field), colorKey: named(dims[1]?.field) };
  }
  if (mark === "heatmap" || mark === "graph") {
    // The heatmap's column and row; the graph's link start and end.
    return { ...base, xKey: named(dims[0]?.field), yKey: named(dims[1]?.field), valueKey: ms[0]?.key };
  }
  return { ...base, xKey: named(dims[0]?.field) ?? "label", colorKey: named(dims[1]?.field), valueKey: ms[0]?.key };
}

/** A gauge without a declared maximum reads against the next round number. */
function niceCeiling(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 5, 10].map((m) => m * p).find((c) => c >= v) ?? 10 * p;
}

/** The columns a row shows: a foreign key's name (`<field>Label`) in place of
 *  its id, and never the row's own id. */
function shownKeys(row: Row | undefined): string[] {
  if (!row) return [];
  return Object.keys(row)
    .filter((k) => k !== "id" && !(k.endsWith("Label") && k.slice(0, -5) in row))
    .map((k) => (`${k}Label` in row ? `${k}Label` : k));
}

function DataTable({ rows, format, currency }: { rows: Row[]; format: Format; currency: string }) {
  if (!rows.length) return <p className="py-8 text-center text-sm text-muted-foreground">No data for this period yet</p>;
  const keys = shownKeys(rows[0]);
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-card">
          <tr className="border-b">
            {keys.map((k) => (
              <th key={k} className={`py-2 pr-3 font-medium text-muted-foreground ${typeof rows[0][k] === "number" ? "text-right" : "text-left"}`}>
                {humanize(k)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b last:border-0">
              {keys.map((k) => (
                <td key={k} className={`py-1.5 pr-3 ${typeof r[k] === "number" ? "text-right tabular-nums" : ""}`}>
                  {formatCell(r[k], format, currency)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface WidgetViewProps {
  widget: WidgetRef;
  /** What `runWidget(widget)` returned in `load.ts`. */
  data: WidgetViewData | null | undefined;
  /** Chart height in px (default 260). */
  height?: number;
  /** ISO 4217 code for a currency widget (default USD). */
  currency?: string;
  /** A click on a mark: drill into a filtered list, or filter the page. */
  onSelect?: (selection: ChartSelection) => void;
  /** Something for the card's header — a "View all" link, a period picker. */
  action?: React.ReactNode;
  className?: string;
}

/** Draws one widget as the Blueprint declares it: a KPI tile, a gauge, a
 *  chart (with a table view for the numbers behind it) or a list. */
export function WidgetView({ widget, data, height = 260, currency = "USD", onSelect, action, className }: WidgetViewProps) {
  const [asTable, setAsTable] = React.useState(false);
  const rows = data?.rows ?? [];
  const format = formatOf(widget.unit);

  if (widget.kind === "metric") {
    const delta = data?.delta;
    return (
      <div className={className}>
        <MetricTile label={widget.label} value={data?.value ?? (null as unknown as number)} format={format}
                    {...(delta != null && Number.isFinite(delta)
                      ? { delta: { value: Math.abs(delta), direction: delta >= 0 ? "up" : "down" } } : {})} />
      </div>
    );
  }

  let body: React.ReactNode;
  let toggle = false;
  if (widget.kind === "gauge") {
    const v = data?.value ?? 0;
    body = (
      <div className="flex justify-center py-2">
        {format === "percent"
          ? <Gauge value={Math.round(v * 1000) / 10} min={0} max={100} unit="%" label={widget.label} />
          : <Gauge value={v} min={0} max={niceCeiling(v)} label={widget.label} />}
      </div>
    );
  } else if (widget.kind === "text") {
    body = <p className="text-2xl font-semibold tabular-nums">{formatCell(data?.value ?? rows[0]?.[Object.keys(rows[0] ?? {})[0]], format, currency)}</p>;
  } else if (widget.kind === "chart" && widget.source.op === "query") {
    toggle = true;
    const props = chartPropsFor(widget, rows, currency);
    body = asTable || !props
      ? <DataTable rows={rows} format={format} currency={currency} />
      : <Chart {...(props as React.ComponentProps<typeof Chart>)} height={height} onSelect={onSelect} />;
  } else {
    const keys = shownKeys(rows[0]);
    body = rows.length
      ? <DataGrid columns={keys.slice(0, 6).map((k) => ({ key: k, label: humanize(k) }))}
                  rows={rows as Record<string, unknown>[]} rowKey="id" />
      : <p className="py-8 text-center text-sm text-muted-foreground">Nothing here yet</p>;
  }

  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0 pb-2">
        <div className="min-w-0">
          <CardTitle className="text-sm font-medium">{widget.label}</CardTitle>
          {widget.description ? <CardDescription className="mt-1 text-xs">{widget.description}</CardDescription> : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {action}
          {toggle && rows.length > 0 ? (
            <Button variant="ghost" size="icon" className="h-7 w-7" aria-pressed={asTable}
                    aria-label={asTable ? "Show chart" : "Show as table"} onClick={() => setAsTable((t) => !t)}>
              {asTable ? <BarChart3 className="h-4 w-4" /> : <Table2 className="h-4 w-4" />}
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  );
}
