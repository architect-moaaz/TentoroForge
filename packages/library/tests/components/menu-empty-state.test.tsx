import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DropdownMenu } from "../../src/components/DropdownMenu/DropdownMenu";
import { ContextMenu } from "../../src/components/ContextMenu/ContextMenu";
import { Menubar } from "../../src/components/Menubar/Menubar";

/**
 * One test file for one shared defect: a Radix-backed menu with no items opened
 * a 160x10px white sliver with `childElementCount === 0` — indistinguishable
 * from broken or still-loading. All three menus now render the same
 * MenuEmptyNote behind the same `length === 0` test, so they are pinned
 * together; a fourth menu that forgets it belongs in this list.
 */

describe("empty menus say so", () => {
  it("DropdownMenu with no items shows the note instead of a blank box", async () => {
    render(<DropdownMenu trigger="Actions" items={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "Actions" }));
    const note = await screen.findByText("No menu items");
    expect(note).toHaveAttribute("data-menu-empty");
  });

  it("ContextMenu with no items shows the note", async () => {
    render(<ContextMenu label="Right-click here" items={[]} />);
    fireEvent.contextMenu(screen.getByText("Right-click here"));
    expect(await screen.findByText("No menu items")).toHaveAttribute("data-menu-empty");
  });

  it("Menubar with no menus renders a labelled bar, not a bare line", () => {
    const { container } = render(<Menubar menus={[]} />);
    expect(screen.getByText("No menus")).toHaveAttribute("data-menu-empty");
    expect(container.querySelector("[data-menubar]")?.childElementCount).toBeGreaterThan(0);
  });

  it("Menubar menu with no items shows the note when opened", async () => {
    render(<Menubar menus={[{ label: "File", items: [] }]} />);
    await userEvent.click(screen.getByText("File"));
    expect(await screen.findByText("No menu items")).toBeInTheDocument();
  });

  it("the note is inert — it is not a selectable menu item", async () => {
    render(<DropdownMenu trigger="Actions" items={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "Actions" }));
    const note = await screen.findByText("No menu items");
    expect(note.getAttribute("role")).toBe("presentation");
    expect(note.closest("[role='menuitem']")).toBeNull();
  });
});
