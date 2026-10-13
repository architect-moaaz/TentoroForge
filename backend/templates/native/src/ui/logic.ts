// The component kit — the parts of it that are arithmetic and naming, not
// drawing, so they run (and are tested) under plain node. A component draws what
// these decide: which tone a status is, how tall a bar is, where a line's
// segment lies, what a widget's rows become on a chart's axes.
//
// PURE — no react-native import.

import { humanize } from "../sdk/format";
import type { QueryRow } from "../sdk/reads";
import type { WidgetRef } from "../sdk/widgets";

export type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "accent";

const TONES: [Tone, RegExp][] = [
  ["success", /^(done|complete|completed|paid|approved|active|success|succeeded|delivered|resolved|verified|accepted|confirmed|in stock|live|published|passed|ok)$/],
  ["danger", /^(failed|failure|rejected|declined|cancelled|canceled|overdue|blocked|error|expired|denied|refunded|out of stock|suspended|lost|critical|high)$/],
  ["warning", /^(pending|review|in review|draft|waiting|on hold|paused|scheduled|partial|partially paid|low|low stock|at risk|medium|awaiting.*)$/],
  ["info", /^(open|new|in progress|processing|started|submitted|shipped|in transit|assigned|queued|running)$/],
];

/** A status word's colour family: green for done, red for gone wrong, amber for
 *  waiting, blue for moving. Words it does not know are neutral — a status
 *  colour is a claim, and the kit does not guess one. */
export function statusTone(status: string | null | undefined): Tone {
  const s = String(status ?? "").trim().toLowerCase().replace(/[_-]+/g, " ");
  for (const [tone, re] of TONES) if (re.test(s)) return tone;
  return "neutral";
}

/** "Ada Lovelace" -> "AL"; one word -> its first letter; nothing -> "?". */
export function initials(name: string | null | undefined): string {
  const words = String(name ?? "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  const letters = words.length === 1 ? [words[0][0]] : [words[0][0], words[words.length - 1][0]];
  return letters.join("").toUpperCase();
}

/** 0.12 -> "▲ 12%", -0.05 -> "▼ 5%" (a change as a fraction of what it was). */
export function deltaText(delta: number | null | undefined): { text: string; direction: "up" | "down" | "flat" } | null {
  if (delta === null || delta === undefined || !Number.isFinite(delta)) return null;
  const pct = Math.round(Math.abs(delta) * 1000) / 10;
  if (pct === 0) return { text: "0%", direction: "flat" };
  return delta > 0 ? { text: `▲ ${pct}%`, direction: "up" } : { text: `▼ ${pct}%`, direction: "down" };
}

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------

export interface ChartSeries { name: string; values: number[] }
export interface ChartData { labels: string[]; series: ChartSeries[] }

const num = (v: unknown): number => {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
};

/** The columns a row shows: a foreign key's name (`<field>Label`) in place of
 *  its id, and never the row's own id. */
export function shownKeys(row: QueryRow | undefined): string[] {
  if (!row) return [];
  return Object.keys(row)
    .filter((k) => k !== "id" && !(k.endsWith("Label") && k.slice(0, -5) in row))
    .map((k) => (`${k}Label` in row ? `${k}Label` : k));
}

/** The chart a widget draws by default: its own `chart.mark`, else a line for a
 *  date-bucketed axis and bars otherwise — reduced to what SimpleChart draws
 *  (marks it has no drawing for are bars). */
export function chartKind(widget: WidgetRef): "bar" | "line" | "pie" {
  const src = widget.source;
  const mark = widget.chart?.mark ?? (src.op === "query" && src.dimensions[0]?.bucket ? "line" : "bar");
  if (mark === "line" || mark === "area") return "line";
  if (mark === "pie" || mark === "donut") return "pie";
  return "bar";
}

/** A foreign key's NAME, never its id, on an axis: a breakdown by a key comes
 *  back with the record's name beside the id (`<field>Label`). */
function named(field: string | undefined, row: QueryRow | undefined): string | undefined {
  return field && row && `${field}Label` in row ? `${field}Label` : field;
}

/** What a chart widget's rows become: labels along the axis and one series per
 *  measure — or, with a second dimension, one series per value of it (the
 *  split), for the first measure. Order of first appearance is kept. */
export function chartData(widget: WidgetRef, rows: QueryRow[]): ChartData {
  const src = widget.source;
  if (src.op !== "query") return { labels: [], series: [] };
  const dims = src.dimensions;
  const axis = named(dims[0]?.field, rows[0]);
  const label = (r: QueryRow) => {
    const v = axis ? r[axis] : undefined;
    return v === null || v === undefined || v === "" ? "—" : String(v);
  };
  if (dims.length >= 2 && src.measures[0]) {
    const split = named(dims[1].field, rows[0]) as string;
    const measure = src.measures[0].key;
    const labels: string[] = [];
    const names: string[] = [];
    for (const r of rows) {
      if (!labels.includes(label(r))) labels.push(label(r));
      const n = r[split] === null || r[split] === undefined ? "—" : String(r[split]);
      if (!names.includes(n)) names.push(n);
    }
    const series = names.map((name) => ({
      name,
      values: labels.map((l) => rows.filter((r) => label(r) === l && String(r[split] ?? "—") === name).reduce((sum, r) => sum + num(r[measure]), 0)),
    }));
    return { labels, series };
  }
  return {
    labels: rows.map(label),
    series: src.measures.map((m) => ({ name: m.label ?? humanize(m.key), values: rows.map((r) => num(r[m.key])) })),
  };
}

/** The largest value a chart's axis must reach (never 0: an empty chart has no divide-by-zero). */
export function axisMax(series: ChartSeries[]): number {
  let max = 0;
  for (const s of series) for (const v of s.values) if (v > max) max = v;
  return max > 0 ? max : 1;
}

/** A bar's height in points: its share of the axis, at least 2 for a non-zero
 *  value (so a small one is still visible) and 0 for zero or less. */
export function barHeight(value: number, max: number, height: number): number {
  if (!(value > 0) || !(max > 0)) return 0;
  return Math.max(2, Math.round((value / max) * height));
}

export interface Segment {
  /** Centre of the segment, for a View positioned by its centre. */
  cx: number;
  cy: number;
  length: number;
  /** Radians, for `rotate`. */
  angle: number;
}

/** The points of a line chart in a `width` x `height` box (y grows downward) and
 *  the segments that join them. One value is a single point, no segments. */
export function linePoints(values: number[], max: number, width: number, height: number): { points: { x: number; y: number }[]; segments: Segment[] } {
  const n = values.length;
  const points = values.map((v, i) => ({
    x: n === 1 ? width / 2 : (i / (n - 1)) * width,
    y: height - (max > 0 ? Math.max(0, v) / max : 0) * height,
  }));
  const segments = points.slice(1).map((p, i) => {
    const a = points[i];
    const dx = p.x - a.x, dy = p.y - a.y;
    return { cx: (a.x + p.x) / 2, cy: (a.y + p.y) / 2, length: Math.hypot(dx, dy), angle: Math.atan2(dy, dx) };
  });
  return { points, segments };
}

/** Shares for a pie / donut: each positive value's percentage of the total
 *  (one decimal), summing to 100 give or take rounding. Zero or negative values
 *  have no share. An all-zero chart has none at all. */
export function shares(values: number[]): number[] {
  const total = values.reduce((s, v) => s + (v > 0 ? v : 0), 0);
  return values.map((v) => (total > 0 && v > 0 ? Math.round((v / total) * 1000) / 10 : 0));
}
