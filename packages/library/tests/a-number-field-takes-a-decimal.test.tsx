import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { Form } from "../src/components/Form/Form";

describe("a number field takes a decimal", () => {
  it("renders the number input with step=any", () => {
    // A guest asked for 88.50 back and the browser refused the form before
    // submit ran: an <input type="number"> with no step accepts whole
    // numbers only. Money is not whole.
    const { container } = render(
      <Form workflow="FLOW-001" fields={[
        { kind: "number", name: "amountRequested", label: "Amount Requested", required: true },
        { kind: "text", name: "guestName", label: "Guest Name" },
      ]} />,
    );
    const amount = container.querySelector('input[name="amountRequested"]') as HTMLInputElement;
    expect(amount.type).toBe("number");
    expect(amount.getAttribute("step")).toBe("any");
    const name = container.querySelector('input[name="guestName"]') as HTMLInputElement;
    expect(name.getAttribute("step")).toBeNull();
  });
});
