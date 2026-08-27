import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SegmentedControl } from "../../src/components/SegmentedControl/SegmentedControl";
import { SegmentedControlProps } from "../../src/components/SegmentedControl/SegmentedControl.schema";

const opts = [{ value: "day", label: "Day" }, { value: "week", label: "Week" }, { value: "month", label: "Month" }];

describe("SegmentedControl", () => {
  it("renders all options as buttons", () => {
    render(<SegmentedControl name="range" options={opts} />);
    expect(screen.getByRole("button", { name: "Day" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Month" })).toBeInTheDocument();
  });
  it("marks the selected option with aria-pressed and fires onChange", () => {
    const onChange = vi.fn();
    render(<SegmentedControl name="range" options={opts} value="day" onChange={onChange} />);
    expect(screen.getByRole("button", { name: "Day" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Week" }));
    expect(onChange).toHaveBeenCalledWith("week");
  });
  it("validates props", () => {
    expect(() => SegmentedControlProps.parse({ name: "r", options: opts })).not.toThrow();
    expect(() => SegmentedControlProps.parse({})).not.toThrow();
  });
});
