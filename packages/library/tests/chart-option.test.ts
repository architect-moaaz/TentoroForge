import { describe, it, expect } from "vitest";
import { buildChartOption, formatValue, DEFAULT_THEME, MAX_SERIES } from "../src/components/Chart/chartOption";
import type { ChartPropsType } from "../src/components/Chart/Chart.schema";

const props = (p: Partial<ChartPropsType>): ChartPropsType =>
  ({ chartType: "bar", data: [], series: [], ...p }) as ChartPropsType;

const opt = (p: Partial<ChartPropsType>) => buildChartOption(props(p)) as any;

describe("buildChartOption — cartesian", () => {
  it("draws the series shape a query returns: {label, value}", () => {
    const o = opt({ data: [{ label: "OPEN", value: 4 }, { label: "DONE", value: 9 }], xKey: "label",
                    series: [{ name: "Cases", dataKey: "value" }] });
    expect(o.xAxis.data).toEqual(["OPEN", "DONE"]);
    expect(o.series[0]).toMatchObject({ type: "bar", data: [4, 9], barMaxWidth: 24 });
    expect(o.legend).toBeUndefined(); // one series: the title names it
  });

  it("pivots long-format rows into one series per split value", () => {
    const data = [
      { month: "2026-01", status: "OPEN", count: 2 },
      { month: "2026-01", status: "DONE", count: 5 },
      { month: "2026-02", status: "OPEN", count: 3 },
    ];
    const o = opt({ chartType: "line", data, xKey: "month", colorKey: "status",
                    series: [{ name: "Cases", dataKey: "count" }] });
    expect(o.xAxis.data).toEqual(["2026-01", "2026-02"]);
    expect(o.series.map((s: any) => s.name)).toEqual(["OPEN", "DONE"]);
    expect(o.series[0].data).toEqual([2, 3]);
    expect(o.series[1].data).toEqual([5, 0]);
    expect(o.legend.data).toEqual(["OPEN", "DONE"]);
    expect(o.series[0].lineStyle.width).toBe(2);
  });

  it("colours by the palette's fixed order, never cycled — the ninth series folds into Other", () => {
    const data = Array.from({ length: 11 }, (_, i) => ({ x: "a", g: `g${i}`, v: 11 - i }));
    const o = opt({ data, xKey: "x", colorKey: "g", series: [{ name: "v", dataKey: "v" }] });
    expect(o.series).toHaveLength(MAX_SERIES);
    expect(o.series.at(-1).name).toBe("Other");
    expect(o.series.at(-1).data).toEqual([1 + 2 + 3 + 4]);
    expect(o.series.slice(0, 7).map((s: any) => s.itemStyle.color)).toEqual(DEFAULT_THEME.palette.slice(0, 7));
  });

  it("keeps an entity's colour when a filter removes a neighbour", () => {
    const both = opt({ data: [{ x: "a", g: "EU", v: 1 }, { x: "a", g: "US", v: 2 }], xKey: "x", colorKey: "g",
                       series: [{ name: "v", dataKey: "v" }], semanticColor: { by: "field", field: "g", map: { US: "#123456" } } });
    const one = opt({ data: [{ x: "a", g: "US", v: 2 }], xKey: "x", colorKey: "g",
                      series: [{ name: "v", dataKey: "v" }], semanticColor: { by: "field", field: "g", map: { US: "#123456" } } });
    expect(both.series[1].itemStyle.color).toBe("#123456");
    expect(one.series[0].itemStyle.color).toBe("#123456");
  });

  it("stacks, rounds only the top segment, and runs bars horizontally when asked", () => {
    const data = [{ x: "a", p: 1, q: 2 }];
    const o = opt({ data, xKey: "x", series: [{ name: "P", dataKey: "p" }, { name: "Q", dataKey: "q" }],
                    encoding: { stacked: true, horizontal: true } });
    expect(o.series.every((s: any) => s.stack === "total")).toBe(true);
    expect(o.series[0].itemStyle.borderRadius).toBe(0);
    expect(o.series[1].itemStyle.borderRadius).toEqual([0, 4, 4, 0]);
    expect(o.yAxis.type).toBe("category");
    expect(o.xAxis.type).toBe("value");
  });

  it("reads a foreign key's name, not its id", () => {
    const o = opt({ data: [{ customerId: "c-1", customerIdLabel: "Acme", value: 3 }], xKey: "customerId" });
    expect(o.xAxis.data).toEqual(["Acme"]);
  });

  it("ranks and cuts to top N", () => {
    const o = opt({ data: [{ label: "a", value: 1 }, { label: "b", value: 5 }, { label: "c", value: 3 }],
                    encoding: { sorted: "desc", topN: 2 } });
    expect(o.xAxis.data).toEqual(["b", "c"]);
  });

  it("never draws a second value axis for an overlay", () => {
    const o = opt({ data: [{ label: "a", value: 1 }], overlay: { chartType: "line", data: [{ label: "a", avg: 2 }],
                                                                 series: [{ name: "Avg", dataKey: "avg" }] } });
    expect(Array.isArray(o.yAxis)).toBe(false);
    expect(o.series.map((s: any) => s.type)).toEqual(["bar", "line"]);
  });
});

