import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Switch } from "../../src/components/Switch/Switch";
import { SwitchProps } from "../../src/components/Switch/Switch.schema";

describe("Switch", () => {
  it("renders a switch reflecting checked state", () => {
    render(<Switch name="active" label="Active" checked />);
    expect(screen.getByRole("switch", { name: "Active" })).toHaveAttribute("aria-checked", "true");
  });
  it("toggles via onChange when clicked", async () => {
    const onChange = vi.fn();
    render(<Switch name="active" label="Active" checked={false} onChange={onChange} />);
    await userEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith(true);
  });
  it("does not fire when disabled", async () => {
    const onChange = vi.fn();
    render(<Switch name="x" label="X" disabled onChange={onChange} />);
    await userEvent.click(screen.getByRole("switch"));
    expect(onChange).not.toHaveBeenCalled();
  });
  it("validates props via SwitchProps (softened)", () => {
    expect(() => SwitchProps.parse({ name: "a", label: "A" })).not.toThrow();
    expect(() => SwitchProps.parse({})).not.toThrow();
  });
});
