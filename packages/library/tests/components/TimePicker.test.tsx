import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TimePicker } from "../../src/components/TimePicker/TimePicker";
import { TimePickerProps } from "../../src/components/TimePicker/TimePicker.schema";

describe("TimePicker", () => {
  it("renders the label and a time input with the value", () => {
    render(<TimePicker name="start" label="Start time" value="09:30" />);
    expect(screen.getByLabelText("Start time")).toHaveValue("09:30");
  });
  it("fires onChange with the new time", () => {
    const onChange = vi.fn();
    render(<TimePicker name="start" label="Start time" value="09:00" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Start time"), { target: { value: "14:15" } });
    expect(onChange).toHaveBeenCalledWith("14:15");
  });
  it("validates props", () => {
    expect(() => TimePickerProps.parse({ name: "t", label: "T" })).not.toThrow();
    expect(() => TimePickerProps.parse({})).not.toThrow();
  });
});
