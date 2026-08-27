import { z } from "zod";

export const SparklineNode = z.object({
  id: z.string().optional(),
  type: z.literal("Sparkline"),
  props: z.object({
    data: z.array(z.number()).min(2),
    width:  z.number().optional(),     // default 100
    height: z.number().optional(),     // default 24
    color:  z.string().optional(),     // CSS color or token path
    showDots: z.boolean().optional(),  // default false
  }),
});

const ChartSeries = z.object({
  name: z.string(),
  dataKey: z.string(),
  color: z.string().optional(),
});

// Slice A / Chart anatomy — the toggle chip that swaps a series
// modifier at runtime. Renderer emits a segmented button group in
// the chart header; each toggle carries a modifier the runtime can
// apply to widen/narrow the current series set (swap group-by field,
// swap window). Kept opaque here — the runtime consumes it.
const ChartViewToggle = z.object({
  label: z.string().min(1),
  modifier: z.record(z.unknown()).optional(),
  default: z.boolean().optional(),
});

export const ChartNode = z.object({
  id: z.string().optional(),
  type: z.literal("Chart"),
  props: z.object({
    chartType: z.enum(["line", "bar", "area", "pie", "donut", "funnel", "radar"]),
    // Either an inline array of row objects OR a Mustache binding string
    // like `"{{stats.dailyUsers}}"` that the runtime resolves to a real
    // array. Same pattern as Form-C: schema accepts both shapes; the
    // renderer is responsible for binding resolution.
    // data / series are frequently null in generated schemas — they're bound
    // at runtime. Coerce null/undefined → [] so the chart renders (empty) in
    // the editor instead of "⚠ invalid props". (data: [] is a valid array;
    // series: [] drops the .min(1) requirement for unbound charts.)
    data: z.preprocess(
      (v) => (v == null ? [] : v),
      z.union([
        z.array(z.record(z.union([z.string(), z.number()]))),
        z.string().min(1),
      ]),
    ),
    xKey: z.string().optional(),
    series: z.preprocess((v) => (v == null ? [] : v), z.array(ChartSeries)),
    height: z.number().optional(),
    showGrid: z.boolean().optional(),
    showLegend: z.boolean().optional(),
    showTooltip: z.boolean().optional(),
    // ── Slice A / Chart anatomy (2026-08-15) ─────────────────────────
    // All optional. Missing = today's render.
    //
    // title / help — header row. The renderer emits a chart header with
    // the title on the left and a small "?" affordance on the right
    // whose hover reveals `help` text. Composer authors both from the
    // maquette's ``title`` + ``help``.
    title: z.string().optional(),
    help: z.string().optional(),
    // overlay — a SECONDARY chart type + series bound to the SAME x/y
    // axes as the primary. The renderer draws it on top so a bar chart
    // can carry a smoothed line overlay (Banking "Transactions Yearly").
    // Only two encodings coexist; more would need a stacked legend.
    overlay: z.object({
      chartType: z.enum(["line", "bar", "area"]),
      data: z.preprocess(
        (v) => (v == null ? [] : v),
        z.union([
          z.array(z.record(z.union([z.string(), z.number()]))),
          z.string().min(1),
        ]),
      ),
      series: z.preprocess((v) => (v == null ? [] : v), z.array(ChartSeries)),
      curve: z.enum(["straight", "smooth"]).optional(),
    }).optional(),
    // encoding — visual grammar switches. `leaderboard` swaps the layout
    // for a ranked horizontal bar with value annotations at the row end
    // (the Banking "Transactions Across Merchant State" shape).
    // `stacked`, `sorted`, `topN`, `valueLabels` are Recharts flags the
    // renderer forwards.
    encoding: z.object({
      leaderboard:  z.boolean().optional(),
      stacked:      z.boolean().optional(),
      sorted:       z.enum(["asc", "desc"]).optional(),
      topN:         z.number().int().positive().optional(),
      valueLabels:  z.boolean().optional(),
    }).optional(),
    // viewToggles — chart-header segmented-button group. Each toggle
    // is a runtime modifier the renderer swaps into the current query
    // (e.g. Time Trend / Year Trend, Amount / #Number). The FIRST
    // toggle with ``default: true`` (or index 0 when none flagged) is
    // active on mount.
    viewToggles: z.array(ChartViewToggle).optional(),
    // semanticColor — cross-widget color consistency. When set, the
    // renderer overrides series colors by the value of ``field`` on
    // each row (pink = female EVERYWHERE, green = pass, red = risk).
    // Composer authors ``map`` from the maquette so the same domain
    // enum lands the same color on every chart on the page.
    semanticColor: z.object({
      by:    z.literal("field"),
      field: z.string().min(1),
      map:   z.record(z.string()),
    }).optional(),
  }),
});

// Radial KPI gauge with optional colored threshold zones + needle.
export const GaugeNode = z.object({
  id: z.string().optional(),
  type: z.literal("Gauge"),
  props: z.object({
    value: z.number().default(0),
    min: z.number().optional(),
    max: z.number().optional(),
    label: z.string().optional(),
    unit: z.string().optional(),
    thresholds: z.array(z.object({ value: z.number(), color: z.string(), label: z.string().optional() })).optional(),
    size: z.number().optional(),
    showValue: z.boolean().optional(),
    bind: z.string().optional(),
  }),
});

// Matrix heatmap — flat cells [{x,y,value}] with per-cell colour intensity.
export const HeatmapNode = z.object({
  id: z.string().optional(),
  type: z.literal("Heatmap"),
  props: z.object({
    data: z.preprocess((v) => (v == null ? [] : v),
      z.union([z.array(z.record(z.unknown())), z.string().min(1)])),
    xKey: z.string().optional(),
    yKey: z.string().optional(),
    valueKey: z.string().optional(),
    rows: z.array(z.string()).optional(),
    columns: z.array(z.string()).optional(),
    color: z.string().optional(),
    min: z.number().optional(),
    max: z.number().optional(),
    showValues: z.boolean().optional(),
    cellSize: z.number().optional(),
    bind: z.string().optional(),
  }),
});

// Self-contained SVG floor/zone/route map (markers + regions + grid).
const SchematicMarkerNode = z.object({
  id: z.string().optional(), x: z.number(), y: z.number(),
  label: z.string().optional(), status: z.string().optional(),
  color: z.string().optional(), shape: z.enum(["circle", "square", "pin"]).optional(),
});
const SchematicRegionNode = z.object({
  id: z.string().optional(), label: z.string().optional(),
  x: z.number().optional(), y: z.number().optional(), w: z.number().optional(), h: z.number().optional(),
  points: z.array(z.array(z.number())).optional(), color: z.string().optional(),
});
export const SchematicNode = z.object({
  id: z.string().optional(),
  type: z.literal("Schematic"),
  props: z.object({
    width: z.number().optional(),
    height: z.number().optional(),
    grid: z.object({ cols: z.number(), rows: z.number() }).optional(),
    regions: z.array(SchematicRegionNode).optional(),
    markers: z.preprocess((v) => (v == null ? [] : v),
      z.union([z.array(SchematicMarkerNode), z.string().min(1)])),
    statusColors: z.record(z.string()).optional(),
    showLabels: z.boolean().optional(),
    heightPx: z.number().optional(),
    bind: z.string().optional(),
  }),
});
