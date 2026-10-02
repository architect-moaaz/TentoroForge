"use client";

// packages/library/src/components/Chart/EChart.tsx
//
// Mounts one ECharts instance on a canvas and keeps it in step with its props,
// its box and the page's theme. Only the chart types the library draws are
// registered, so an app ships the ECharts core plus those — not the whole of it.

import * as React from "react";
import * as echarts from "echarts/core";
import {
  BarChart, LineChart, PieChart, FunnelChart, RadarChart, ScatterChart, HeatmapChart, TreemapChart,
  SunburstChart, GraphChart, MapChart,
} from "echarts/charts";
import {
  GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, AriaComponent, GeoComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { ChartPropsType } from "./Chart.schema";
import {
  buildChartOption, DEFAULT_THEME, PALETTE_DARK, PALETTE_LIGHT, SEQUENTIAL_DARK, SEQUENTIAL_LIGHT,
  type ChartTheme,
} from "./chartOption";

echarts.use([
  BarChart, LineChart, PieChart, FunnelChart, RadarChart, ScatterChart, HeatmapChart, TreemapChart,
  SunburstChart, GraphChart, MapChart,
  GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, AriaComponent, GeoComponent,
  CanvasRenderer,
]);

// The world's outlines are a quarter-megabyte ECharts does not ship; they are
// fetched the first time a map chart mounts and registered once per page.
let worldReady: Promise<void> | null = null;
function ensureWorldMap(): Promise<void> {
  if (echarts.getMap("world")) return Promise.resolve();
  worldReady ??= import("./maps/world.json").then((mod) => {
    if (!echarts.getMap("world")) echarts.registerMap("world", (mod.default ?? mod) as any);
  });
  return worldReady;
}

/** What a click on a mark says: the category (axis value, slice, cell column),
 *  the series it belongs to, its value, and — for a cell — the row value. */
export interface ChartSelection {
  category: string;
  series: string | null;
  value: number | null;
}

// A canvas cannot read `var(--primary)`, and ECharts' own colour parser does
// not take the space-separated `hsl(222 47% 11%)` form, so every token is
// resolved to a comma form before it reaches the option.
function cssColor(raw: string): string | null {
  const v = raw.trim();
  if (!v) return null;
  // shadcn tokens are bare triplets: "222 47% 11%" (optionally "/ 0.5").
  const m = v.match(/^(-?[\d.]+)(?:deg)?\s+([\d.]+%)\s+([\d.]+%)(?:\s*\/\s*([\d.]+%?))?$/);
  if (m) return m[4] ? `hsla(${m[1]}, ${m[2]}, ${m[3]}, ${m[4]})` : `hsl(${m[1]}, ${m[2]}, ${m[3]})`;
  const f = v.match(/^hsla?\(\s*(-?[\d.]+)(?:deg)?[\s,]+([\d.]+%)[\s,]+([\d.]+%)(?:\s*[/,]\s*([\d.]+%?))?\s*\)$/);
  if (f) return f[4] ? `hsla(${f[1]}, ${f[2]}, ${f[3]}, ${f[4]})` : `hsl(${f[1]}, ${f[2]}, ${f[3]})`;
  if (/^#|^rgb|^hsl/i.test(v)) return v;
  return null;
}

function lightnessOf(raw: string): number | null {
  const m = raw.trim().match(/([\d.]+)%\s*\)?\s*$/);
  return m ? Number(m[1]) : null;
}

export function resolveChartTheme(el: Element | null): ChartTheme {
  if (!el || typeof window === "undefined") return DEFAULT_THEME;
  const cs = window.getComputedStyle(el);
  const tok = (name: string) => cs.getPropertyValue(name);
  const bgRaw = tok("--card") || tok("--background");
  const light = lightnessOf(bgRaw);
  const dark = light !== null ? light < 50 : false;
  const base = dark ? PALETTE_DARK : PALETTE_LIGHT;
  // An app's own chart tokens take their slots; the rest stay the reference's.
  const palette = base.map((c, i) => cssColor(tok(`--chart-${i + 1}`)) ?? c);
  return {
    palette,
    sequential: dark ? SEQUENTIAL_DARK : SEQUENTIAL_LIGHT,
    surface: cssColor(bgRaw) ?? (dark ? "#1a1a19" : "#ffffff"),
    text: cssColor(tok("--foreground")) ?? (dark ? "#ffffff" : "#0b0b0b"),
    textMuted: cssColor(tok("--muted-foreground")) ?? (dark ? "#c3c2b7" : "#52514e"),
    grid: cssColor(tok("--border")) ?? (dark ? "#383835" : "#e5e7eb"),
    fontFamily: cs.fontFamily || undefined,
    dark,
  };
}

/** Re-resolve the theme when the page's theme changes (a `.dark` class, a
 *  `data-theme` stamp, an inline token override, or the OS setting). */
function useChartTheme(ref: React.RefObject<HTMLDivElement | null>): ChartTheme {
  const [theme, setTheme] = React.useState<ChartTheme>(DEFAULT_THEME);
  React.useEffect(() => {
    const update = () => setTheme(resolveChartTheme(ref.current));
    update();
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme", "style"] });
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener?.("change", update);
    return () => { mo.disconnect(); mq?.removeEventListener?.("change", update); };
  }, [ref]);
  return theme;
}

export interface EChartProps extends ChartPropsType {
  onSelect?: (selection: ChartSelection) => void;
  className?: string;
}

export function EChart({ onSelect, className, ...props }: EChartProps) {
  const ref = React.useRef<HTMLDivElement | null>(null);
  const chart = React.useRef<echarts.ECharts | null>(null);
  const theme = useChartTheme(ref);
  const onSelectRef = React.useRef(onSelect);
  onSelectRef.current = onSelect;

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let inst: echarts.ECharts;
    try {
      inst = echarts.init(el, undefined, { renderer: "canvas" });
    } catch (err) {
      // No canvas (a test DOM, a locked-down browser): the page keeps its
      // box and the rest of the screen, rather than failing with the chart.
      console.warn("[Chart] could not start a canvas:", err);
      return;
    }
    chart.current = inst;
    inst.on("click", (p: any) => {
      const cb = onSelectRef.current;
      if (!cb) return;
      const category = p.seriesType === "heatmap" && Array.isArray(p.value)
        ? String((inst.getOption() as any).xAxis?.[0]?.data?.[p.value[0]] ?? "")
        : p.seriesType === "graph" && p.dataType === "edge"
          ? `${p.data?.source ?? ""} → ${p.data?.target ?? ""}`
          : String(p.name ?? "");
      const raw = Array.isArray(p.value) ? p.value[p.value.length - 1] : p.value;
      cb({ category, series: p.seriesName ?? null, value: typeof raw === "number" ? raw : null });
    });
    const ro = new ResizeObserver(() => inst.resize());
    ro.observe(el);
    return () => { ro.disconnect(); inst.dispose(); chart.current = null; };
  }, []);

  const option = React.useMemo(() => buildChartOption(props as ChartPropsType, theme),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(props), theme]);

  // A map waits for its outlines; every other chart draws at once.
  const [worldLoaded, setWorldLoaded] = React.useState(false);
  const needsWorld = props.chartType === "map";
  React.useEffect(() => {
    if (!needsWorld || worldLoaded) return;
    let live = true;
    ensureWorldMap().then(() => { if (live) setWorldLoaded(true); })
      .catch((err) => console.warn("[Chart] could not load the world map:", err));
    return () => { live = false; };
  }, [needsWorld, worldLoaded]);

  React.useEffect(() => {
    if (needsWorld && !worldLoaded) return;
    try {
      chart.current?.setOption(option as echarts.EChartsCoreOption, { notMerge: true });
    } catch (err) {
      // A chart that cannot draw its data leaves its box empty; it does not
      // take the page with it.
      console.warn("[Chart] could not draw:", err);
    }
    if (ref.current) ref.current.style.cursor = onSelect ? "pointer" : "";
  }, [option, onSelect, needsWorld, worldLoaded]);

  return (
    <div
      ref={ref}
      className={className}
      role="img"
      aria-label={props.title ?? `${props.chartType} chart`}
      data-chart-type={props.chartType}
      style={{ width: "100%", height: props.height ?? 240 }}
    />
  );
}
