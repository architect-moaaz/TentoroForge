/**
 * The arithmetic behind the Insights charts: tick marks, bar sizes, which day the pointer is over, and the path of a line. No React,
 * no drawing, so it can be tested on its own.
 *
 * The drawing rules these serve (the data-visualisation guidance the charts follow): bars are thin (never fill their slot), lines are
 * 2px, the axis starts at zero with a few round tick values, and a pointer anywhere over a day's column picks that day.
 */

/** A round step (1, 2, 2.5 or 5 times a power of ten) that fits about `target` steps into `max`. */
function niceStep(max: number, target: number): number {
  const raw = max / Math.max(1, target);
  const power = Math.pow(10, Math.floor(Math.log10(raw)));
  const unit = raw / power;
  const nice = unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10;
  return nice * power;
}

export interface Ticks {
  /** From 0 up to `top`, evenly spaced, round numbers. */
  ticks: number[];
  /** The top of the axis: the last tick, never below the biggest value. */
  top: number;
}

/**
 * Tick values for an axis that starts at zero. `integer` keeps counts whole (a "2.5 replies" tick means nothing); an empty or
 * all-zero series still gets a small axis rather than a flat line at the bottom.
 */
export function niceTicks(max: number, opts: { target?: number; integer?: boolean } = {}): Ticks {
  const target = opts.target ?? 4;
  const biggest = Number.isFinite(max) && max > 0 ? max : opts.integer ? 4 : 1;
  let step = niceStep(biggest, target);
  if (opts.integer) step = Math.max(1, Math.ceil(step));
  const top = Math.ceil(biggest / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= top + step * 1e-6; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return { ticks, top };
}

/** 0, 500, 1.2K, 3M: short tick text for counts. */
export function compactTick(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e6) return `${trim(n / 1e6)}M`;
  if (abs >= 1e3) return `${trim(n / 1e3)}K`;
  return trim(n);
}

/** $0, $0.05, $1.20, $12: dollar tick text, keeping the cents a small axis needs and dropping them from big ones. */
export function moneyTick(usd: number): string {
  if (usd === 0) return "$0";
  if (usd >= 100) return `$${Math.round(usd)}`;
  if (usd >= 10) return `$${trim(usd)}`;
  if (usd >= 1) return `$${usd.toFixed(2).replace(/0$/, "")}`;
  return `$${usd.toFixed(2)}`;
}

function trim(n: number): string {
  return String(Math.round(n * 100) / 100);
}

export interface ColumnLayout {
  /** The width of one day's band: where the pointer is "over" that day. */
  band: number;
  /** The bar inside it: thin, centred, never wider than `maxBar`. */
  bar: number;
  /** Left edge of the bar for day `i`. */
  x(i: number): number;
  /** Left edge of the band for day `i`. */
  bandX(i: number): number;
}

/**
 * Where each day's column goes. The bar is at most `maxBar` wide and leaves a gap each side, so a week gets a few slim columns and
 * ninety days get thin ones, and the leftover room is air.
 */
export function columnLayout(width: number, count: number, maxBar = 24, gap = 2): ColumnLayout {
  const n = Math.max(1, count);
  const band = Math.max(1, width) / n;
  const bar = Math.max(2, Math.min(maxBar, band - gap * 2));
  return { band, bar, x: (i) => band * i + (band - bar) / 2, bandX: (i) => band * i };
}

/** Which of `count` equal bands the pointer is over (x in pixels from the left of the plot), clamped to the ends. */
export function nearestBand(x: number, width: number, count: number): number {
  if (count <= 0 || width <= 0) return 0;
  return Math.min(count - 1, Math.max(0, Math.floor((x / width) * count)));
}

/** The point of day `i` on a line chart: the middle of its band, so lines and columns line up when drawn together. */
export function pointX(i: number, width: number, count: number): number {
  return ((i + 0.5) / Math.max(1, count)) * width;
}

export type Pt = [number, number];

/**
 * The runs of a line, split where a value is unknown (null): a day with no price is a gap, never a drop to zero.
 * `value` is in data units, `top` is the axis top, `h` the plot height in pixels.
 */
export function lineRuns(values: Array<number | null>, top: number, width: number, h: number): Pt[][] {
  const runs: Pt[][] = [];
  let cur: Pt[] = [];
  values.forEach((v, i) => {
    if (v === null || !Number.isFinite(v)) {
      if (cur.length) runs.push(cur);
      cur = [];
      return;
    }
    cur.push([pointX(i, width, values.length), h - (Math.max(0, v) / (top || 1)) * h]);
  });
  if (cur.length) runs.push(cur);
  return runs;
}

/** An SVG path through the points. */
export function pathOf(points: Pt[]): string {
  return points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${round(x)} ${round(y)}`).join(" ");
}

/** The same path closed down to the baseline: the wash under a line. */
export function areaOf(points: Pt[], baseline: number): string {
  if (points.length === 0) return "";
  const first = points[0];
  const last = points[points.length - 1];
  return `${pathOf(points)} L${round(last[0])} ${round(baseline)} L${round(first[0])} ${round(baseline)} Z`;
}

const round = (n: number) => Math.round(n * 100) / 100;

/**
 * Which day labels go under the axis: the latest day, then every `step` days back from it, with `step` the smallest number that keeps
 * two labels at least `minGap` pixels apart. Even spacing counted back from today reads calmly; forcing both ends in as well gave
 * labels 4, 7 and 4 days apart. Seven days or fewer usually label every day.
 */
export function dayLabelIndexes(count: number, width: number, labelWidth = 44, minGap = 12): number[] {
  if (count <= 0) return [];
  if (count === 1) return [0];
  const band = Math.max(1, width) / count;
  const step = Math.max(1, Math.ceil((labelWidth + minGap) / band));
  const out: number[] = [];
  for (let i = count - 1; i >= 0; i -= step) out.push(i);
  return out.reverse();
}

/** Shares of a whole as pixel widths with a gap between neighbours, so a tiny share is still seen and nothing overlaps. */
export function shareWidths(values: number[], total: number, gap = 2, min = 3): number[] {
  const parts = values.filter((v) => v > 0).length;
  if (parts === 0 || total <= 0) return values.map(() => 0);
  const free = Math.max(0, total - gap * (parts - 1));
  const sum = values.reduce((a, b) => a + Math.max(0, b), 0) || 1;
  const raw = values.map((v) => (v > 0 ? Math.max(min, (v / sum) * free) : 0));
  const over = raw.reduce((a, b) => a + b, 0) - free;
  if (over > 0) {
    // a segment held up to its minimum took space from the rest: take it back from the biggest
    const big = raw.indexOf(Math.max(...raw));
    raw[big] = Math.max(min, raw[big] - over);
  }
  return raw;
}
