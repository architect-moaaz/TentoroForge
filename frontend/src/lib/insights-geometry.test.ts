/**
 * The arithmetic behind the Insights charts (lib/insights-geometry.ts).
 *
 * Pinned: an axis starts at zero and ends on a round number at or above the biggest value (whole numbers for counts); tick text is
 * short; bars are thin and centred and never fill their slot; the pointer picks the band it is over, clamped at the ends; a line breaks
 * where a value is unknown instead of falling to zero; day labels never touch; and shares keep a gap and stay visible.
 */
import { describe, it, expect } from "vitest";
import {
  areaOf, columnLayout, compactTick, dayLabelIndexes, lineRuns, moneyTick, nearestBand, niceTicks, pathOf, pointX, shareWidths,
} from "./insights-geometry";

describe("axis ticks", () => {
  it("start at zero, are round, and end at or above the biggest value", () => {
    for (const max of [0.36, 3, 7, 10, 23, 99, 480, 1200, 54_321]) {
      const { ticks, top } = niceTicks(max);
      expect(ticks[0]).toBe(0);
      expect(top).toBeGreaterThanOrEqual(max);
      expect(ticks[ticks.length - 1]).toBe(top);
      const step = ticks[1] - ticks[0];
      expect(ticks.every((t, i) => Math.abs(t - i * step) < 1e-6), "evenly spaced").toBe(true);
      expect(ticks.length, "a handful of ticks, not a ruler").toBeLessThanOrEqual(7);
    }
  });

  it("keeps whole numbers for counts and still draws an axis for nothing", () => {
    expect(niceTicks(3, { integer: true }).ticks).toEqual([0, 1, 2, 3]);
    expect(niceTicks(10, { integer: true }).ticks.every(Number.isInteger)).toBe(true);
    expect(niceTicks(0, { integer: true }).top).toBeGreaterThan(0);
    expect(niceTicks(NaN).top).toBeGreaterThan(0);
    expect(niceTicks(-5).top).toBeGreaterThan(0);
  });

  it("writes short tick text", () => {
    expect(["0", "7", "500", "1.2K", "12K", "2.5M"]).toEqual([0, 7, 500, 1200, 12_000, 2_500_000].map(compactTick));
    expect([0, 0.05, 0.4, 1.2, 12.5, 480].map(moneyTick)).toEqual(["$0", "$0.05", "$0.40", "$1.2", "$12.5", "$480"]);
  });
});

describe("columns", () => {
  it("are thin: never wider than the cap, never filling the band, always centred", () => {
    const wide = columnLayout(600, 7);
    expect(wide.bar).toBe(24);
    expect(wide.band).toBeCloseTo(600 / 7);
    expect(wide.x(0) + wide.bar / 2).toBeCloseTo(wide.bandX(0) + wide.band / 2);
    const dense = columnLayout(600, 90);
    expect(dense.bar).toBeLessThan(dense.band);
    expect(dense.bar).toBeGreaterThanOrEqual(2);
    expect(dense.x(89) + dense.bar).toBeLessThanOrEqual(600);
    expect(columnLayout(0, 0).bar).toBeGreaterThanOrEqual(2);
  });

  it("are found from the pointer: the band it is over, clamped at both ends", () => {
    expect([-20, 0, 99, 100, 350, 599, 600, 900].map((x) => nearestBand(x, 600, 6))).toEqual([0, 0, 0, 1, 3, 5, 5, 5]);
    expect(nearestBand(10, 0, 5)).toBe(0);
    expect(nearestBand(10, 100, 0)).toBe(0);
  });
});

describe("lines", () => {
  it("sit in the middle of their day's band, so a line and its columns line up", () => {
    expect(pointX(0, 700, 7)).toBe(50);
    expect(pointX(6, 700, 7)).toBe(650);
  });

  it("break where a value is unknown and never drop to zero", () => {
    const runs = lineRuns([1, 2, null, null, 3, 4, 2], 4, 700, 100);
    expect(runs).toHaveLength(2);
    expect(runs[0]).toHaveLength(2);
    expect(runs[1]).toHaveLength(3);
    expect(lineRuns([null, null], 1, 100, 50)).toEqual([]);
    const [only] = lineRuns([0, 4], 4, 200, 100);
    expect(only[0][1], "zero sits on the baseline").toBe(100);
    expect(only[1][1], "the top of the axis sits at the top").toBe(0);
  });

  it("make a path, and a wash closed down to the baseline", () => {
    const pts: Array<[number, number]> = [[0, 10], [50, 0]];
    expect(pathOf(pts)).toBe("M0 10 L50 0");
    expect(areaOf(pts, 100)).toBe("M0 10 L50 0 L50 100 L0 100 Z");
    expect(areaOf([], 100)).toBe("");
  });
});

describe("day labels", () => {
  it("always include the latest day, are evenly spaced back from it, and never touch each other", () => {
    for (const [count, width] of [[7, 600], [30, 600], [90, 600], [90, 300], [2, 600], [14, 200]] as const) {
      const idx = dayLabelIndexes(count, width);
      expect(idx[idx.length - 1], `${count} days in ${width}px`).toBe(count - 1);
      const gaps = idx.slice(1).map((v, k) => v - idx[k]);
      expect(new Set(gaps).size, "every gap the same").toBeLessThanOrEqual(1);
      for (let k = 1; k < idx.length; k++) {
        expect(pointX(idx[k], width, count) - pointX(idx[k - 1], width, count)).toBeGreaterThanOrEqual(44);
      }
    }
    expect(dayLabelIndexes(7, 600), "a week fits a label for every day").toEqual([0, 1, 2, 3, 4, 5, 6]);
    expect(dayLabelIndexes(1, 600)).toEqual([0]);
    expect(dayLabelIndexes(0, 600)).toEqual([]);
  });
});

describe("shares of a whole", () => {
  it("keep a gap between neighbours, fit the width, and show even a tiny share", () => {
    const [a, b] = shareWidths([98.8, 1.2], 400);
    expect(a + b).toBeCloseTo(400 - 2);
    expect(b, "a 1.2% share is still seen").toBeGreaterThanOrEqual(3);
    const three = shareWidths([1, 1, 1], 304);
    expect(three.reduce((x, y) => x + y, 0), "304 minus two gaps of 2").toBeCloseTo(300);
    expect(shareWidths([5, 0], 200)).toEqual([200, 0]);
    expect(shareWidths([0, 0], 200)).toEqual([0, 0]);
  });
});
