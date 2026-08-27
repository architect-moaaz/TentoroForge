import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Form } from "../../src/components/Form/Form";

describe("Form radio + switch field kinds", () => {
  it("collects radio and switch values into the workflow payload", async () => {
    const dispatch = vi.fn();
    render(
      <Form workflow="save" defaultValues={{ plan: "pro", active: false }}
        fields={[
          { kind: "radio", name: "plan", label: "Plan", options: [{ value: "free", label: "Free" }, { value: "pro", label: "Pro" }] },
          { kind: "switch", name: "active", label: "Active" },
        ]}
        __dispatch={dispatch} />
    );
    await userEvent.click(screen.getByRole("switch", { name: "Active" }));
    await userEvent.click(screen.getByRole("button", { name: /save|submit/i }));
    expect(dispatch).toHaveBeenCalledWith("save", { plan: "pro", active: true });
  });
});
