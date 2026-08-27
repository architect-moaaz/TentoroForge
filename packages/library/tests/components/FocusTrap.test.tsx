/**
 * FocusTrap — Spec E Wave 2 accessibility spine.
 *
 * Contract covered:
 *  - Renders a container that carries data-forge-focus-trap.
 *  - When active + autoFocus, moves focus to the first focusable
 *    descendant on mount.
 *  - Tab from the last focusable wraps to the first; Shift-Tab from
 *    the first wraps to the last.
 *  - On unmount, restores focus to the previously-focused element.
 *  - `active={false}` renders children but does not constrain focus.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, fireEvent, cleanup } from "@testing-library/react";
import * as React from "react";

import { FocusTrap } from "../../src/components/FocusTrap/FocusTrap";

function _tabKey(shift = false) {
  return { key: "Tab", code: "Tab", shiftKey: shift };
}

describe("FocusTrap", () => {
  let opener: HTMLButtonElement;

  beforeEach(() => {
    // A pre-existing element that should regain focus after unmount.
    opener = document.createElement("button");
    opener.textContent = "opener";
    document.body.appendChild(opener);
    opener.focus();
  });

  afterEach(() => {
    cleanup();
    if (opener.parentNode) opener.parentNode.removeChild(opener);
  });

  it("renders a container with data-forge-focus-trap='active'", () => {
    const { container } = render(
      <FocusTrap>
        <button>inside</button>
      </FocusTrap>,
    );
    const trap = container.querySelector("[data-forge-focus-trap]");
    expect(trap).not.toBeNull();
    expect(trap?.getAttribute("data-forge-focus-trap")).toBe("active");
  });

  it("focuses the first focusable descendant on mount", () => {
    const { getByText } = render(
      <FocusTrap>
        <button>first</button>
        <button>second</button>
      </FocusTrap>,
    );
    expect(document.activeElement).toBe(getByText("first"));
  });

  it("Tab from the last focusable wraps back to the first", () => {
    const { getByText, container } = render(
      <FocusTrap>
        <button>first</button>
        <button>second</button>
        <button>third</button>
      </FocusTrap>,
    );
    const trap = container.querySelector(
      "[data-forge-focus-trap]",
    ) as HTMLElement;
    const third = getByText("third");
    third.focus();
    expect(document.activeElement).toBe(third);
    fireEvent.keyDown(trap, _tabKey(false));
    expect(document.activeElement).toBe(getByText("first"));
  });

  it("Shift-Tab from the first focusable wraps to the last", () => {
    const { getByText, container } = render(
      <FocusTrap>
        <button>first</button>
        <button>second</button>
      </FocusTrap>,
    );
    const trap = container.querySelector(
      "[data-forge-focus-trap]",
    ) as HTMLElement;
    getByText("first").focus();
    fireEvent.keyDown(trap, _tabKey(true));
    expect(document.activeElement).toBe(getByText("second"));
  });

  it("restores focus to the previously-focused element on unmount", () => {
    const { unmount } = render(
      <FocusTrap>
        <button>inside</button>
      </FocusTrap>,
    );
    expect(document.activeElement).not.toBe(opener);
    unmount();
    expect(document.activeElement).toBe(opener);
  });

  it("active={false} renders children but does not steal focus", () => {
    render(
      <FocusTrap active={false}>
        <button>inside</button>
      </FocusTrap>,
    );
    // opener stays focused
    expect(document.activeElement).toBe(opener);
  });

  it("autoFocus={false} keeps prior focus while still trapping tabs", () => {
    render(
      <FocusTrap autoFocus={false}>
        <button>inside</button>
      </FocusTrap>,
    );
    expect(document.activeElement).toBe(opener);
  });
});
