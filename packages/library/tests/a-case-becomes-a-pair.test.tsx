import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { KeyValueList } from "../src/components/KeyValueList/KeyValueList";
import { asKeyValue } from "../src/style/rowShape";

describe("a data row becomes a key-value pair", () => {
  // The dashboard's Complaints & tickets card was bound to the property's
  // support cases and showed "— —".
  it("labels a support case by its number and values it by its status", () => {
    expect(asKeyValue({ id: "s1", caseNumber: "SC-STG-0001", subject: "Noise", status: "Open", caseType: "Complaint" }))
      .toEqual({ label: "Noise", value: "Open" });
  });
  it("keeps an authored pair", () => {
    expect(asKeyValue({ label: "PSP reference", value: "ABC", copyable: true })).toEqual({ label: "PSP reference", value: "ABC", copyable: true });
  });
  it("renders shaped rows", () => {
    const { container } = render(<KeyValueList items={[{ caseNumber: "SC-STG-0002", status: "In progress" }] as any} />);
    expect(container.textContent).toContain("SC-STG-0002");
    expect(container.textContent).toContain("In progress");
  });
});
