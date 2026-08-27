import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Tooltip } from "../../src/components/Tooltip/Tooltip";
import { TooltipProps } from "../../src/components/Tooltip/Tooltip.schema";

describe("Tooltip", () => {
  it("renders the trigger label", () => {
    render(<Tooltip label="Hover me" content="Helpful hint" />);
    expect(screen.getByText("Hover me")).toBeInTheDocument();
  });
  it("shows the tooltip content on focus", async () => {
    render(<Tooltip label="Hover me" content="Helpful hint" />);
    await userEvent.tab(); // focus the trigger
    // Radix renders two copies of content: one visible, one a11y-hidden role="tooltip".
    // Use findByRole to target the semantic tooltip element unambiguously.
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Helpful hint");
  });
  it("validates props", () => {
    expect(() => TooltipProps.parse({ label: "X", content: "Y" })).not.toThrow();
    expect(() => TooltipProps.parse({})).not.toThrow();
  });
});
