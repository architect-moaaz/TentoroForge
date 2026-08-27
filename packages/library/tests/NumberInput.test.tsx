import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { NumberInput } from "../src/components/NumberInput/NumberInput";

describe("NumberInput — uncontrolled steppers", () => {
  it("increments/decrements via +/- when no onChange is wired (schema form)", () => {
    const { getByLabelText, getByRole } = render(<NumberInput name="duration" step={5} min={0} />);
    const input = getByRole("spinbutton") as HTMLInputElement;
    expect(input.value).toBe("0");
    fireEvent.click(getByLabelText("increment"));
    fireEvent.click(getByLabelText("increment"));
    expect(input.value).toBe("10");
    fireEvent.click(getByLabelText("decrement"));
    expect(input.value).toBe("5");
    fireEvent.click(getByLabelText("decrement")); fireEvent.click(getByLabelText("decrement"));
    expect(input.value).toBe("0"); // clamped at min
  });

  it("stays controlled when a parent supplies onChange", () => {
    let seen = -1;
    const { getByLabelText, getByRole } = render(
      <NumberInput name="d" value={3} onChange={(v) => (seen = v)} />
    );
    fireEvent.click(getByLabelText("increment"));
    expect(seen).toBe(4);
    // value stays 3 (parent owns state, didn't re-render here)
    expect((getByRole("spinbutton") as HTMLInputElement).value).toBe("3");
  });
});
