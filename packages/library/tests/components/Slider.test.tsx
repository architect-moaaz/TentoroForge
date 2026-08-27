import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Slider } from "../../src/components/Slider/Slider";
import { SliderProps } from "../../src/components/Slider/Slider.schema";

describe("Slider", () => {
  it("renders a single slider with aria values", () => {
    render(<Slider name="vol" label="Volume" min={0} max={10} value={4} />);
    const s = screen.getByRole("slider");
    expect(s).toHaveAttribute("aria-valuemin", "0");
    expect(s).toHaveAttribute("aria-valuemax", "10");
  });
  it("fires onChange with the new numeric value", () => {
    const onChange = vi.fn();
    render(<Slider name="vol" label="Volume" min={0} max={10} value={4} onChange={onChange} />);
    fireEvent.change(screen.getByRole("slider"), { target: { value: "7" } });
    expect(onChange).toHaveBeenCalledWith(7);
  });
  it("renders two thumbs in range mode and emits a tuple", () => {
    const onChange = vi.fn();
    render(<Slider name="r" label="Range" min={0} max={100} range value={[20, 80]} onChange={onChange} />);
    const sliders = screen.getAllByRole("slider");
    expect(sliders).toHaveLength(2);
    fireEvent.change(sliders[1], { target: { value: "90" } });
    expect(onChange).toHaveBeenCalledWith([20, 90]);
  });
  it("validates props", () => {
    expect(() => SliderProps.parse({ name: "s" })).not.toThrow();
    expect(() => SliderProps.parse({})).not.toThrow();
  });
});
