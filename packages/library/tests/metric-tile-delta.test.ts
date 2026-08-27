/**
 * A KPI delta must never invent a number the author did not write.
 *
 * The composer authors deltas as prose — "+3 vs last week", "-2 vs yesterday".
 * MetricTile's contract said `{value: <fraction>, direction}` and it bridged
 * the gap with `parseFloat`, so "+3 vs last week" became 3, and formatDelta
 * rendered 3 as a *fraction* → "300%". Five tiles on the live dashboard read
 * 300% / 800% / 200% / 120% / 400%, none of which any author wrote, and
 * "-2 vs yesterday" lost its sign and displayed as a rise.
 *
 * Two shapes are documented in schema_rules.py (a fraction and a string), and
 * the app emits a third (a bare string), so the component — the one place that
 * renders — accepts all three rather than trusting upstream to converge.
 */
import { describe, it, expect } from "vitest";
import { normalizeDelta } from "../src/components/MetricTile/delta";

describe("a delta the author wrote as prose", () => {
  it("renders verbatim instead of being parsed into a number", () => {
    expect(normalizeDelta("+3 vs last week").text).toBe("+3 vs last week");
  });

  it("keeps prose passed as {value} too — the shape the renderer wraps it in", () => {
    expect(normalizeDelta({ value: "+8% vs last month" }).text).toBe("+8% vs last month");
  });

  it("reads direction from the leading sign when none was declared", () => {
    expect(normalizeDelta("+3 vs last week").direction).toBe("up");
    expect(normalizeDelta("-2 vs yesterday").direction).toBe("down");
  });

  it("does not lose a fall — the live bug showed -2 as a rise", () => {
    expect(normalizeDelta("-2 vs yesterday").direction).not.toBe("up");
  });

  it("honours an explicit direction over the sign", () => {
    expect(normalizeDelta({ value: "+3", direction: "down" }).direction).toBe("down");
  });

  it("falls back to flat rather than undefined — the class read '...undefined'", () => {
    expect(normalizeDelta("3 items").direction).toBe("flat");
    expect(normalizeDelta({ value: "3" }).direction).toBe("flat");
  });
});

describe("a delta the author wrote as a number", () => {
  it("keeps the documented fraction convention: 0.12 is 12%", () => {
    expect(normalizeDelta({ value: 0.12, direction: "up" }).text).toBe("12%");
  });

  it("infers direction from a negative number", () => {
    expect(normalizeDelta({ value: -0.05 }).direction).toBe("down");
  });

  it("renders the magnitude unsigned — the glyph carries the direction", () => {
    expect(normalizeDelta({ value: -0.05 }).text).toBe("5%");
  });
});

describe("no delta at all", () => {
  it("returns null so the tile renders nothing", () => {
    expect(normalizeDelta(undefined)).toBeNull();
    expect(normalizeDelta("")).toBeNull();
    expect(normalizeDelta({})).toBeNull();
  });
});

// ── every skin, not just the base component ─────────────────────────────
//
// MetricTile ships in five variants. The base one was fixed first and the
// live dashboard did not change, because the app renders a *skin* — and all
// four carried their own copy of `parseFloat(delta.value)`. Same shape as the
// scroll-guard bug: one component, several render paths, one of them fixed.
import { readFileSync } from "node:fs";
import { join } from "node:path";

describe("no variant parses prose into a number", () => {
  const VARIANTS = ["MetricTile", "MetricTile.linear", "MetricTile.notion",
                    "MetricTile.stripe", "MetricTile.workday"];

  for (const v of VARIANTS) {
    it(`${v} renders the author's delta rather than re-deriving it`, () => {
      const src = readFileSync(
        join(__dirname, "..", "src", "components", "MetricTile", `${v}.tsx`), "utf8");
      expect(src).not.toMatch(/parseFloat\s*\(\s*delta/);
      // A raw `delta.direction` index is what produced the literal
      // "undefined" class when direction was absent.
      expect(src).not.toMatch(/DELTA_TONE\[\s*delta\.direction/);
    });
  }
});
