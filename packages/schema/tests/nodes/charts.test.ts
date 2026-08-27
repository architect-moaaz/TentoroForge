import { describe, it, expect } from "vitest";
import { ChartNode } from "../../src/nodes/charts";

describe("Chart node — data binding", () => {
  it("accepts Mustache string binding for data", () => {
    const r = ChartNode.safeParse({
      id: "c",
      type: "Chart",
      props: {
        chartType: "line",
        data: "{{stats.dailyUsers}}",
        xKey: "date",
        series: [{ name: "Users", dataKey: "users" }],
      },
    });
    expect(r.success).toBe(true);
  });

  it("still accepts inline array data", () => {
    const r = ChartNode.safeParse({
      id: "c",
      type: "Chart",
      props: {
        chartType: "bar",
        data: [
          { date: "Mon", users: 10 },
          { date: "Tue", users: 20 },
        ],
        xKey: "date",
        series: [{ name: "Users", dataKey: "users" }],
      },
    });
    expect(r.success).toBe(true);
  });

  it("rejects empty string for data (must be a valid binding)", () => {
    const r = ChartNode.safeParse({
      id: "c",
      type: "Chart",
      props: {
        chartType: "area",
        data: "",
        xKey: "date",
        series: [{ name: "Users", dataKey: "users" }],
      },
    });
    expect(r.success).toBe(false);
  });
});
