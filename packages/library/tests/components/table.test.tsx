import { describe, it, expect, vi } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Table } from "../../src/components/Table/Table";

const columns = [{ key: "name", label: "Name" }];
const rows = [
  { id: "r1", name: "Alpha" },
  { id: "r2", name: "Beta" },
];

describe("Table row-actions — in-flight state", () => {
  it("dispatches the row-action workflow with the row id via injected dispatcher", async () => {
    const dispatch = vi.fn();
    render(
      <Table
        columns={columns}
        rows={rows}
        rowActions={[{ label: "Process Return", workflow: "processReturn" }]}
        __dispatch={dispatch}
      />,
    );
    const buttons = screen.getAllByRole("button", { name: "Process Return" });
    await userEvent.click(buttons[0]);
    expect(dispatch).toHaveBeenCalledWith("processReturn", { id: "r1" });
  });

  it("disables the row-action button while the dispatch promise is in flight, re-enables after resolve", async () => {
    let resolveDispatch!: () => void;
    const pending = new Promise<void>((r) => {
      resolveDispatch = r;
    });
    const dispatch = vi.fn(() => pending);
    render(
      <Table
        columns={columns}
        rows={rows}
        rowActions={[{ label: "Confirm Pickup", workflow: "confirmPickup" }]}
        __dispatch={dispatch}
      />,
    );
    const btn = screen.getAllByRole("button", { name: /Confirm Pickup|…/ })[0];

    await userEvent.click(btn);
    expect(dispatch).toHaveBeenCalledWith("confirmPickup", { id: "r1" });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-busy", "true");

    await act(async () => {
      resolveDispatch();
      await pending;
    });
    await waitFor(() => expect(btn).not.toBeDisabled());
    expect(btn).not.toHaveAttribute("aria-busy", "true");
  });

  it("does not dispatch twice on a second click while a dispatch is already in flight", async () => {
    const pending = new Promise<void>(() => {});
    const dispatch = vi.fn(() => pending);
    render(
      <Table
        columns={columns}
        rows={rows}
        rowActions={[{ label: "Process Return", workflow: "processReturn" }]}
        __dispatch={dispatch}
      />,
    );
    const btn = screen.getAllByRole("button", { name: /Process Return|…/ })[0];
    await userEvent.click(btn);
    await userEvent.click(btn);
    expect(dispatch).toHaveBeenCalledTimes(1);
  });

  it("tracks busy state per row+action — one row's in-flight action does not disable another row's button", async () => {
    const pending = new Promise<void>(() => {});
    const dispatch = vi.fn(() => pending);
    render(
      <Table
        columns={columns}
        rows={rows}
        rowActions={[{ label: "Process Return", workflow: "processReturn" }]}
        __dispatch={dispatch}
      />,
    );
    const buttons = screen.getAllByRole("button", { name: /Process Return|…/ });
    await userEvent.click(buttons[0]);
    expect(buttons[0]).toBeDisabled();
    // second row's button remains clickable
    expect(buttons[1]).not.toBeDisabled();
  });
});
