"use client";

/**
 * The charts on the Insights page, drawn by hand in SVG (no chart library) to one set of rules:
 *
 * - One measure, one axis. Replies and cost are two charts, never one plot with two scales.
 * - Thin marks: columns are at most 24px wide with a 4px rounded top and a square foot on the baseline, lines are 2px, dots are 8px
 *   with a 2px ring in the surface colour, stacked parts are separated by a 2px gap and never by a border.
 * - Axes start at zero and carry a few round numbers; gridlines are solid hairlines; day labels never touch.
 * - Colour is a job: blue is the thing being counted, orange is the second kind of thing (tokens written), red is only for "failed", and
 *   the text is always ink, never the colour of the mark beside it. The two series colours are validated for colour-blind separation.
 * - Hovering (or arrowing along) a day shows ONE tooltip with its value first and its name second; every value is also in the table view
 *   or on a label, so the tooltip never gates anything.
 *
 * Colours are custom properties on `.viz` so a dark theme can swap them in one place. (The app has no dark theme today; the dark values
 * are there for when it does, selected for the dark surface and validated as a pair.)
 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { dayLabel, formatCount, formatDuration, formatMoney, formatTokens, peopleCount } from "@/lib/agent-insights";
import {
  areaOf, columnLayout, compactTick, dayLabelIndexes, lineRuns, moneyTick, niceTicks, pathOf, pointX, shareWidths, type Pt,
} from "@/lib/insights-geometry";

export const VIZ_CSS = `
.viz {
  --viz-surface: #ffffff; --viz-ink: #0b0b0b; --viz-ink-2: #52514e; --viz-muted: #898781;
  --viz-grid: #e1e0d9; --viz-axis: #c3c2b7; --viz-quiet: #c3c2b7;
  --viz-s1: #2a78d6; --viz-s2: #eb6834; --viz-bad: #d03b3b;
  --viz-s1-track: #cde2fb; --viz-bad-track: #f6d6d6;
}
.dark .viz, :root[data-theme="dark"] .viz {
  --viz-surface: #1a1a19; --viz-ink: #f0efec; --viz-ink-2: #c3c2b7; --viz-muted: #898781;
  --viz-grid: #2c2c2a; --viz-axis: #383835; --viz-quiet: #4a4a46;
  --viz-s1: #3987e5; --viz-s2: #d95926; --viz-bad: #d03b3b;
  --viz-s1-track: #1b3350; --viz-bad-track: #4a2323;
}
`;

/** Puts the colour tokens on the page once. */
export function VizStyles() {
  return <style>{VIZ_CSS}</style>;
}

const C = {
  surface: "var(--viz-surface)", ink: "var(--viz-ink)", ink2: "var(--viz-ink-2)", muted: "var(--viz-muted)", grid: "var(--viz-grid)",
  axis: "var(--viz-axis)", quiet: "var(--viz-quiet)", s1: "var(--viz-s1)", s2: "var(--viz-s2)", bad: "var(--viz-bad)",
  s1Track: "var(--viz-s1-track)", badTrack: "var(--viz-bad-track)",
};

// ---------------------------------------------------------------------------
// shared pieces
// ---------------------------------------------------------------------------

/** The width of a box, kept up to date as it is resized. Before it can be measured (or where it cannot, as in tests) it is `fallback`. */
export function useWidth(fallback = 520) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const w = el.getBoundingClientRect().width;
      if (w > 0) setWidth(Math.round(w));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

/**
 * Which day is under the pointer or the keyboard. One tab stop for the whole chart (a ninety-day chart must not be ninety tab stops):
 * arrows move along the days, Home and End jump to the ends, Escape lets go.
 */
function useDayHover(count: number) {
  const [index, setIndex] = useState<number | null>(null);
  const onKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (count === 0) return;
      const at = index ?? count - 1;
      const next = e.key === "ArrowLeft" ? at - 1 : e.key === "ArrowRight" ? at + 1 : e.key === "Home" ? 0 : e.key === "End" ? count - 1 : null;
      if (next !== null) {
        e.preventDefault();
        setIndex(Math.min(count - 1, Math.max(0, next)));
      } else if (e.key === "Escape") setIndex(null);
    },
    [count, index],
  );
  return { index, setIndex, onKeyDown, onFocus: () => setIndex((i) => i ?? count - 1), onBlur: () => setIndex(null) };
}

