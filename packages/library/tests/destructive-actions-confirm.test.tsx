import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { Button } from "../src/components/Button/Button";
import { Table, confirmDestructive } from "../src/components/Table/Table";

// "Delete Record, with a confirmation prompt before deletion" — asked for in
// every brief, promised by the composition conventions, and a `danger` action
// ran on the click. The platform confirms once, for every destructive control.
afterEach(() => vi.restoreAllMocks());

describe("a destructive control asks before it dispatches", () => {
  it("a danger Button dispatches only when confirmed", () => {
    const dispatch = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const { container } = render(
      <Button label="Delete Record" variant="danger" workflow="FLOW-003" args={{ record: "abc-1" }} __dispatch={dispatch} />,
    );
    fireEvent.click(container.querySelector("button")!);
    expect(dispatch).not.toHaveBeenCalled();
    (window.confirm as ReturnType<typeof vi.fn>).mockReturnValue(true);
    fireEvent.click(container.querySelector("button")!);
    expect(dispatch).toHaveBeenCalledWith("FLOW-003", { record: "abc-1" });
    expect(window.confirm).toHaveBeenLastCalledWith("Delete Record? This cannot be undone.");
  });

  it("a danger row action names the row and dispatches only when confirmed", async () => {
    const dispatch = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const { getAllByText } = render(
      <Table
        columns={[{ key: "fullName", label: "Name" }]}
        rows={[{ id: "n-1", fullName: "Amara Okonkwo" }]}
        rowActions={[{ label: "Delete", workflow: "FLOW-003", variant: "danger" }]}
        __dispatch={dispatch}
      />,
    );
    fireEvent.click(getAllByText("Delete")[0]);
    expect(dispatch).not.toHaveBeenCalled();
    expect(window.confirm).toHaveBeenCalledWith('Delete "Amara Okonkwo"? This cannot be undone.');
    (window.confirm as ReturnType<typeof vi.fn>).mockReturnValue(true);
    fireEvent.click(getAllByText("Delete")[0]);
    await new Promise((r) => setTimeout(r, 0));
    expect(dispatch).toHaveBeenCalledWith("FLOW-003", { id: "n-1" });
  });

  it("a non-destructive action never asks, and a host without a window proceeds", () => {
    const confirm = vi.spyOn(window, "confirm");
    const dispatch = vi.fn();
    const { container } = render(<Button label="Approve" workflow="FLOW-009" __dispatch={dispatch} />);
    fireEvent.click(container.querySelector("button")!);
    expect(confirm).not.toHaveBeenCalled();
    expect(dispatch).toHaveBeenCalled();
    confirm.mockReturnValue(true);
    expect(confirmDestructive("Delete", { id: "x" })).toBe(true);
    expect(confirm).toHaveBeenLastCalledWith('Delete "x"? This cannot be undone.');
  });
});
