import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DropdownMenu } from "../../src/components/DropdownMenu/DropdownMenu";
import { DropdownMenuProps } from "../../src/components/DropdownMenu/DropdownMenu.schema";

const items = [
  { label: "Edit", value: "edit" },
  { label: "Delete", value: "delete" },
];

describe("DropdownMenu", () => {
  it("renders the trigger label", () => {
    render(<DropdownMenu trigger="Actions" items={items} />);
    expect(screen.getByRole("button", { name: "Actions" })).toBeInTheDocument();
  });
  it("opens on trigger click and shows items, selecting fires onSelect with value", async () => {
    const onSelect = vi.fn();
    render(<DropdownMenu trigger="Actions" items={items} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole("button", { name: "Actions" }));
    const del = await screen.findByText("Delete");
    await userEvent.click(del);
    expect(onSelect).toHaveBeenCalledWith("delete");
  });
  it("validates props via DropdownMenuProps", () => {
    expect(() => DropdownMenuProps.parse({ trigger: "X", items })).not.toThrow();
    expect(() => DropdownMenuProps.parse({})).not.toThrow();
  });
});
