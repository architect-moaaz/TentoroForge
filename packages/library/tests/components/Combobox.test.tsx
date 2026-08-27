import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Combobox } from "../../src/components/Combobox/Combobox";
import { ComboboxProps } from "../../src/components/Combobox/Combobox.schema";

const opts = [
  { value: "dxb", label: "Dubai" },
  { value: "auh", label: "Abu Dhabi" },
  { value: "shj", label: "Sharjah" },
];

describe("Combobox", () => {
  it("opens the option list on focus and shows all options", async () => {
    render(<Combobox name="city" label="City" options={opts} />);
    await userEvent.click(screen.getByRole("combobox"));
    expect(screen.getByText("Dubai")).toBeInTheDocument();
    expect(screen.getByText("Sharjah")).toBeInTheDocument();
  });
  it("filters options as you type", async () => {
    render(<Combobox name="city" label="City" options={opts} />);
    await userEvent.type(screen.getByRole("combobox"), "Abu");
    expect(screen.getByText("Abu Dhabi")).toBeInTheDocument();
    expect(screen.queryByText("Sharjah")).not.toBeInTheDocument();
  });
  it("selects an option and fires onChange with its value", async () => {
    const onChange = vi.fn();
    render(<Combobox name="city" label="City" options={opts} onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByText("Sharjah"));
    expect(onChange).toHaveBeenCalledWith("shj");
  });
  it("validates props", () => {
    expect(() => ComboboxProps.parse({ name: "c", options: opts })).not.toThrow();
    expect(() => ComboboxProps.parse({})).not.toThrow();
  });
});
