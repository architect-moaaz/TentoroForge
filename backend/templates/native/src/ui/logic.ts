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

// ---- a bottom sheet over a map ----------------------------------------------------------------------------------------

/** A sheet's resting heights, ascending, in points. A number of 1 or less is a share of `room` (the height there is to
 *  fill), anything more is points; none may be under `floor` or over `room`, and a repeat is dropped. */
export function sheetHeights(snaps: number[], room: number, floor = 72): number[] {
  const out = snaps
    .map((s) => (s <= 1 ? s * room : s))
    .map((h) => Math.round(Math.min(Math.max(h, floor), Math.max(room, floor))))
    .sort((a, b) => a - b);
  return out.filter((h, i) => i === 0 || h !== out[i - 1]);
}

/** Where a sheet comes to rest when the finger lifts: `shown` is how much of it is showing, `velocity` is the
 *  finger's speed in points per millisecond (positive is downward). A flick carries it on in its direction;
 *  a slow drag goes to the nearest resting height. Returns the index into `heights`. */
export function settleSheet(shown: number, velocity: number, heights: number[]): number {
  if (heights.length === 0) return 0;
  const aimed = shown - velocity * 220;
  let best = 0;
  for (let i = 1; i < heights.length; i++) {
    if (Math.abs(heights[i] - aimed) < Math.abs(heights[best] - aimed)) best = i;
  }
  return best;
}

/** A drag, held inside the sheet's own range: it can be pulled a little past the ends (it gives), never off. */
export function dragShown(start: number, dy: number, heights: number[], give = 24): number {
  if (heights.length === 0) return start;
  const lo = heights[0], hi = heights[heights.length - 1];
  const raw = start - dy;
  if (raw < lo) return lo - Math.min(give, (lo - raw) / 4);
  if (raw > hi) return hi + Math.min(give, (raw - hi) / 4);
  return raw;
}

// ---- clocks ---------------------------------------------------------------------------------------------------------------

/** `m:ss` for a time left (never negative). */
export function countdownText(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const s = total % 60;
  return `${Math.floor(total / 60)}:${s < 10 ? "0" : ""}${s}`;
}

/** The milliseconds from `now` to an ISO time (negative once it has passed); null when there is no time. */
export function msUntil(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : t - now;
}

/** How long ago something began, in words a glance can take: `just now`, `12 min`, `1 h 5 min`. */
export function elapsedText(ms: number): string {
  const min = Math.max(0, Math.floor(ms / 60000));
  if (min < 1) return "just now";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60), m = min % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}
