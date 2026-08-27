import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { Checkbox } from "../../src/components/Checkbox/Checkbox";

describe("Checkbox", () => {
  it("renders checkbox + label with name", () => {
    const { getByLabelText } = render(
      <Checkbox name="agree" label="I agree" />
    );
    const cb = getByLabelText("I agree") as HTMLInputElement;
    expect(cb.tagName).toBe("INPUT");
    expect(cb.type).toBe("checkbox");
    expect(cb.name).toBe("agree");
  });

  it("calls onChange with the new boolean value", () => {
    const calls: boolean[] = [];
    const { getByLabelText } = render(
      <Checkbox name="x" label="X" onChange={(v) => calls.push(v)} />
    );
    fireEvent.click(getByLabelText("X"));
    expect(calls).toEqual([true]);
  });

  it("respects controlled checked prop", () => {
    const { getByLabelText } = render(
      <Checkbox name="x" label="X" checked onChange={() => {}} />
    );
    expect((getByLabelText("X") as HTMLInputElement).checked).toBe(true);
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Checkbox name="x" label="X" style={{ padding: "tokens.spacing.4" }} />
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-4)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Checkbox name="x" label="X" style={{ motion: "fade-in" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });
});
