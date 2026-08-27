import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Stat } from "../../src/components/Stat/Stat";
import { StatProps } from "../../src/components/Stat/Stat.schema";

describe("Stat", () => {
  it("renders label and value", () => {
    render(<Stat label="Revenue" value="$12,400" />);
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("$12,400")).toBeInTheDocument();
  });
  it("renders delta with a trend data attribute", () => {
    render(<Stat label="Users" value="1,200" delta="+8%" trend="up" />);
    const el = screen.getByText("+8%");
    expect(el).toBeInTheDocument();
    expect(el.closest("[data-trend]")?.getAttribute("data-trend")).toBe("up");
  });
  it("validates props", () => {
    expect(() => StatProps.parse({ label: "A", value: "1", trend: "down" })).not.toThrow();
    expect(() => StatProps.parse({})).not.toThrow();
  });
});