interface TipRow {
  /** A short stroke of the series colour keys the row. */
  color: string;
  value: string;
  name: string;
}

/** The one tooltip: the value leads in strong ink, the name follows quietly. */
function Tooltip({ anchor, width, title, rows, note }: { anchor: number; width: number; title: string; rows: TipRow[]; note?: string }) {
  const boxW = 188;
  const left = anchor + 14 + boxW > width ? Math.max(4, anchor - 14 - boxW) : anchor + 14;
  return (
    <div
      role="tooltip"
      data-testid="insights-tooltip"
      className="pointer-events-none absolute top-1 z-10 rounded-md border px-2.5 py-1.5 text-xs shadow-md"
      style={{ left, width: boxW, background: C.surface, borderColor: C.grid, color: C.ink }}
    >
      <div className="text-[11px]" style={{ color: C.ink2 }}>{title}</div>
      {rows.map((r) => (
        <div key={r.name} className="mt-1 flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-0.5 w-3 shrink-0 rounded-full" style={{ background: r.color }} />
          <span className="font-semibold">{r.value}</span>
          <span className="whitespace-nowrap" style={{ color: C.ink2 }}>{r.name}</span>
        </div>
      ))}
      {note && <div className="mt-1 text-[11px]" style={{ color: C.ink2 }}>{note}</div>}
    </div>
  );
}

/** A column with a 4px rounded top and a square foot, as a path. */
function columnPath(x: number, y: number, w: number, h: number, rounded: boolean, r = 4): string {
  if (h <= 0 || w <= 0) return "";
  const rr = rounded ? Math.min(r, w / 2, h) : 0;
  return `M${x} ${y + h} L${x} ${y + rr} ${rr ? `Q${x} ${y} ${x + rr} ${y} L${x + w - rr} ${y} Q${x + w} ${y} ${x + w} ${y + rr}` : `L${x + w} ${y}`} L${x + w} ${y + h} Z`;
}

const MARGIN = { left: 34, right: 10, top: 14, bottom: 24 };
const PLOT_H = 140;

export interface DayDatum {
  /** A day (2026-10-21), or for an hour or a minute the start of it: the key of the column. */
  day: string;
  /** What the axis says under it ("Oct 21", "14:00", "10:42"). Without it the day is written out from `day`. */
  label?: string;
  /** A longer name for the tooltip and the screen reader, when one column stands for several buckets ("10:40 to 10:44"). */
  title?: string;
  turns: number;
  errors: number;
  /** Estimated cost for the day, or null when a price is not known. */
  usd: number | null;
}

const labelOf = (d: DayDatum) => d.label ?? dayLabel(d.day);
const titleOf = (d: DayDatum) => d.title ?? labelOf(d);

function Frame({
  width, height, label, children, hover,
}: { width: number; height: number; label: string; children: ReactNode; hover: ReturnType<typeof useDayHover> }) {
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="group"
      aria-label={label}
      tabIndex={0}
      className="block max-w-full overflow-visible outline-none focus-visible:ring-2 focus-visible:ring-sky-400 rounded-sm"
      onKeyDown={hover.onKeyDown}
      onFocus={hover.onFocus}
      onBlur={hover.onBlur}
      onPointerLeave={() => hover.setIndex(null)}
    >
      {children}
    </svg>
  );
}

