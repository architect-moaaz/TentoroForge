import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RadioGroup } from "../../src/components/RadioGroup/RadioGroup";
import { RadioGroupProps } from "../../src/components/RadioGroup/RadioGroup.schema";

const opts = [{ value: "a", label: "Option A" }, { value: "b", label: "Option B" }];

describe("RadioGroup", () => {
  it("renders a radio per option with the selected one checked", () => {
    render(<RadioGroup name="g" label="Pick" options={opts} value="b" />);
    expect(screen.getByRole("radio", { name: "Option B" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Option A" })).not.toBeChecked();
  });
  it("fires onChange with the option value when selected", async () => {
    const onChange = vi.fn();
    render(<RadioGroup name="g" label="Pick" options={opts} value="a" onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: "Option B" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });
  it("renders nothing for empty options without crashing", () => {
    render(<RadioGroup name="g" label="Pick" options={[]} />);
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
  });
  it("validates props", () => {
    expect(() => RadioGroupProps.parse({ name: "g", options: opts })).not.toThrow();
    expect(() => RadioGroupProps.parse({})).not.toThrow();
  });
});
