import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { DatePicker } from "../../src/components/DatePicker/DatePicker";

describe("DatePicker", () => {
  it("renders label + date input with name", () => {
    const { getByLabelText } = render(
      <DatePicker name="dob" label="Date of birth" />
    );
    const input = getByLabelText("Date of birth") as HTMLInputElement;
    expect(input.tagName).toBe("INPUT");
    expect(input.type).toBe("date");
    expect(input.name).toBe("dob");
  });

  it("applies min and max bounds", () => {
    const { getByLabelText } = render(
      <DatePicker name="d" label="D" min="1900-01-01" max="2099-12-31" />
    );
    const input = getByLabelText("D") as HTMLInputElement;
    expect(input.min).toBe("1900-01-01");
    expect(input.max).toBe("2099-12-31");
  });

  it("calls onChange with new value", () => {
    const calls: string[] = [];
    const { getByLabelText } = render(
      <DatePicker name="d" label="D" onChange={(v) => calls.push(v)} />
    );
    fireEvent.change(getByLabelText("D"), { target: { value: "2024-06-15" } });
    expect(calls).toEqual(["2024-06-15"]);
  });

  it("respects controlled value", () => {
    const { getByLabelText } = render(
      <DatePicker name="d" label="D" value="2024-06-15" onChange={() => {}} />
    );
    expect((getByLabelText("D") as HTMLInputElement).value).toBe("2024-06-15");
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <DatePicker name="d" label="D" style={{ padding: "tokens.spacing.input" }} />
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-input)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <DatePicker name="d" label="D" style={{ motion: "fade-in" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });
});
