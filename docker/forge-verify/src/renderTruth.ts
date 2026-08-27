// Render truth — did a widget that is PRESENT actually draw anything?
//
// Why this exists
// ---------------
// `countWidgets` answers "how much stuff is on this page", and every gate in
// the pipeline is downstream of that kind of question: does the schema declare
// a chart, does the component exist, does the dataSource resolve. All of those
// were green for the bar chart on q941voiw, which shipped drawing zero bars —
// correct data, correct axes, three <g class="recharts-bar-rectangle"> elements
// containing nothing at all. Recharts 2.15's entry animation goes through
// react-smooth, which does not survive React 19, so the rectangle group mounts
// and renders null. Nothing in the pipeline looked at whether a mark was drawn,
// so it shipped, in every generated app, for as long as React 19 has been in
// the template.
//
// The distinction that makes this worth having
// --------------------------------------------
// "Zero rows" is not a fault. A first-run app legitimately has empty tables and
// empty charts — that is what the empty states are for. The fault is zero marks
// AND no empty state: the widget claims a slot on the page, occupies its
// height, and communicates nothing.
//
// That distinction is only decidable if empty states identify themselves, which
// is why the library now stamps `data-forge-empty` on the branches that render
// one. Inferring it from prose would be guessing, and a gate that guesses gets
// switched off.
//
// Shape: the browser collects counts (see probeRenderTruth in runners.ts) and
// this module decides. Keeping the judgement pure is what makes it testable
// without a browser — the counts are trivial, the rules are where mistakes
// live.

export interface WidgetCounts {
  /** Chart containers on the page (recharts wrappers). */
  charts: number;
  /** Plotted marks across every chart — bars, line points, areas, sectors. */
  chartMarks: number;
  /** Chart containers that rendered their own empty state. */
  chartsEmptyState: number;

  /** Table elements on the page. */
  tables: number;
  /** Body rows across every table. */
  tableRows: number;
  /** Tables that rendered their own empty state. */
  tablesEmptyState: number;

  /** KPI tiles on the page. */
  metrics: number;
  /** KPI tiles whose value slot rendered no text at all. */
  metricsBlank: number;
}

export interface RenderTruthFinding {
  rule:
    | "chart_draws_nothing"
    | "table_no_rows_no_empty_state"
    | "metric_value_blank";
  detail: string;
}

export function emptyWidgetCounts(): WidgetCounts {
  return {
    charts: 0, chartMarks: 0, chartsEmptyState: 0,
    tables: 0, tableRows: 0, tablesEmptyState: 0,
    metrics: 0, metricsBlank: 0,
  };
}

/**
 * Findings for one rendered page. Empty array means every widget that claims
 * a slot is actually saying something.
 */
export function classifyRenderTruth(c: WidgetCounts): RenderTruthFinding[] {
  const out: RenderTruthFinding[] = [];

  // A chart with no marks and no empty state is a hole in the page wearing a
  // chart's clothes. `chartsEmptyState` covers the honest case.
  if (c.charts > 0 && c.chartMarks === 0 && c.chartsEmptyState < c.charts) {
    out.push({
      rule: "chart_draws_nothing",
      detail:
        `${c.charts} chart(s) rendered, 0 plotted marks, ` +
        `${c.chartsEmptyState} empty state(s). The chart occupies its slot ` +
        `and communicates nothing — axes can be populated while the series ` +
        `draws null.`,
    });
  }

  if (c.tables > 0 && c.tableRows === 0 && c.tablesEmptyState < c.tables) {
    out.push({
      rule: "table_no_rows_no_empty_state",
      detail:
        `${c.tables} table(s) rendered, 0 body rows, ` +
        `${c.tablesEmptyState} empty state(s). Zero rows is fine; zero rows ` +
        `with nothing telling the user why is not.`,
    });
  }

  // Blank KPIs are the MetricTile version of the same failure — the tile
  // renders, the label renders, the number is missing. Seen live when the
  // schema omitted a required `format` prop.
  if (c.metricsBlank > 0) {
    out.push({
      rule: "metric_value_blank",
      detail:
        `${c.metricsBlank} of ${c.metrics} KPI tile(s) rendered a label but ` +
        `no value. A tile with no number is a caption for nothing.`,
    });
  }

  return out;
}