/** Gridlines, the baseline and the tick numbers of a zero-based axis, plus the day labels under it. */
function Axes({ ticks, top, plotW, days, format }: { ticks: number[]; top: number; plotW: number; days: string[]; format: (n: number) => string }) {
  // "Oct 21, 14:00" is wider than "Oct 21": leave room for the longest label so two never touch.
  const labelW = Math.max(44, Math.ceil(Math.max(0, ...days.map((d) => d.length)) * 5.6) + 4);
  // The first and last labels are tucked in so they stay inside the chart; two labels never touch, so one that would is left out
  // (working from the newest back, which is the one that matters).
  const textW = (i: number) => days[i].length * 5.6;
  const placed: Array<{ i: number; anchor: "start" | "middle" | "end"; left: number }> = [];
  for (const i of [...dayLabelIndexes(days.length, plotW, labelW)].reverse()) {
    const anchor = i === 0 && days.length > 1 ? "start" : i === days.length - 1 && days.length > 1 ? "end" : "middle";
    const x = pointX(i, plotW, days.length);
    const w = textW(i);
    const left = anchor === "end" ? x - w : anchor === "start" ? x : x - w / 2;
    if (placed.length === 0 || left + w + 8 <= placed[placed.length - 1].left) placed.push({ i, anchor, left });
  }
  placed.reverse();
  return (
    <g>
      {ticks.map((t) => {
        const y = MARGIN.top + PLOT_H - (t / (top || 1)) * PLOT_H;
        return (
          <g key={t}>
            <line x1={MARGIN.left} x2={MARGIN.left + plotW} y1={y} y2={y} strokeWidth={1} style={{ stroke: t === 0 ? C.axis : C.grid }} />
            <text x={MARGIN.left - 6} y={y + 3.5} textAnchor="end" fontSize={10} className="tabular-nums" style={{ fill: C.muted }}>
              {format(t)}
            </text>
          </g>
        );
      })}
      {placed.map(({ i, anchor }) => (
        <text
          key={i}
          x={MARGIN.left + pointX(i, plotW, days.length)}
          y={MARGIN.top + PLOT_H + 16}
          textAnchor={anchor}
          fontSize={10}
          style={{ fill: C.muted }}
        >
          {days[i]}
        </text>
      ))}
    </g>
  );
}

// ---------------------------------------------------------------------------
// replies each day: columns
// ---------------------------------------------------------------------------

/**
 * Replies per day as slim columns. A reply that failed is the top part of its day's column, in red, with a 2px gap under it; with no
 * failures at all there is one series, so there is no legend box and the title says what it is. Only the busiest day gets a number on it.
 */
