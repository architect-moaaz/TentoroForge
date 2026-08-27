import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Menubar } from "../../src/components/Menubar/Menubar";
import { MenubarProps } from "../../src/components/Menubar/Menubar.schema";

const menus = [
  { label: "File", items: [{ label: "New", value: "file.new" }, { label: "Open", value: "file.open" }] },
  { label: "Edit", items: [{ label: "Undo", value: "edit.undo" }] },
];

describe("Menubar", () => {
  it("renders each menu label", () => {
    render(<Menubar menus={menus} />);
    expect(screen.getByText("File")).toBeInTheDocument();
    expect(screen.getByText("Edit")).toBeInTheDocument();
  });
  it("opens a menu and fires onSelect with the item value", async () => {
    const onSelect = vi.fn();
    render(<Menubar menus={menus} onSelect={onSelect} />);
    await userEvent.click(screen.getByText("File"));
    const open = await screen.findByText("Open");
    await userEvent.click(open);
    expect(onSelect).toHaveBeenCalledWith("file.open");
  });
  it("validates props", () => {
    expect(() => MenubarProps.parse({ menus })).not.toThrow();
    expect(() => MenubarProps.parse({})).not.toThrow();
  });
});
