import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KeyboardHelp } from "../../src/chrome/KeyboardHelp";

describe("KeyboardHelp", () => {
  it("renders nothing when closed", () => {
    render(<KeyboardHelp open={false} onClose={() => {}} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders shortcuts dialog when open", () => {
    render(<KeyboardHelp open={true} onClose={() => {}} />);
    expect(screen.getByRole("dialog", { name: /keyboard shortcuts/i })).toBeInTheDocument();
    // Check the Save shortcut appears in the shortcuts list
    expect(screen.getByText("Save")).toBeInTheDocument();
  });

  it("calls onClose when backdrop is clicked", async () => {
    const onClose = vi.fn();
    render(<KeyboardHelp open={true} onClose={onClose} />);
    const dialog = screen.getByRole("dialog");
    await userEvent.click(dialog);
    expect(onClose).toHaveBeenCalled();
  });
});