export function ColumnChart({ days, what = "Replies each day", noun = ["reply", "replies"] }: { days: DayDatum[]; what?: string; noun?: [string, string] }) {
  const [ref, width] = useWidth();
  const hover = useDayHover(days.length);
  const plotW = Math.max(60, width - MARGIN.left - MARGIN.right);
  const { ticks, top } = niceTicks(Math.max(0, ...days.map((d) => d.turns)), { integer: true });
  const layout = columnLayout(plotW, days.length);
  const y = (v: number) => MARGIN.top + PLOT_H - (v / top) * PLOT_H;
  const anyFailed = days.some((d) => d.errors > 0);
  const busiest = days.reduce((best, d, i) => (d.turns > (days[best]?.turns ?? -1) ? i : best), 0);
  const h = MARGIN.top + PLOT_H + MARGIN.bottom;
  const over = hover.index !== null ? days[hover.index] : null;
  const summary = `${what}, from ${days[0] ? labelOf(days[0]) : ""} to ${days.length ? labelOf(days[days.length - 1]) : ""}. Use the arrow keys to move along the columns.`;

  return (
    <div ref={ref} className="relative" data-testid="insights-column-chart">
      <Frame width={width} height={h} label={summary} hover={hover}>
        <Axes ticks={ticks} top={top} plotW={plotW} days={days.map(labelOf)} format={compactTick} />
        {hover.index !== null && (
          <rect
            x={MARGIN.left + layout.bandX(hover.index)}
            y={MARGIN.top}
            width={layout.band}
            height={PLOT_H}
            rx={4}
            style={{ fill: C.grid }}
            opacity={0.45}
            aria-hidden="true"
          />
        )}
        {days.map((d, i) => {
          const ok = Math.max(0, d.turns - d.errors);
          const bad = Math.min(d.errors, d.turns);
          const okH = (ok / top) * PLOT_H;
          const badH = (bad / top) * PLOT_H;
          const gap = ok > 0 && bad > 0 ? 2 : 0;
          const x = MARGIN.left + layout.x(i);
          const label = `${titleOf(d)}: ${d.turns} ${d.turns === 1 ? noun[0] : noun[1]}${d.errors ? `, ${d.errors} failed` : ""}`;
          return (
            <g key={`${d.day}-${i}`} data-testid="insights-bar" role="img" aria-label={label}>
              {ok > 0 && <path d={columnPath(x, y(0) - okH, layout.bar, Math.max(2, okH), bad === 0)} style={{ fill: C.s1 }} />}
              {bad > 0 && <path d={columnPath(x, y(0) - okH - gap - badH, layout.bar, Math.max(2, badH), true)} style={{ fill: C.bad }} />}
              <rect
                x={MARGIN.left + layout.bandX(i)}
                y={MARGIN.top}
                width={layout.band}
                height={PLOT_H}
                fill="transparent"
                onPointerEnter={() => hover.setIndex(i)}
                onPointerMove={() => hover.index !== i && hover.setIndex(i)}
              />
            </g>
          );
        })}
        {days[busiest]?.turns > 0 && hover.index === null && (
          <text
            x={MARGIN.left + layout.x(busiest) + layout.bar / 2}
            y={y(days[busiest].turns) - 5}
            textAnchor="middle"
            fontSize={11}
            fontWeight={600}
            data-testid="insights-peak-label"
            style={{ fill: C.ink }}
          >
            {days[busiest].turns}
          </text>
        )}
      </Frame>
      {over && (
        <Tooltip
          anchor={MARGIN.left + layout.x(hover.index!) + layout.bar / 2}
          width={width}
          title={titleOf(over)}
          rows={[
            { color: C.s1, value: String(over.turns), name: over.turns === 1 ? noun[0] : noun[1] },
            ...(over.errors > 0 ? [{ color: C.bad, value: String(over.errors), name: "failed" }] : []),
          ]}
        />
      )}
      {anyFailed && (
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]" style={{ color: C.ink2 }} data-testid="insights-column-legend">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: C.s1 }} />
            {noun[1][0].toUpperCase() + noun[1].slice(1)}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: C.bad }} />
            <AlertTriangle className="h-3 w-3" aria-hidden="true" />
            Replies that failed
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// estimated cost each day: line
// ---------------------------------------------------------------------------

/**
 * Estimated cost per day as a 2px line over a faint wash, with a crosshair and a tooltip that snap to the nearest day. A day with no
 * known price is a gap in the line, never a drop to zero. The latest day carries its value.
 */
export function LineChart({ days, what = "Estimated cost each day" }: { days: DayDatum[]; what?: string }) {
  const [ref, width] = useWidth();
  const hover = useDayHover(days.length);
  const plotW = Math.max(60, width - MARGIN.left - MARGIN.right);
  const values = days.map((d) => d.usd);
  const known = values.filter((v): v is number => v !== null);
  const { ticks, top } = niceTicks(Math.max(0, ...known));
  const runs = lineRuns(values, top, plotW, PLOT_H);
  const h = MARGIN.top + PLOT_H + MARGIN.bottom;
  const lastRun = runs[runs.length - 1];
  const end = lastRun?.[lastRun.length - 1];
  const before = lastRun && lastRun.length > 1 ? lastRun[lastRun.length - 2] : null;
  // The line comes down into the last point: the label goes under the dot. It climbs into it: the label goes above. Never on the line.
  const labelBelow = !!end && !!before && before[1] < end[1] && end[1] + 22 < PLOT_H;
  const lastKnown = known.length ? known[known.length - 1] : null;
  const shift = (p: Pt): Pt => [MARGIN.left + p[0], MARGIN.top + p[1]];
  const over = hover.index !== null ? days[hover.index] : null;
  const overValue = over?.usd ?? null;
  const overX = hover.index !== null ? MARGIN.left + pointX(hover.index, plotW, days.length) : 0;
  const overY = overValue !== null ? MARGIN.top + PLOT_H - (overValue / (top || 1)) * PLOT_H : 0;
  const summary = `${what}, from ${days[0] ? labelOf(days[0]) : ""} to ${days.length ? labelOf(days[days.length - 1]) : ""}. Use the arrow keys to move along the line.`;

  return (
    <div ref={ref} className="relative" data-testid="insights-line-chart">
      <Frame width={width} height={h} label={summary} hover={hover}>
        <Axes ticks={ticks} top={top} plotW={plotW} days={days.map(labelOf)} format={moneyTick} />
        {runs.map((run, i) => {
          const pts = run.map(shift);
          return (
            <g key={i}>
              {pts.length > 1 && <path d={areaOf(pts, MARGIN.top + PLOT_H)} style={{ fill: C.s1 }} opacity={0.1} />}
              <path d={pathOf(pts)} fill="none" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" style={{ stroke: C.s1 }} data-testid="insights-line" />
            </g>
          );
        })}
        {hover.index !== null && (
          <line x1={overX} x2={overX} y1={MARGIN.top} y2={MARGIN.top + PLOT_H} strokeWidth={1} style={{ stroke: C.axis }} aria-hidden="true" />
        )}
        {end && hover.index === null && (
          <g aria-hidden="true">
            <circle cx={MARGIN.left + end[0]} cy={MARGIN.top + end[1]} r={6} style={{ fill: C.surface }} />
            <circle cx={MARGIN.left + end[0]} cy={MARGIN.top + end[1]} r={4} style={{ fill: C.s1 }} />
            {lastKnown !== null && (
              <text
                x={MARGIN.left + end[0] + 6}
                y={MARGIN.top + end[1] + (labelBelow ? 20 : -10)}
                textAnchor="end"
                fontSize={11}
                fontWeight={600}
                data-testid="insights-end-label"
                style={{ fill: C.ink }}
              >
                {formatMoney(lastKnown)}
              </text>
            )}
          </g>
        )}
        {hover.index !== null && overValue !== null && (
          <g aria-hidden="true">
            <circle cx={overX} cy={overY} r={6} style={{ fill: C.surface }} />
            <circle cx={overX} cy={overY} r={4} style={{ fill: C.s1 }} />
          </g>
        )}
        {days.map((d, i) => (
          <rect
            key={`${d.day}-${i}`}
            data-testid="insights-day-hit"
            x={MARGIN.left + (plotW / days.length) * i}
            y={MARGIN.top}
            width={plotW / days.length}
            height={PLOT_H}
            fill="transparent"
            onPointerEnter={() => hover.setIndex(i)}
            onPointerMove={() => hover.index !== i && hover.setIndex(i)}
          />
        ))}
      </Frame>
      {over && (
        <Tooltip
          anchor={overX}
          width={width}
          title={titleOf(over)}
          rows={[{ color: C.s1, value: overValue === null ? "price unknown" : formatMoney(overValue), name: "estimated cost" }]}
          note={`${over.turns} ${over.turns === 1 ? "reply" : "replies"}`}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// small figures: sparkline, meter, speed range
// ---------------------------------------------------------------------------

/**
 * A trend with no axes, in a quiet grey with the latest day in the accent (a dot with a ring), over a faint wash when it is wide enough
 * to be a figure of its own. Decorative: the number beside it says everything it says.
 */
export function Sparkline({ values, height = 32, wide = false }: { values: Array<number | null>; height?: number; wide?: boolean }) {
  const [ref, measured] = useWidth(wide ? 240 : 96);
  const width = wide ? measured : 96;
  const pad = 6;
  const known = values.filter((v): v is number => v !== null);
  const top = Math.max(0, ...known) || 1;
  const runs = lineRuns(values, top, width - pad * 2, height - pad * 2).map((r) => r.map(([x, y]): Pt => [x + pad, y + pad]));
  const last = runs[runs.length - 1]?.slice(-1)[0];
  return (
    <div ref={ref} className={wide ? "w-full" : "w-24 shrink-0"} aria-hidden="true" data-testid="insights-sparkline">
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block max-w-full">
        {runs.length === 0 && <line x1={pad} x2={width - pad} y1={height - pad} y2={height - pad} strokeWidth={1.5} style={{ stroke: C.quiet }} />}
        {runs.map((r, i) => (
          <g key={i}>
            {wide && r.length > 1 && <path d={areaOf(r, height - pad)} style={{ fill: C.s1 }} opacity={0.1} />}
            <path d={pathOf(r)} fill="none" strokeWidth={wide ? 2 : 1.5} strokeLinecap="round" strokeLinejoin="round" style={{ stroke: wide ? C.s1 : C.quiet }} />
          </g>
        ))}
        {last && (
          <g>
            <circle cx={last[0]} cy={last[1]} r={5.5} style={{ fill: C.surface }} />
            <circle cx={last[0]} cy={last[1]} r={3.5} style={{ fill: C.s1 }} />
          </g>
        )}
      </svg>
    </div>
  );
}

/** One ratio as a slim bar: the track is a lighter step of the fill's own colour. Red only when `bad`, which the caller labels in words. */
export function Meter({ pct, bad = false, label }: { pct: number | null; bad?: boolean; label: string }) {
  if (pct === null) return <div className="mt-2 h-1.5 rounded-full" style={{ background: C.s1Track, opacity: 0.5 }} aria-hidden="true" />;
  const clamped = Math.min(100, Math.max(0, pct));
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped)}
      className="mt-2 h-1.5 overflow-hidden rounded-full"
      style={{ background: bad ? C.badTrack : C.s1Track }}
      data-testid="insights-meter"
    >
      <div className="h-full rounded-full" style={{ width: `${clamped > 0 ? Math.max(2, clamped) : 0}%`, background: bad ? C.bad : C.s1 }} />
    </div>
  );
}

/**
 * Where the typical reply and the slowest 1 in 20 sit on a time scale, with the 30 second line marked. Labelled in words underneath so
 * nothing depends on the colours or on hovering.
 */
export function SpeedRange({ p50Ms, p95Ms, limitMs = 30_000 }: { p50Ms: number; p95Ms: number; limitMs?: number }) {
  const [ref, width] = useWidth(160);
  const max = Math.max(limitMs * 1.08, p95Ms * 1.15, 1);
  const x = (ms: number) => 8 + (Math.min(ms, max) / max) * (width - 16);
  const slow = p95Ms > limitMs;
  return (
    <div ref={ref} className="mt-2" data-testid="insights-speed-range">
      <svg width={width} height={28} viewBox={`0 0 ${width} 28`} className="block max-w-full" role="img" aria-label={`Typical ${formatDuration(p50Ms)}, slowest 1 in 20 ${formatDuration(p95Ms)}, limit ${formatDuration(limitMs)}`}>
        <rect x={8} y={14} width={width - 16} height={6} rx={3} style={{ fill: C.s1Track }} />
        <rect x={8} y={14} width={Math.max(0, x(p95Ms) - 8)} height={6} rx={3} style={{ fill: C.s1 }} opacity={0.35} />
        <line x1={x(limitMs)} x2={x(limitMs)} y1={9} y2={25} strokeWidth={1.5} style={{ stroke: slow ? C.bad : C.axis }} />
        <text x={x(limitMs)} y={7} textAnchor="end" fontSize={9} style={{ fill: C.muted }}>{formatDuration(limitMs)}</text>
        <circle cx={x(p95Ms)} cy={17} r={6} style={{ fill: C.surface }} />
        <circle cx={x(p95Ms)} cy={17} r={4} style={{ fill: C.ink2 }} />
        <circle cx={x(p50Ms)} cy={17} r={6} style={{ fill: C.surface }} />
        <circle cx={x(p50Ms)} cy={17} r={4} style={{ fill: C.s1 }} />
      </svg>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px]" style={{ color: C.ink2 }}>
        <span className="inline-flex items-center gap-1">
          <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: C.s1 }} />
          Typical {formatDuration(p50Ms)}
        </span>
        <span className="inline-flex items-center gap-1">
          <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: C.ink2 }} />
          Slowest 1 in 20: {formatDuration(p95Ms)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// where the cost goes: one bar of shares, and the tools
// ---------------------------------------------------------------------------

/**
 * What the tokens were spent on: what the assistant read (its instructions, the history, what tools returned) against what it wrote.
 * One bar of two shares with a 2px gap, labelled underneath with the numbers and the share, so a very small share is still named.
 */
export function TokenSplit({ inputTokens, outputTokens }: { inputTokens: number; outputTokens: number }) {
  const [ref, width] = useWidth(480);
  const total = inputTokens + outputTokens;
  const [a, b] = shareWidths([inputTokens, outputTokens], width);
  // One decimal at both ends (1.2% and 98.8%) so the two shares still add up to a hundred; whole numbers in between.
  const share = (n: number) => {
    if (total <= 0) return "0%";
    const pct = (n / total) * 100;
    return `${pct < 10 || pct > 90 ? Math.round(pct * 10) / 10 : Math.round(pct)}%`;
  };
  return (
    <div ref={ref} data-testid="insights-token-split">
      <div className="flex h-3 w-full gap-0.5" role="img" aria-label={`Read by the assistant ${formatTokens(inputTokens)} (${share(inputTokens)}), written by the assistant ${formatTokens(outputTokens)} (${share(outputTokens)})`}>
        {a > 0 && <div className="h-full rounded-l-full" style={{ width: a, background: C.s1, borderTopRightRadius: b > 0 ? 2 : 999, borderBottomRightRadius: b > 0 ? 2 : 999 }} />}
        {b > 0 && <div className="h-full rounded-r-full" style={{ width: b, background: C.s2, borderTopLeftRadius: a > 0 ? 2 : 999, borderBottomLeftRadius: a > 0 ? 2 : 999 }} />}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs" style={{ color: C.ink2 }}>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: C.s1 }} />
          <span>Read by the assistant</span>
          <span className="font-semibold tabular-nums" style={{ color: C.ink }}>{formatTokens(inputTokens)}</span>
          <span className="tabular-nums">{share(inputTokens)}</span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: C.s2 }} />
          <span>Written by the assistant</span>
          <span className="font-semibold tabular-nums" style={{ color: C.ink }}>{formatTokens(outputTokens)}</span>
          <span className="tabular-nums">{share(outputTokens)}</span>
        </span>
      </div>
    </div>
  );
}

