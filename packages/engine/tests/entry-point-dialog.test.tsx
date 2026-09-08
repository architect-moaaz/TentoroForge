import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Engine } from "../src/Engine";

/**
 * The end-to-end path a Figma entry point takes: a Button with `opensDialog`
 * and a sibling Dialog holding a Form. The Engine's delegated [data-dialog-open]
 * click handler must open the sibling Dialog — this is what a "+ New Case"
 * button does in a generated app, and what did not fire in the browser.
 */
describe("an entry-point button opens its sibling dialog", () => {
  const schema = {
    schemaVersion: "2" as const,
    id: "dashboard",
    root: {
      type: "Stack",
      id: "root",
      children: [
        {
          type: "Button",
          id: "opener",
          props: { label: "+ New Case", opensDialog: "new-case" },
        },
        {
          type: "Dialog",
          id: "dlg",
          props: { id: "new-case", title: "New Case" },
          children: [
            {
              type: "Form",
              id: "form",
              props: {
                workflow: "FLOW-011",
                submitLabel: "New Case",
                fields: [
                  { kind: "select", name: "caseType", label: "Case type",
                    options: [{ value: "Refund", label: "Refund" }] },
                  { kind: "select", name: "propertyId", label: "Property", options: [],
                    interaction: { optionsFrom: { source: "properties", value: "id", label: "name" } } },
                ],
              },
            },
          ],
        },
      ],
    },
  };

  it("opens the dialog on click and shows the form", async () => {
    render(<Engine schema={schema} previewData={{}} />);

    expect(screen.queryByText("Case type")).toBeNull();

    (screen.getByText("+ New Case").closest("button") as HTMLButtonElement).click();

    // The dialog opened and mounted its form.
    expect(await screen.findByText("Case type")).toBeTruthy();
    expect(screen.getByText("Property")).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
});