describe("buildChartOption — other marks", () => {
  it("pie and donut fold past eight slices", () => {
    const data = Array.from({ length: 10 }, (_, i) => ({ label: `s${i}`, value: 10 - i }));
    const o = opt({ chartType: "donut", data });
    expect(o.series[0].type).toBe("pie");
    expect(o.series[0].radius).toEqual(["55%", "80%"]);
    expect(o.series[0].data).toHaveLength(MAX_SERIES);
    expect(o.series[0].data.at(-1)).toMatchObject({ name: "Other", value: 3 + 2 + 1 });
  });

  it("funnel keeps stage order", () => {
    const o = opt({ chartType: "funnel", data: [{ label: "Lead", value: 100 }, { label: "Won", value: 20 }] });
    expect(o.series[0]).toMatchObject({ type: "funnel", sort: "none" });
    expect(o.series[0].data.map((d: any) => d.name)).toEqual(["Lead", "Won"]);
  });

  it("scatter plots two measures against each other, bubble-sized", () => {
    const data = [{ region: "EU", revenue: 100, orders: 5, customers: 3 }];
    const o = opt({ chartType: "scatter", data, xKey: "revenue", yKey: "orders", sizeKey: "customers",
                    labelKey: "region" });
    expect(o.series[0].data[0]).toMatchObject({ value: [100, 5], name: "EU", size: 3 });
    expect(typeof o.series[0].symbolSize).toBe("function");
  });

  it("heatmap places cells on two category axes with a sequential ramp", () => {
    const data = [{ day: "Mon", hour: "9", count: 3 }, { day: "Tue", hour: "10", count: 7 }];
    const o = opt({ chartType: "heatmap", data, xKey: "day", yKey: "hour", valueKey: "count" });
    expect(o.xAxis.data).toEqual(["Mon", "Tue"]);
    expect(o.yAxis.data).toEqual(["9", "10"]);
    expect(o.series[0].data.map((c: any) => c.value)).toEqual([[0, 0, 3], [1, 1, 7]]);
    // ink follows the cell: dark on the pale low end, white on the deep end
    expect(o.series[0].data.map((c: any) => c.label.color)).toEqual(["#0b0b0b", "#ffffff"]);
    expect(o.visualMap.inRange.color).toEqual(DEFAULT_THEME.sequential);
  });

  it("treemap nests leaves under the split", () => {
    const data = [{ cat: "A", team: "x", value: 1 }, { cat: "B", team: "x", value: 2 }];
    const o = opt({ chartType: "treemap", data, xKey: "cat", colorKey: "team" });
    expect(o.series[0].data).toHaveLength(1);
    const parent = o.series[0].data[0];
    expect(parent.name).toBe("x");
    expect(parent.children.map((c: any) => [c.name, c.value])).toEqual([["A", 1], ["B", 2]]);
    // leaves wear their parent's hue: the split is the identity
    expect(parent.children.every((c: any) => c.itemStyle.color === parent.itemStyle.color)).toBe(true);
  });

  it("radar draws one polygon per series over the categories", () => {
    const o = opt({ chartType: "radar", data: [{ label: "Speed", a: 3 }, { label: "Cost", a: 5 }],
                    series: [{ name: "A", dataKey: "a" }] });
    expect(o.radar.indicator.map((i: any) => i.name)).toEqual(["Speed", "Cost"]);
    expect(o.series[0].data[0].value).toEqual([3, 5]);
  });
});

describe("formatValue", () => {
  it("formats by unit; percent takes a fraction", () => {
    expect(formatValue(1234.5, "currency", "GBP")).toBe("£1,235");
    expect(formatValue(0.125, "percent")).toBe("12.5%");
    expect(formatValue(3725, "duration")).toBe("1h 2m");
    expect(formatValue(125000, "number", undefined, true)).toBe("125K");
    expect(formatValue(null)).toBe("—");
  });
});
