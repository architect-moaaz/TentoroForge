import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ContextMenu } from "../../src/components/ContextMenu/ContextMenu";
import { ContextMenuProps } from "../../src/components/ContextMenu/ContextMenu.schema";

const items = [
  { label: "Copy", value: "copy" },
  { label: "Paste", value: "paste" },
];

describe("ContextMenu", () => {
  it("renders the labelled surface", () => {
    render(<ContextMenu label="Right-click here" items={items} />);
    expect(screen.getByText("Right-click here")).toBeInTheDocument();
  });
  it("opens on right-click and fires onSelect with the item value", async () => {
    const onSelect = vi.fn();
    render(<ContextMenu label="Right-click here" items={items} onSelect={onSelect} />);
    fireEvent.contextMenu(screen.getByText("Right-click here"));
    const paste = await screen.findByText("Paste");
    await userEvent.click(paste);
    expect(onSelect).toHaveBeenCalledWith("paste");
  });
  it("validates props", () => {
    expect(() => ContextMenuProps.parse({ label: "X", items })).not.toThrow();
    expect(() => ContextMenuProps.parse({})).not.toThrow();
  });
});
