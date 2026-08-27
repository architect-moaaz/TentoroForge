import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Cluster } from "../../src/components/Cluster/Cluster";
import { Section } from "../../src/components/Section/Section";
import { Card } from "../../src/components/Card/Card";
import { buildDefaultRegistry } from "../../src/buildDefaultRegistry";

// Regression for the render-layer half of the className guarantee: validateProps
// preserves className + data-* universally, but the layout primitives built
// their class list solely from their own props and silently dropped both —
// verified live on cwx1stzz (Cluster with className="dashboard-toolbar" and
// data-dashboard-toolbar rendered with neither attribute), forcing app CSS
// into fragile :has() selectors.
describe("layout primitives — className + data-* passthrough", () => {
  it("Cluster (flex path) appends className and spreads data-*", () => {
    const { container } = render(
      <Cluster
        justify="end"
        align="end"
        className="dashboard-toolbar"
        data-dashboard-toolbar=""
      />
    );
    const root = container.firstElementChild!;
    expect(root.className).toContain("flex flex-row flex-wrap");
    expect(root.className).toContain("dashboard-toolbar");
    expect(root.hasAttribute("data-dashboard-toolbar")).toBe(true);
  });

  it("Cluster (equalCols grid path) carries className and data-*", () => {
    const { container } = render(
      <Cluster
        justify="start"
        align="center"
        equalCols
        className="kpi-row"
        data-kpi-row="true"
      >
        <span>a</span>
        <span>b</span>
      </Cluster>
    );
    const root = container.firstElementChild!;
    expect(root.getAttribute("data-cluster-equal-cols")).toBe("true");
    expect(root.className).toContain("kpi-row");
    expect(root.getAttribute("data-kpi-row")).toBe("true");
  });

  it("Section appends className and spreads data-*", () => {
    const { container } = render(
      <Section variant="plain" title="T" className="page-hero" data-hero="">
        <p>body</p>
      </Section>
    );
    const root = container.querySelector("section")!;
    expect(root.className).toContain("page-hero");
    expect(root.className).toContain("bg-background"); // computed classes kept
    expect(root.hasAttribute("data-hero")).toBe(true);
  });

  it("Card appends className and spreads data-*", () => {
    const { container } = render(
      <Card title="T" className="summary-card" data-summary-card="">
        <p>body</p>
      </Card>
    );
    const root = container.querySelector("[data-card]")!;
    expect(root.className).toContain("summary-card");
    expect(root.className).toContain("bg-card"); // computed classes kept
    expect(root.hasAttribute("data-summary-card")).toBe(true);
  });

  it("end-to-end via registry: validateProps preserves data-* on a strict schema (Cluster)", () => {
    const reg = buildDefaultRegistry();
    const v = reg.validateProps("Cluster", {
      className: "dashboard-toolbar",
      "data-dashboard-toolbar": "",
      align: "end",
    });
    expect(v.className).toBe("dashboard-toolbar");
    expect("data-dashboard-toolbar" in v).toBe(true);
  });
});