export interface ToolDatum {
  name: string;
  calls: number;
  errors: number;
  avgMs: number | null;
}

/**
 * Calls per tool as horizontal bars, busiest first: the part that failed is the end of the bar, in red, after a 2px gap. The number sits
 * at the tip; how many failed and how long a call takes are in the words beside it, so nothing relies on colour or hover alone.
 */
export function ToolBars({ tools }: { tools: ToolDatum[] }) {
  const [ref, width] = useWidth(520);
  const [over, setOver] = useState<number | null>(null);
  const max = Math.max(1, ...tools.map((t) => t.calls));
  const nameW = Math.min(180, Math.max(110, width * 0.32));
  const tailW = 150;
  const numW = 36; // room for the number at the tip of the longest bar
  const barMax = Math.max(40, width - nameW - tailW - numW - 28);
  return (
    <div ref={ref} className="relative space-y-2.5" data-testid="insights-tool-bars">
      {tools.map((t, i) => {
        const failed = Math.min(t.errors, t.calls);
        const full = (t.calls / max) * barMax;
        const badW = failed > 0 ? Math.max(3, (failed / t.calls) * full) : 0;
        const okW = Math.max(0, full - badW - (failed > 0 && failed < t.calls ? 2 : 0));
        const label = `${t.name}: ${t.calls} ${t.calls === 1 ? "call" : "calls"}${failed ? `, ${failed} failed` : ""}${t.avgMs !== null ? `, about ${formatDuration(t.avgMs)} each` : ""}`;
        return (
          <div
            key={t.name}
            className="flex items-center gap-3 rounded-sm"
            role="img"
            aria-label={label}
            data-testid="insights-tool-bar"
            onPointerEnter={() => setOver(i)}
            onPointerLeave={() => setOver(null)}
            style={{ background: over === i ? "color-mix(in srgb, var(--viz-grid) 45%, transparent)" : undefined }}
          >
            <span className="shrink-0 truncate font-mono text-[11px]" style={{ width: nameW, color: C.ink }} title={t.name}>{t.name}</span>
            <span className="flex shrink-0 items-center" style={{ width: barMax + numW }}>
              <span className="flex h-3 items-center gap-0.5">
                {okW > 0 && <span className="h-3" style={{ width: okW, background: C.s1, borderRadius: failed > 0 ? "0 0 0 0" : "0 4px 4px 0" }} />}
                {badW > 0 && <span className="h-3" style={{ width: badW, background: C.bad, borderRadius: "0 4px 4px 0" }} />}
              </span>
              <span className="ml-2 text-xs font-semibold tabular-nums" style={{ color: C.ink }}>{t.calls}</span>
            </span>
            <span className="flex shrink-0 items-center gap-1.5 text-[11px]" style={{ width: tailW, color: C.ink2 }}>
              {failed > 0 ? (
                <>
                  <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden="true" style={{ color: C.bad }} />
                  <span>{failed} failed</span>
                </>
              ) : (
                <span>{t.avgMs !== null ? `${formatDuration(t.avgMs)} each` : ""}</span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// who is using it: one bar of shares, and usage by role
// ---------------------------------------------------------------------------

export interface SharePart {
  name: string;
  value: number;
  /** Blue for the thing counted, orange for the second kind of thing. */
  tone: "s1" | "s2";
}

/**
 * Two (or more) shares of one whole as ONE stacked bar, parts separated by a 2px gap, never a pie. Every part is named underneath with
 * its number and its share, so a very thin part is still read and nothing depends on the colours. Used for new against returning people.
 */
export function ShareBar({ parts, label, approximate = false }: { parts: SharePart[]; label: string; approximate?: boolean }) {
  const [ref, width] = useWidth(480);
  const total = parts.reduce((a, p) => a + Math.max(0, p.value), 0);
  const widths = shareWidths(parts.map((p) => p.value), width);
  const share = (n: number) => {
    if (total <= 0) return "0%";
    const pct = (n / total) * 100;
    return `${pct < 10 || pct > 90 ? Math.round(pct * 10) / 10 : Math.round(pct)}%`;
  };
  const color = (t: SharePart["tone"]) => (t === "s1" ? C.s1 : C.s2);
  // The outer ends of the bar are round, the ends that meet the gap are nearly square.
  const first = widths.findIndex((w) => w > 0);
  const last = widths.length - 1 - [...widths].reverse().findIndex((w) => w > 0);
  return (
    <div ref={ref} data-testid="insights-share-bar">
      <div
        className="flex h-3 w-full gap-0.5"
        role="img"
        aria-label={`${label}: ${parts.map((p) => `${p.name} ${peopleCount(p.value, approximate)} (${share(p.value)})`).join(", ")}`}
      >
        {total <= 0 && <div className="h-full w-full rounded-full" style={{ background: C.s1Track }} />}
        {parts.map((p, i) =>
          widths[i] > 0 ? (
            <div
              key={p.name}
              className="h-full"
              style={{
                width: widths[i], background: color(p.tone),
                borderRadius: `${i === first ? 999 : 2}px ${i === last ? 999 : 2}px ${i === last ? 999 : 2}px ${i === first ? 999 : 2}px`,
              }}
            />
          ) : null,
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs" style={{ color: C.ink2 }}>
        {parts.map((p) => (
          <span key={p.name} className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color(p.tone) }} />
            <span>{p.name}</span>
            <span className="font-semibold tabular-nums" style={{ color: C.ink }}>{peopleCount(p.value, approximate)}</span>
            <span className="tabular-nums">{share(p.value)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export interface RoleDatum {
  role: string;
  users: number;
  turns: number;
  usd: number | null;
  thumbsDownPct: number | null;
}

/** The words under a role's bar: who they are, what they cost (an estimate) and how often they were let down. */
export function roleWords(r: RoleDatum, approximate: boolean): string {
  const people = `${peopleCount(r.users, approximate)} ${r.users === 1 && !approximate ? "person" : "people"}`;
  const thumbs = r.thumbsDownPct === null ? "no ratings yet" : `${r.thumbsDownPct >= 10 ? Math.round(r.thumbsDownPct) : Math.round(r.thumbsDownPct * 10) / 10}% thumbs down`;
  return `${people}, estimated cost ${formatMoney(r.usd)}, ${thumbs}`;
}

/**
 * Replies by role as horizontal bars, busiest first: one measure (replies) on the bar and its number at the tip; the people, the cost
 * estimate and the thumbs-down share are in the words under the role, never only in a tooltip or a colour. Widths are percentages, so
 * it fits any width without measuring.
 */
export function RoleBars({ roles, approximate = false }: { roles: RoleDatum[]; approximate?: boolean }) {
  const [over, setOver] = useState<number | null>(null);
  const max = Math.max(1, ...roles.map((r) => r.turns));
  return (
    <div className="space-y-3" data-testid="insights-role-bars">
      {roles.map((r, i) => {
        const words = roleWords(r, approximate);
        return (
          <div
            key={`${r.role}-${i}`}
            role="img"
            aria-label={`${r.role}: ${formatCount(r.turns)} ${r.turns === 1 ? "reply" : "replies"}, ${words}`}
            data-testid="insights-role-bar"
            className="rounded-sm"
            onPointerEnter={() => setOver(i)}
            onPointerLeave={() => setOver(null)}
            style={{ background: over === i ? "color-mix(in srgb, var(--viz-grid) 45%, transparent)" : undefined }}
          >
            <div className="flex items-center gap-3">
              <span className="w-24 shrink-0 truncate text-xs sm:w-40" style={{ color: C.ink }} title={r.role}>{r.role}</span>
              <span className="flex min-w-0 flex-1 items-center">
                <span className="h-3 shrink-0" style={{ width: `calc(${(r.turns / max) * 100}% - 64px)`, minWidth: r.turns > 0 ? 2 : 0, background: C.s1, borderRadius: "0 4px 4px 0" }} />
                <span className="ml-2 w-14 shrink-0 text-xs font-semibold tabular-nums" style={{ color: C.ink }}>{formatCount(r.turns)}</span>
              </span>
            </div>
            <div className="mt-0.5 pl-[6.75rem] text-[11px] sm:pl-[10.75rem]" style={{ color: C.ink2 }}>{words}</div>
          </div>
        );
      })}
    </div>
  );
}
