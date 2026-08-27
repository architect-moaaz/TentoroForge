import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Drawer } from "../../src/components/Drawer/Drawer";
import { DrawerProps } from "../../src/components/Drawer/Drawer.schema";

describe("Drawer", () => {
  it("renders the trigger and opens the panel on click", async () => {
    render(<Drawer trigger="Open panel" title="Settings" side="right" content="Panel body" />);
    expect(screen.getByRole("button", { name: "Open panel" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open panel" }));
    expect(await screen.findByText("Panel body")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });
  it("anchors the panel to the requested side", async () => {
    render(<Drawer trigger="Open" title="T" side="left" content="Body" />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    const panel = await screen.findByRole("dialog");
    expect(panel).toHaveAttribute("data-side", "left");
  });
  it("validates props", () => {
    expect(() => DrawerProps.parse({ trigger: "X", content: "Y" })).not.toThrow();
    expect(() => DrawerProps.parse({})).not.toThrow();
  });
});
