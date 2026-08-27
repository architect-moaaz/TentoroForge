import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { Select } from "../../src/components/Select/Select";

describe("Select", () => {
  it("renders label and option list", () => {
    const { getByLabelText, container } = render(
      <Select name="role" label="Role" options={[
        { value: "admin", label: "Admin" },
        { value: "user", label: "User" },
      ]} />
    );
    const select = getByLabelText("Role") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    const options = container.querySelectorAll("option");
    expect(options.length).toBe(2);
    expect(options[0].value).toBe("admin");
    expect(options[0].textContent).toBe("Admin");
  });

  it("marks select required when validators.required is true", () => {
    const { getByLabelText } = render(
      <Select name="r" label="R" options={[{ value: "a", label: "A" }]}
        validators={{ required: true }} />
    );
    expect((getByLabelText("R") as HTMLSelectElement).required).toBe(true);
  });

  it("calls onChange with the new value", () => {
    const calls: string[] = [];
    const { getByLabelText } = render(
      <Select name="r" label="R"
        options={[{ value: "a", label: "A" }, { value: "b", label: "B" }]}
        onChange={(v) => calls.push(v)} />
    );
    fireEvent.change(getByLabelText("R"), { target: { value: "b" } });
    expect(calls).toEqual(["b"]);
  });

  it("respects controlled value prop", () => {
    const { getByLabelText } = render(
      <Select name="r" label="R"
        options={[{ value: "a", label: "A" }, { value: "b", label: "B" }]}
        value="b" onChange={() => {}} />
    );
    expect((getByLabelText("R") as HTMLSelectElement).value).toBe("b");
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Select name="r" label="R" options={[{ value: "a", label: "A" }]}
        style={{ padding: "tokens.spacing.input" }} />
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-input)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Select name="r" label="R" options={[{ value: "a", label: "A" }]}
        style={{ motion: "fade-in" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });
});
