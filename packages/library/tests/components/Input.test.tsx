import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { Input } from "../../src/components/Input/Input";

describe("Input", () => {
  it("renders label + input with name and type", () => {
    const { getByLabelText } = render(
      <Input name="email" label="Email" type="email" placeholder="you@example.com" />
    );
    const input = getByLabelText("Email") as HTMLInputElement;
    expect(input.tagName).toBe("INPUT");
    expect(input.type).toBe("email");
    expect(input.name).toBe("email");
    expect(input.placeholder).toBe("you@example.com");
  });

  it("marks input required when validators.required is true", () => {
    const { getByLabelText } = render(
      <Input name="x" label="X" type="text" validators={{ required: true }} />
    );
    expect((getByLabelText("X") as HTMLInputElement).required).toBe(true);
  });

  it("calls onChange with the new value", () => {
    const calls: string[] = [];
    const { getByLabelText } = render(
      <Input name="x" label="X" type="text" onChange={(v) => calls.push(v)} />
    );
    fireEvent.change(getByLabelText("X"), { target: { value: "hi" } });
    expect(calls).toEqual(["hi"]);
  });

  it("respects controlled value prop", () => {
    const { getByLabelText } = render(
      <Input name="x" label="X" type="text" value="hello" onChange={() => {}} />
    );
    expect((getByLabelText("X") as HTMLInputElement).value).toBe("hello");
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Input name="x" label="X" type="text"
        style={{ padding: "tokens.spacing.input" }} />
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-input)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Input name="x" label="X" type="text" style={{ motion: "fade-in" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });

  it("renders a leading icon when iconLeft is supplied", () => {
    const { container } = render(
      <Input name="search" label="Search" type="text" iconLeft="search" />
    );
    const leftIcon = container.querySelector('[data-input-icon="left"]');
    expect(leftIcon).toBeTruthy();
    expect(container.querySelector(".relative input")).toBeTruthy();
  });

  it("renders a trailing icon when iconRight is supplied", () => {
    // chevron-down is in the registered icon set; "eye" isn't, so we use a
    // known one — the wrapping logic is what we're testing here, not lucide.
    const { container } = render(
      <Input name="select" label="Pick one" type="text" iconRight="chevron-down" />
    );
    expect(container.querySelector('[data-input-icon="right"]')).toBeTruthy();
  });

  it("renders no icon wrapper when neither icon is supplied (back-compat)", () => {
    const { container } = render(
      <Input name="plain" label="Plain" type="text" />
    );
    expect(container.querySelector('[data-input-icon]')).toBeNull();
  });

  it("omits the label block when label prop is undefined", () => {
    const { container } = render(
      <Input name="q" type="text" placeholder="Search" iconLeft="search" />
    );
    expect(container.querySelector("label")).toBeNull();
  });

  it("renders the label at the design type-scale caption size (not hardcoded text-sm)", () => {
    const { getByText } = render(
      <Input name="email" label="Email" type="email" />
    );
    const label = getByText("Email");
    expect(label.tagName).toBe("LABEL");
    expect(label.className).toContain("text-caption");
    expect(label.className).not.toContain("text-sm");
  });
});
