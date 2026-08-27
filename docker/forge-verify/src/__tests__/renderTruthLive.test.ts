import { describe, it, expect } from "vitest";
import { classifyRenderTruth } from "../renderTruth";

// Counts read out of the LIVE q941voiw dashboard with the probe's own
// selectors, before and after the recharts/React-19 fix landed. This is the
// regression that justifies the whole module.
describe("live q941voiw dashboard", () => {
  it("is clean after the recharts fix", () => {
    expect(classifyRenderTruth({
      charts: 1, chartMarks: 3, chartsEmptyState: 0,
      tables: 1, tableRows: 10, tablesEmptyState: 0,
      metrics: 4, metricsBlank: 0,
    })).toEqual([]);
  });

  it("would have caught the blank chart before it", () => {
    // Measured earlier: three <g class="recharts-bar-rectangle"> containing
    // no <path>, so the .recharts-rectangle count was 0 while axes, data and
    // every upstream gate were green.
    const f = classifyRenderTruth({
      charts: 1, chartMarks: 0, chartsEmptyState: 0,
      tables: 1, tableRows: 10, tablesEmptyState: 0,
      metrics: 4, metricsBlank: 0,
    });
    expect(f.map((x) => x.rule)).toEqual(["chart_draws_nothing"]);
  });
});
