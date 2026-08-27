import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MotionEditor } from "../../../src/panes/Properties/style/MotionEditor";

describe("MotionEditor", () => {
  it("renders 6 options: (unset) + 5 motion values", () => {
    render(<MotionEditor value={undefined} onChange={vi.fn()} />);

    const select = screen.getByRole("combobox", { name: /motion/i });
    const options = Array.from(select.querySelectorAll("option")).map(
      (o) => (o as HTMLOptionElement).value
    );

    expect(options).toEqual(["", "none", "fade-in", "fade-up", "stagger", "slide-in"]);
    expect(options).toHaveLength(6);
  });

  it("calls onChange with the string value when a motion option is selected", async () => {
    const handleChange = vi.fn();
    render(<MotionEditor value={undefined} onChange={handleChange} />);

    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox", { name: /motion/i }), "fade-up");

    expect(handleChange).toHaveBeenCalledWith("fade-up");
  });

  it("calls onChange(undefined) when (unset) is selected", async () => {
    const handleChange = vi.fn();
    render(<MotionEditor value="stagger" onChange={handleChange} />);

    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox", { name: /motion/i }), "");

    expect(handleChange).toHaveBeenCalledWith(undefined);
  });
});
