import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MetricTile } from "../src/components/MetricTile/MetricTile";

// Slice A / KPI anatomy — the tile learns to render structured sub-info
// (breakdown rows) and a threshold-driven value tone so a "Total Debt
// $127M" doesn't ship as a bare number when the story is "Male 984 /
// Female 1,016 — and DTI at 139 is red because it's over threshold".
// See docs/superpowers/specs/2026-08-15-widget-anatomy-composition-recipes.md

describe("MetricTile — Slice A anatomy (breakdown + threshold)", () => {
  describe("backwards compatibility", () => {
    it("renders exactly today's markup when new props are absent", () => {
      const { container } = render(
        <MetricTile label="Batches" value={42} format="number" />
      );
      const tile = container.querySelector("[data-metric-tile]");
      expect(tile).toBeTruthy();
      expect(tile?.querySelector("[data-metric-breakdown]")).toBeNull();
      expect(tile?.getAttribute("data-threshold")).toBeNull();
    });
  });

  describe("breakdown rows", () => {
    it("emits a data-metric-breakdown dl with one dt+dd per row", () => {
      const { container } = render(
        <MetricTile
          label="Clients"
          value={2000}
          format="number"
          breakdown={[
            { label: "Male",   value: 984 },
            { label: "Female", value: 1016 },
          ]}
        />
      );
      const dl = container.querySelector("[data-metric-breakdown]");
      expect(dl).toBeTruthy();
      const dts = dl!.querySelectorAll("dt");
      const dds = dl!.querySelectorAll("dd");
      expect(dts).toHaveLength(2);
      expect(dds).toHaveLength(2);
      expect(dts[0].textContent).toBe("Male");
      expect(dts[1].textContent).toBe("Female");
    });

    it("formats numeric breakdown values with thousands separators", () => {
      const { container } = render(
        <MetricTile
          label="Clients"
          value={2000}
          format="number"
          breakdown={[{ label: "Male", value: 984 }, { label: "Female", value: 1016 }]}
        />
      );
      const dds = container.querySelectorAll("[data-metric-breakdown-value]");
      expect(dds[0].textContent).toBe("984");
      expect(dds[1].textContent).toBe("1,016");
    });

    it("passes string breakdown values through verbatim (mustache-tolerant)", () => {
      // Composer emits `{{some_source}}` before data resolves; the tile
      // must not choke on unresolved templates.
      const { container } = render(
        <MetricTile
          label="Debt"
          value="$127M"
          format="currency"
          breakdown={[{ label: "Max", value: "{{maxDebt}}" }]}
        />
      );
      const dd = container.querySelector("[data-metric-breakdown-value]");
      expect(dd?.textContent).toBe("{{maxDebt}}");
    });

    it("empty breakdown array renders nothing", () => {
      const { container } = render(
        <MetricTile label="X" value={1} format="number" breakdown={[]} />
      );
      expect(container.querySelector("[data-metric-breakdown]")).toBeNull();
    });
  });

  describe("threshold", () => {
    it("stamps data-threshold=ok when value is under all thresholds", () => {
      const { container } = render(
        <MetricTile
          label="DTI" value={45} format="number"
          threshold={{ warnAbove: 50, criticalAbove: 100 }}
        />
      );
      expect(container.querySelector("[data-metric-tile]")?.getAttribute("data-threshold")).toBe("ok");
    });

    it("stamps data-threshold=warn when value exceeds warnAbove only", () => {
      const { container } = render(
        <MetricTile
          label="DTI" value={75} format="number"
          threshold={{ warnAbove: 50, criticalAbove: 100 }}
        />
      );
      expect(container.querySelector("[data-metric-tile]")?.getAttribute("data-threshold")).toBe("warn");
    });

    it("stamps data-threshold=critical when value exceeds criticalAbove", () => {
      const { container } = render(
        <MetricTile
          label="DTI" value={139.36} format="number"
          threshold={{ warnAbove: 50, criticalAbove: 100 }}
        />
      );
      expect(container.querySelector("[data-metric-tile]")?.getAttribute("data-threshold")).toBe("critical");
    });

    it("colorOnValue=true adds text-destructive class at critical", () => {
      const { container } = render(
        <MetricTile
          label="DTI" value={139} format="number"
          threshold={{ criticalAbove: 100, colorOnValue: true }}
        />
      );
      const val = container.querySelector("[data-metric-value]");
      expect(val?.className).toMatch(/text-destructive/);
    });

    it("colorOnValue=false (default) keeps value class untouched — attr-only signal", () => {
      const { container } = render(
        <MetricTile
          label="DTI" value={139} format="number"
          threshold={{ criticalAbove: 100 }}
        />
      );
      const val = container.querySelector("[data-metric-value]");
      expect(val?.className || "").not.toMatch(/text-destructive/);
    });

    it("does not colour a non-numeric value (unresolved binding)", () => {
      const { container } = render(
        <MetricTile
          label="DTI" value="{{dtiRatio}}" format="number"
          threshold={{ criticalAbove: 100, colorOnValue: true }}
        />
      );
      expect(container.querySelector("[data-metric-tile]")?.getAttribute("data-threshold")).toBe("ok");
    });

    it("parses numeric prefix out of a currency-formatted string", () => {
      // A composer might already pre-format "$127,419,388" — the
      // threshold check strips non-numerics before comparing.
      const { container } = render(
        <MetricTile
          label="Debt" value="$127,419,388" format="currency"
          threshold={{ criticalAbove: 100_000_000 }}
        />
      );
      expect(container.querySelector("[data-metric-tile]")?.getAttribute("data-threshold")).toBe("critical");
    });
  });

  describe("breakdown + threshold together", () => {
    it("renders both anatomy layers without interference", () => {
      const { container } = render(
        <MetricTile
          label="Total Debt"
          value={127419388}
          format="currency"
          threshold={{ criticalAbove: 100_000_000, colorOnValue: true }}
          breakdown={[
            { label: "Single Max", value: "$516K" },
            { label: "Single Min", value: "$5" },
          ]}
        />
      );
      const tile = container.querySelector("[data-metric-tile]");
      expect(tile?.getAttribute("data-threshold")).toBe("critical");
      expect(tile?.querySelectorAll("[data-metric-breakdown] dd")).toHaveLength(2);
      const val = container.querySelector("[data-metric-value]");
      expect(val?.className).toMatch(/text-destructive/);
    });
  });
});
