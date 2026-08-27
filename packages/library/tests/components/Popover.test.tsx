import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Popover } from "../../src/components/Popover/Popover";
import { PopoverProps } from "../../src/components/Popover/Popover.schema";

describe("Popover", () => {
  it("renders the trigger and reveals content on click", async () => {
    render(<Popover trigger="Open" title="Details" content="Hello world" />);
    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(await screen.findByText("Hello world")).toBeInTheDocument();
    expect(screen.getByText("Details")).toBeInTheDocument();
  });
  it("validates props", () => {
    expect(() => PopoverProps.parse({ trigger: "X", content: "Y" })).not.toThrow();
    expect(() => PopoverProps.parse({})).not.toThrow();
  });
});
