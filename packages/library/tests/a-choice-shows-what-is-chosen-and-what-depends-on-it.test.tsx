import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import React from "react";
import { Form } from "../src/components/Form/Form";

const fields: any[] = [
  { kind: "choice", name: "orderType", label: "How", options: [
      { value: "dine_in", label: "Dine-in" }, { value: "delivery", label: "Delivery" }] },
  { kind: "text", name: "tableNumber", label: "Table number", interaction: { visibleIf: "orderType == 'dine_in'" } },
  { kind: "text", name: "deliveryAddress", label: "Delivery address", interaction: { visibleIf: "orderType == 'delivery'" } },
];
const button = (c: HTMLElement, label: string) =>
  [...c.querySelectorAll("button")].find((b) => b.textContent === label) as HTMLButtonElement;

describe("an either/or choice", () => {
  it("loads with the first option selected and only its field shown", () => {
    const { container } = render(<Form workflow="F" fields={fields} />);
    expect(button(container, "Dine-in").getAttribute("aria-pressed")).toBe("true");
    expect(button(container, "Delivery").getAttribute("aria-pressed")).toBe("false");
    expect(container.querySelector('input[name="tableNumber"]')).not.toBeNull();
    expect(container.querySelector('input[name="deliveryAddress"]')).toBeNull();
  });
  it("flips the selected state and swaps the dependent field when the other is pressed", () => {
    const { container } = render(<Form workflow="F" fields={fields} />);
    fireEvent.click(button(container, "Delivery"));
    expect(button(container, "Delivery").getAttribute("aria-pressed")).toBe("true");
    expect(button(container, "Dine-in").getAttribute("aria-pressed")).toBe("false");
    expect(container.querySelector('input[name="deliveryAddress"]')).not.toBeNull();
    expect(container.querySelector('input[name="tableNumber"]')).toBeNull();
  });
});
