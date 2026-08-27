import { describe, it, expect } from "vitest";
import {
  classifyRenderTruth,
  emptyWidgetCounts,
  type WidgetCounts,
} from "../renderTruth";

function counts(partial: Partial<WidgetCounts>): WidgetCounts {
  return { ...emptyWidgetCounts(), ...partial };
}

const rules = (c: WidgetCounts) => classifyRenderTruth(c).map((f) => f.rule);

describe("classifyRenderTruth", () => {
  it("flags a chart that rendered but drew no marks", () => {
    // The q941voiw case verbatim: one recharts wrapper, populated axes, three
    // <g class="recharts-bar-rectangle"> containing no <path> at all.
    expect(rules(counts({ charts: 1, chartMarks: 0 })))
      .toEqual(["chart_draws_nothing"]);
  });

  it("stays quiet when the chart drew marks", () => {
    expect(rules(counts({ charts: 1, chartMarks: 3 }))).toEqual([]);
  });

  it("treats an empty state as an honest answer, not a fault", () => {
    // A first-run app legitimately has nothing to plot. Saying so is correct
    // behaviour and must not be punished, or the gate teaches people to fake
    // data rather than write empty states.
    expect(rules(counts({ charts: 1, chartMarks: 0, chartsEmptyState: 1 })))
      .toEqual([]);
  });

  it("still flags when only SOME charts explain themselves", () => {
    expect(rules(counts({ charts: 2, chartMarks: 0, chartsEmptyState: 1 })))
      .toEqual(["chart_draws_nothing"]);
  });

  it("flags a table with no rows and no empty state", () => {
    expect(rules(counts({ tables: 1, tableRows: 0 })))
      .toEqual(["table_no_rows_no_empty_state"]);
  });

  it("accepts a table that rendered its empty state", () => {
    expect(rules(counts({ tables: 1, tableRows: 0, tablesEmptyState: 1 })))
      .toEqual([]);
  });

  it("accepts a table with rows", () => {
    expect(rules(counts({ tables: 1, tableRows: 10 }))).toEqual([]);
  });

  it("flags KPI tiles that rendered a label but no value", () => {
    // Live case: MetricTile without the required `format` prop renders the
    // label and nothing else.
    const f = classifyRenderTruth(counts({ metrics: 4, metricsBlank: 4 }));
    expect(f.map((x) => x.rule)).toEqual(["metric_value_blank"]);
    expect(f[0].detail).toContain("4 of 4");
  });

  it("accepts KPI tiles that rendered values", () => {
    expect(rules(counts({ metrics: 4, metricsBlank: 0 }))).toEqual([]);
  });

  it("reports every independent failure on one page", () => {
    expect(
      rules(counts({
        charts: 1, chartMarks: 0,
        tables: 1, tableRows: 0,
        metrics: 3, metricsBlank: 2,
      })),
    ).toEqual([
      "chart_draws_nothing",
      "table_no_rows_no_empty_state",
      "metric_value_blank",
    ]);
  });

  it("says nothing about a page carrying none of these widgets", () => {
    // A form page has no charts, tables or tiles. Absence is not a fault —
    // that is the dashboard floor's job, on dashboards only.
    expect(rules(emptyWidgetCounts())).toEqual([]);
  });
});
