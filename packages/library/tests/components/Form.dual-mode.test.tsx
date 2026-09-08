import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Form } from "../../src/components/Form/Form";
import { FormProps } from "../../src/components/Form/Form.schema";

describe("Form dual-mode schema + rendering", () => {
  it("schema accepts declarative {workflow, fields}", () => {
    const r = FormProps.safeParse({
      workflow: "createNote",
      fields: [{ kind: "text", name: "title", label: "Title" }],
    });
    expect(r.success).toBe(true);
  });

  it("schema accepts empty props (container mode)", () => {
    const r = FormProps.safeParse({});
    expect(r.success).toBe(true);
  });

  it("schema accepts unknown props (no longer .strict())", () => {
    const r = FormProps.safeParse({ method: "POST" });
    expect(r.success).toBe(true);
  });

  it("accepts a required checkbox and a hint on any field", () => {
    // A consent tick is required; a number field carries helper text. Both
    // used to nuke the whole page (the checkbox variant forbade `required`,
    // no variant allowed `hint`), dropping it from the build.
    const r = FormProps.safeParse({
      workflow: "saveGuest",
      fields: [
        { kind: "checkbox", name: "vipFlag", label: "VIP guest", required: false },
        { kind: "number", name: "remedyValue", label: "Remedy value",
          required: false, hint: "Leave blank for apology-only remedies" },
        { kind: "switch", name: "active", label: "Active", required: true },
      ],
    });
    expect(r.success).toBe(true);
  });

  it("renders a field hint as helper text", () => {
    const { getByText } = render(
      <Form workflow="x" fields={[
        { kind: "text", name: "code", label: "Code", hint: "Six digits" },
      ]} />
    );
    expect(getByText("Six digits")).not.toBeNull();
  });

  it("renders children when fields is absent", () => {
    const { container } = render(
      <Form>
        <input data-testid="custom-input" name="title" />
      </Form>
    );
    expect(container.querySelector("[data-testid='custom-input']")).not.toBeNull();
    expect(container.querySelector("form")).not.toBeNull();
  });
});
