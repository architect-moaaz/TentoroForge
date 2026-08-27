import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NumberInput } from "../../src/components/NumberInput/NumberInput";
import { NumberInputProps } from "../../src/components/NumberInput/NumberInput.schema";

describe("NumberInput", () => {
  it("renders the value", () => {
    render(<NumberInput name="qty" label="Qty" value={5} />);
    expect(screen.getByRole("spinbutton")).toHaveValue(5);
  });
  it("increments by step on + and clamps to max", async () => {
    const onChange = vi.fn();
    render(<NumberInput name="qty" label="Qty" value={9} max={10} step={1} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: /increment/i }));
    expect(onChange).toHaveBeenCalledWith(10);
  });
  it("does not exceed max when already at max", async () => {
    const onChange = vi.fn();
    render(<NumberInput name="q2" label="Q2" value={10} max={10} step={1} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: /increment/i }));
    expect(onChange).toHaveBeenCalledWith(10);
  });
  it("decrements and clamps to min", async () => {
    const onChange = vi.fn();
    render(<NumberInput name="q" label="Q" value={0} min={0} step={1} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: /decrement/i }));
    expect(onChange).toHaveBeenCalledWith(0);
  });
  it("validates props", () => {
    expect(() => NumberInputProps.parse({ name: "n", label: "N" })).not.toThrow();
    expect(() => NumberInputProps.parse({})).not.toThrow();
  });
  it("defaults showSteppers to true (regression: stepper buttons present)", () => {
    render(<NumberInput name="qty" label="Qty" value={5} />);
    expect(screen.getByRole("button", { name: /increment/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /decrement/i })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton")).toHaveValue(5);
    expect(NumberInputProps.parse({}).showSteppers).toBe(true);
  });
  it("showSteppers={false} renders a plain input: no +/- buttons, no spinbutton role, prefix/suffix still render", () => {
    render(
      <NumberInput name="price" label="Price" value={12} showSteppers={false} prefix="$" suffix="USD" />
    );
    expect(screen.queryByRole("button", { name: /increment/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /decrement/i })).toBeNull();
    expect(screen.queryByRole("spinbutton")).toBeNull();
    expect(screen.getByText("$")).toBeInTheDocument();
    expect(screen.getByText("USD")).toBeInTheDocument();
  });
  it("showSteppers={false} still updates the value when a number is typed", async () => {
    const onChange = vi.fn();
    render(<NumberInput name="price" label="Price" value={0} showSteppers={false} onChange={onChange} />);
    const input = screen.getByRole("textbox");
    await userEvent.type(input, "7");
    expect(onChange).toHaveBeenLastCalledWith(7);
  });
});
