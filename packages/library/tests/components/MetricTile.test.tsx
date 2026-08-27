import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MetricTile } from "../../src/components/MetricTile/MetricTile";

describe("MetricTile", () => {
  it("renders label and formatted number value", () => {
    const { getByText } = render(
      <MetricTile label="Active users" value={1234} format="number" />
    );
    expect(getByText("Active users")).toBeTruthy();
    // Formatted as 1,234 via Intl
    expect(getByText("1,234")).toBeTruthy();
  });

  it("renders currency value", () => {
    const { getByText } = render(
      <MetricTile label="Revenue" value={1500} format="currency" />
    );
    // USD by default
    expect(getByText(/\$1,500/)).toBeTruthy();
  });

  it("renders percent value", () => {
    const { getByText } = render(
      <MetricTile label="Conversion" value={0.123} format="percent" />
    );
    expect(getByText("12%")).toBeTruthy();
  });

  it("renders string value as-is", () => {
    const { getByText } = render(
      <MetricTile label="Status" value="Active" format="number" />
    );
    expect(getByText("Active")).toBeTruthy();
  });

  it("renders delta with up direction", () => {
    const { getByText, container } = render(
      <MetricTile label="X" value={1} format="number"
        delta={{ value: 0.12, direction: "up" }} />
    );
    expect(getByText("12%")).toBeTruthy();
    // Direction encoded as data attribute
    expect(container.querySelector("[data-delta-direction='up']")).toBeTruthy();
  });

  it("renders delta with down direction", () => {
    const { container } = render(
      <MetricTile label="X" value={1} format="number"
        delta={{ value: 0.05, direction: "down" }} />
    );
    expect(container.querySelector("[data-delta-direction='down']")).toBeTruthy();
    expect(container.textContent).toContain("↓");
  });

  it("renders delta with flat direction", () => {
    const { container } = render(
      <MetricTile label="X" value={1} format="number"
        delta={{ value: 0, direction: "flat" }} />
    );
    expect(container.querySelector("[data-delta-direction='flat']")).toBeTruthy();
    expect(container.textContent).toContain("—");
  });

  it("renders trend sparkline as SVG when trend array provided", () => {
    const { container } = render(
      <MetricTile label="X" value={1} format="number" trend={[1, 2, 3, 5, 4]} />
    );
    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
    expect(svg?.querySelector("polyline")).toBeTruthy();
  });

  it("does not render trend sparkline when trend absent", () => {
    const { container } = render(
      <MetricTile label="X" value={1} format="number" />
    );
    expect(container.querySelector("svg")).toBeNull();
  });

  it("renders icon span with data-icon attribute", () => {
    const { container } = render(
      <MetricTile label="X" value={1} format="number" icon="users" />
    );
    expect(container.querySelector("[data-icon='users']")).toBeTruthy();
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <MetricTile label="X" value={1} format="number"
        style={{ padding: "tokens.spacing.semantic.card" }} />
    );
    const root = container.firstChild as HTMLElement;
    expect(root.style.padding).toBe("var(--token-spacing-semantic-card)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <MetricTile label="X" value={1} format="number"
        style={{ motion: "fade-in" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });
});
