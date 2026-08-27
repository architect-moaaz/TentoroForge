import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ColorPicker } from "../../src/components/ColorPicker/ColorPicker";
import { ColorPickerProps } from "../../src/components/ColorPicker/ColorPicker.schema";

describe("ColorPicker", () => {
  it("renders the label and the current hex value", () => {
    render(<ColorPicker name="brand" label="Brand color" value="#3366ff" />);
    expect(screen.getByText("Brand color")).toBeInTheDocument();
    expect(screen.getByText(/#3366ff/i)).toBeInTheDocument();
  });
  it("fires onChange with the new color", () => {
    const onChange = vi.fn();
    render(<ColorPicker name="brand" label="Brand color" value="#000000" onChange={onChange} />);
    fireEvent.change(screen.getByTestId("color-input"), { target: { value: "#ff0000" } });
    expect(onChange).toHaveBeenCalledWith("#ff0000");
  });
  it("validates props", () => {
    expect(() => ColorPickerProps.parse({ name: "c", label: "C" })).not.toThrow();
    expect(() => ColorPickerProps.parse({})).not.toThrow();
  });
});
