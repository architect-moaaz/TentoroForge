import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ValidationChecklist } from "../../src/components/ValidationChecklist/ValidationChecklist";
import { ValidationChecklistProps } from "../../src/components/ValidationChecklist/ValidationChecklist.schema";

const items = [
  { label: "Valid RFID", valid: true },
  { label: "Approved Vendor", valid: true },
  { label: "Active Permit", valid: true },
  { label: "Valid EID", valid: false },
];

describe("ValidationChecklist", () => {
  it("renders every item label", () => {
    render(<ValidationChecklist items={items} />);
    for (const it of items) expect(screen.getByText(it.label)).toBeInTheDocument();
  });
  it("marks each item valid/invalid via a data attribute", () => {
    render(<ValidationChecklist items={items} />);
    expect(screen.getByText("Valid RFID").closest("[data-valid]")?.getAttribute("data-valid")).toBe("true");
    expect(screen.getByText("Valid EID").closest("[data-valid]")?.getAttribute("data-valid")).toBe("false");
  });
  it("reflects orientation in a data attribute", () => {
    const { container } = render(<ValidationChecklist orientation="horizontal" items={items} />);
    expect(container.querySelector("[data-validation-checklist]")?.getAttribute("data-orientation")).toBe("horizontal");
  });
  it("validates props", () => {
    expect(() => ValidationChecklistProps.parse({ items })).not.toThrow();
    expect(() => ValidationChecklistProps.parse({})).not.toThrow();
  });
});
