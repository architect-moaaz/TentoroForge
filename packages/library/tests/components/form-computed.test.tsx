import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Form } from "../../src/components/Form/Form";

// S1b — reactive computed-field controller. A field with
// `interaction.computed.formula` recomputes live as its dependency fields change
// and renders read-only.

describe("Form — reactive computed fields", () => {
  it("recomputes totalCost live as rate / start / end change", async () => {
    render(
      <Form
        workflow="createRental"
        defaultValues={{ ratePerDay: "", startDate: "", endDate: "", totalCost: "" }}
        fields={[
          { kind: "number", name: "ratePerDay", label: "Rate Per Day" },
          { kind: "date", name: "startDate", label: "Start Date" },
          { kind: "date", name: "endDate", label: "End Date" },
          {
            kind: "number",
            name: "totalCost",
            label: "Total Cost",
            interaction: {
              computed: { formula: "ratePerDay * daysBetween(startDate, endDate)", readOnly: true },
            },
          },
        ]}
        __dispatch={vi.fn()}
      />,
    );

    const total = screen.getByLabelText("Total Cost") as HTMLInputElement;

    // rate=5, 2026-07-14 → 2026-07-18 is 4 days ⇒ 5 * 4 = 20.
    fireEvent.change(screen.getByLabelText("Rate Per Day"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Start Date"), { target: { value: "2026-07-14" } });
    fireEvent.change(screen.getByLabelText("End Date"), { target: { value: "2026-07-18" } });

    await waitFor(() => expect(total.value).toBe("20"));

    // Change a dependency ⇒ the derived value updates visibly.
    fireEvent.change(screen.getByLabelText("Rate Per Day"), { target: { value: "10" } });
    await waitFor(() => expect(total.value).toBe("40"));

    // Shorten the range (14 → 16 = 2 days) ⇒ 10 * 2 = 20.
    fireEvent.change(screen.getByLabelText("End Date"), { target: { value: "2026-07-16" } });
    await waitFor(() => expect(total.value).toBe("20"));
  });

  it("cascades a chain (qty,unitPrice → subtotal → subtotal+tax = total) in one pass", async () => {
    render(
      <Form
        workflow="createOrder"
        defaultValues={{ qty: "", unitPrice: "", tax: "", subtotal: "", total: "" }}
        fields={[
          { kind: "number", name: "qty", label: "Qty" },
          { kind: "number", name: "unitPrice", label: "Unit Price" },
          { kind: "number", name: "tax", label: "Tax" },
          {
            kind: "number",
            name: "subtotal",
            label: "Subtotal",
            interaction: { computed: { formula: "qty * unitPrice", readOnly: true } },
          },
          {
            kind: "number",
            name: "total",
            label: "Total",
            interaction: { computed: { formula: "subtotal + tax", readOnly: true } },
          },
        ]}
        __dispatch={vi.fn()}
      />,
    );

    const subtotal = screen.getByLabelText("Subtotal") as HTMLInputElement;
    const total = screen.getByLabelText("Total") as HTMLInputElement;

    fireEvent.change(screen.getByLabelText("Qty"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Unit Price"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Tax"), { target: { value: "5" } });

    // subtotal = 2*3 = 6 ; total = 6 + 5 = 11 — the chain resolves through one pass.
    await waitFor(() => {
      expect(subtotal.value).toBe("6");
      expect(total.value).toBe("11");
    });

    // A single edit to qty cascades subtotal → total together.
    fireEvent.change(screen.getByLabelText("Qty"), { target: { value: "4" } });
    await waitFor(() => {
      expect(subtotal.value).toBe("12");
      expect(total.value).toBe("17");
    });
  });

  it("renders the computed field read-only (user cannot type into it)", async () => {
    render(
      <Form
        workflow="createRental"
        defaultValues={{ ratePerDay: "4", startDate: "2026-07-14", endDate: "2026-07-16", totalCost: "" }}
        fields={[
          { kind: "number", name: "ratePerDay", label: "Rate Per Day" },
          { kind: "date", name: "startDate", label: "Start Date" },
          { kind: "date", name: "endDate", label: "End Date" },
          {
            kind: "number",
            name: "totalCost",
            label: "Total Cost",
            interaction: { computed: { formula: "ratePerDay * daysBetween(startDate, endDate)", readOnly: true } },
          },
        ]}
        __dispatch={vi.fn()}
      />,
    );

    const total = screen.getByLabelText("Total Cost") as HTMLInputElement;
    await waitFor(() => expect(total.value).toBe("8")); // 4 * 2 days
    expect(total).toHaveAttribute("readonly");

    // Typing does nothing — the value stays the derived one.
    await userEvent.type(total, "999");
    expect(total.value).toBe("8");
  });

  it("regression: a plain form with no interaction submits normally", async () => {
    const dispatch = vi.fn();
    render(
      <Form
        workflow="createProduct"
        defaultValues={{ name: "" }}
        fields={[{ kind: "text", name: "name", label: "Name", required: true }]}
        __dispatch={dispatch}
      />,
    );
    await userEvent.type(screen.getByLabelText("Name"), "Widget");
    await userEvent.click(screen.getByRole("button", { name: /save|submit/i }));
    expect(dispatch).toHaveBeenCalledWith("createProduct", { name: "Widget" });
  });
});
