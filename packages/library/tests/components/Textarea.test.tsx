import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { Textarea } from "../../src/components/Textarea/Textarea";

describe("Textarea", () => {
  it("renders label + textarea with name and rows", () => {
    const { getByLabelText } = render(
      <Textarea name="bio" label="Bio" rows={6} placeholder="Tell us..." />
    );
    const ta = getByLabelText("Bio") as HTMLTextAreaElement;
    expect(ta.tagName).toBe("TEXTAREA");
    expect(ta.name).toBe("bio");
    expect(ta.rows).toBe(6);
    expect(ta.placeholder).toBe("Tell us...");
  });

  it("uses default rows of 4 when not specified", () => {
    const { getByLabelText } = render(<Textarea name="x" label="X" />);
    expect((getByLabelText("X") as HTMLTextAreaElement).rows).toBe(4);
  });

  it("calls onChange with new value", () => {
    const calls: string[] = [];
    const { getByLabelText } = render(
      <Textarea name="x" label="X" onChange={(v) => calls.push(v)} />
    );
    fireEvent.change(getByLabelText("X"), { target: { value: "hi" } });
    expect(calls).toEqual(["hi"]);
  });

  it("respects controlled value", () => {
    const { getByLabelText } = render(
      <Textarea name="x" label="X" value="hello" onChange={() => {}} />
    );
    expect((getByLabelText("X") as HTMLTextAreaElement).value).toBe("hello");
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Textarea name="x" label="X" style={{ padding: "tokens.spacing.input" }} />
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-input)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Textarea name="x" label="X" style={{ motion: "fade-in" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });
});
