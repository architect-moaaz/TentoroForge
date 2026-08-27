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
