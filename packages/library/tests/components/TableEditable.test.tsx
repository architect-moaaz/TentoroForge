/**
 * Table.editable — Spec E Wave 3.
 *
 * Covers: click-to-edit opens an input, Enter commits + shows the
 * Save-all toolbar, Escape reverts, and Save all emits a
 * `forge:row:update` event per dirty row.
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import * as React from "react";

import { Table } from "../../src/components/Table/Table";

const columns = [
  { key: "name", label: "Name" },
  { key: "role", label: "Role" },
];
const rows = [
  { id: "u1", name: "Ada", role: "engineer" },
  { id: "u2", name: "Grace", role: "admiral" },
];

describe("Table editable", () => {
  afterEach(() => cleanup());

  it("does not show inputs when editableColumns is unset", () => {
    const { container } = render(
      <Table columns={columns} rows={rows} />,
    );
    expect(container.querySelector("[data-forge-editable-cell]")).toBeNull();
    expect(container.querySelector("[data-forge-table-edit-toolbar]")).toBeNull();
  });

  it("click on an editable cell opens an input; Enter commits and shows Save-all", () => {
    const { container, getByText } = render(
      <Table columns={columns} rows={rows} editableColumns={["name"]} />,
    );
    // Click the cell showing "Ada".
    fireEvent.click(getByText("Ada"));
    const input = container.querySelector<HTMLInputElement>("[data-forge-editable-cell]");
    expect(input).not.toBeNull();
    fireEvent.change(input!, { target: { value: "Ada L." } });
    fireEvent.keyDown(input!, { key: "Enter" });
    expect(container.querySelector("[data-forge-table-edit-toolbar]")).not.toBeNull();
  });

  it("Escape reverts the edit and does not mark the row dirty", () => {
    const { container, getByText } = render(
      <Table columns={columns} rows={rows} editableColumns={["name"]} />,
    );
    fireEvent.click(getByText("Ada"));
    const input = container.querySelector<HTMLInputElement>("[data-forge-editable-cell]")!;
    fireEvent.change(input, { target: { value: "ZZZ" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(container.querySelector("[data-forge-table-edit-toolbar]")).toBeNull();
  });

  it("Save all emits forge:row:update for each dirty row", () => {
    const spy = vi.fn();
    const handler = (e: Event) => spy((e as CustomEvent).detail);
    window.addEventListener("forge:row:update", handler);

    const { container, getByText } = render(
      <Table columns={columns} rows={rows} editableColumns={["name"]} />,
    );
    fireEvent.click(getByText("Ada"));
    const input = container.querySelector<HTMLInputElement>("[data-forge-editable-cell]")!;
    fireEvent.change(input, { target: { value: "Ada L." } });
    fireEvent.keyDown(input, { key: "Enter" });

    const saveBtn = container.querySelector<HTMLButtonElement>("[data-forge-table-save-all]")!;
    fireEvent.click(saveBtn);

    expect(spy).toHaveBeenCalled();
    expect(spy.mock.calls[0][0]).toMatchObject({ id: "u1", patch: { name: "Ada L." } });
    window.removeEventListener("forge:row:update", handler);
  });
});
