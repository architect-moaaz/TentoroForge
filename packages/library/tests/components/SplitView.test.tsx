/**
 * SplitView — Spec E Wave 3.
 *
 * Covers: master/detail slot binding, URL selection sync, delegation of clicks
 * on `data-forge-split-id` descendants, and the child contract — every child
 * has to end up somewhere on screen.
 */
import { describe, it, expect, afterEach, beforeEach } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import * as React from "react";

import { SplitView } from "../../src/components/SplitView/SplitView";

describe("SplitView", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });
  afterEach(() => cleanup());

  it("renders both panes with no selection in the URL", () => {
    // The editor never puts `?selected=` on the preview URL, so gating the
    // detail pane on it hid the second child and everything inside it —
    // docs/editor-audit/containment.md #2, 117 of 133 child pairs lost.
    const { getByText } = render(
      <SplitView emptyText="Nothing selected">
        <ul><li data-forge-split-id="1">Row A</li></ul>
        <div>Detail body</div>
      </SplitView>
    );
    getByText("Row A");
    getByText("Detail body");
  });

  it("shows emptyText only when there is no detail child", () => {
    const { getByText, queryByText } = render(
      <SplitView emptyText="Nothing selected">
        <ul><li>Row A</li></ul>
      </SplitView>
    );
    getByText("Nothing selected");
    expect(queryByText("Detail body")).toBeNull();
  });

  it("requireSelection restores the pick-a-row-first gate", () => {
    const { getByText, queryByText } = render(
      <SplitView emptyText="Nothing selected" requireSelection>
        <ul><li data-forge-split-id="1">Row A</li></ul>
        <div>Detail body</div>
      </SplitView>
    );
    getByText("Nothing selected");
    expect(queryByText("Detail body")).toBeNull();
    fireEvent.click(getByText("Row A"));
    getByText("Detail body");
  });

  it("keeps children beyond the second in the detail pane", () => {
    // No maxChildren existed on the registry entry, so any number of children
    // could be dropped in; everything past kids[1] used to vanish silently.
    const { container } = render(
      <SplitView>
        <div>Master</div>
        <div>Detail one</div>
        <div>Detail two</div>
      </SplitView>
    );
    const detail = container.querySelector("[data-forge-split-detail]")!;
    expect(detail.textContent).toContain("Detail one");
    expect(detail.textContent).toContain("Detail two");
  });

  it("clicking a row updates the URL and marks the selection", () => {
    const { getByText, container } = render(
      <SplitView>
        <ul><li data-forge-split-id="42">Row 42</li></ul>
        <div>Detail here</div>
      </SplitView>
    );
    fireEvent.click(getByText("Row 42"));
    getByText("Detail here");
    const params = new URLSearchParams(window.location.search);
    expect(params.get("selected")).toBe("42");
    expect(container.querySelector("[data-forge-split-selected='42']")).not.toBeNull();
  });
});
