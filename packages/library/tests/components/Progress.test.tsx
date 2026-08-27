import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Progress } from "../../src/components/Progress/Progress";
import { ProgressProps } from "../../src/components/Progress/Progress.schema";

describe("Progress", () => {
  it("renders a bar with aria-valuenow reflecting percent", () => {
    render(<Progress label="Upload" value={40} max={100} />);
    const bar = screen.getByRole("progressbar", { name: "Upload" });
    expect(bar).toHaveAttribute("aria-valuenow", "40");
  });
  it("clamps value to 0..100 percent", () => {
    render(<Progress label="Over" value={150} max={100} />);
    expect(screen.getByRole("progressbar", { name: "Over" })).toHaveAttribute("aria-valuenow", "100");
  });
  it("renders a circular variant progressbar", () => {
    render(<Progress label="Ring" value={50} variant="circular" />);
    expect(screen.getByRole("progressbar", { name: "Ring" })).toBeInTheDocument();
  });
  it("validates props", () => {
    expect(() => ProgressProps.parse({ value: 50 })).not.toThrow();
    expect(() => ProgressProps.parse({})).not.toThrow();
  });
});
