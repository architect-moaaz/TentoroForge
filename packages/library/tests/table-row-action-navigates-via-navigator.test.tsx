import { describe, it, expect, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { NavigatorProvider } from "@tentoroforge/renderer";
import { Table } from "../src/components/Table/Table";

// A row action's `navigate` used `window.location.assign` while the empty-state
// action and the row link went through the Navigator. The preview scaffold
// serves an app under `/p/<id>` and provides a Navigator that knows it — the
// hard assign escaped that base path and a row's Edit reached a 404 there.
describe("Table — a row action navigates through the host's Navigator", () => {
  it("pushes the templated route on the navigator, not the window", () => {
    const push = vi.fn();
    const { getAllByText } = render(
      <NavigatorProvider value={{ push, replace: vi.fn(), back: vi.fn(), refresh: vi.fn() }}>
        <Table
          columns={[{ key: "fullName", label: "Name" }]}
          rows={[{ id: "n-1", fullName: "Amara Okonkwo" }]}
          rowActions={[{ label: "Edit", navigate: "/nurse-registration/{{id}}" }]}
        />
      </NavigatorProvider>,
    );
    fireEvent.click(getAllByText("Edit")[0]);
    expect(push).toHaveBeenCalledWith("/nurse-registration/n-1");
  });
});
