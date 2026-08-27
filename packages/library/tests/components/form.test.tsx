import { describe, it, expect, vi } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Form } from "../../src/components/Form/Form";

describe("Form", () => {
  it("submits values to the workflow on submit", async () => {
    const dispatch = vi.fn();
    render(
      <Form
        workflow="createProduct"
        defaultValues={{ name: "" }}
        fields={[{ kind: "text", name: "name", label: "Name", required: true }]}
        __dispatch={dispatch}
      />
    );
    await userEvent.type(screen.getByLabelText("Name"), "Widget");
    await userEvent.click(screen.getByRole("button", { name: /save|submit/i }));
    expect(dispatch).toHaveBeenCalledWith("createProduct", { name: "Widget" });
  });

  it("disables the submit button while the workflow dispatch is in flight", async () => {
    let resolveDispatch!: () => void;
    const pending = new Promise<void>((r) => {
      resolveDispatch = r;
    });
    const dispatch = vi.fn(() => pending);
    render(
      <Form
        workflow="createProduct"
        fields={[{ kind: "text", name: "name", label: "Name", required: true }]}
        __dispatch={dispatch}
      />
    );
    await userEvent.type(screen.getByLabelText("Name"), "Widget");
    const submit = screen.getByRole("button", { name: /save|submit/i });
    await userEvent.click(submit);

    expect(dispatch).toHaveBeenCalledWith("createProduct", { name: "Widget" });
    expect(submit).toBeDisabled();

    await act(async () => {
      resolveDispatch();
      await pending;
    });
    await waitFor(() => expect(submit).not.toBeDisabled());
  });

  it("renders field labels at the design type-scale caption size (not hardcoded text-sm)", () => {
    render(
      <Form
        workflow="x"
        fields={[{ kind: "text", name: "name", label: "Name", required: true }]}
        __dispatch={vi.fn()}
      />
    );
    const label = screen.getByText("Name");
    expect(label.tagName).toBe("LABEL");
    expect(label.className).toContain("text-caption");
    expect(label.className).not.toContain("text-sm");
  });

  it("blocks submit when required field empty", async () => {
    const dispatch = vi.fn();
    render(
      <Form
        workflow="x"
        fields={[{ kind: "text", name: "name", label: "Name", required: true }]}
        __dispatch={dispatch}
      />
    );
    await userEvent.click(screen.getByRole("button"));
    expect(dispatch).not.toHaveBeenCalled();
    expect(screen.getByText(/required/i)).toBeInTheDocument();
  });
});
