/**
 * SplitView — Spec E Wave 3.
 *
 * Covers: master/detail slot binding, URL selection sync, and
 * delegation of clicks on `data-forge-split-id` descendants.
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

  it("renders the master slot and shows empty text before selection", () => {
    const { getByText } = render(
      <SplitView emptyText="Nothing selected">
        <ul><li data-forge-split-id="1">Row A</li></ul>
        <div>Detail body</div>
      </SplitView>
    );
    getByText("Row A");
    getByText("Nothing selected");
  });

  it("clicking a row updates the URL and shows the detail slot", () => {
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
