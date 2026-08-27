/**
 * AutoFocus — Spec E Wave 2 accessibility spine.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, cleanup, act } from "@testing-library/react";
import * as React from "react";

import { AutoFocus } from "../../src/components/AutoFocus/AutoFocus";

describe("AutoFocus", () => {
  beforeEach(() => {
    // Reset focus before each test — otherwise the microtask focus may
    // race against the previous test's focus state.
    (document.activeElement as HTMLElement | null)?.blur?.();
  });
  afterEach(() => cleanup());

  it("focuses the first focusable descendant on mount (immediate)", () => {
    const { getByText } = render(
      <AutoFocus delayed={false}>
        <button>first</button>
        <button>second</button>
      </AutoFocus>,
    );
    expect(document.activeElement).toBe(getByText("first"));
  });

  it("honours a selector prop, preferring its match", () => {
    const { getByText } = render(
      <AutoFocus selector=".target" delayed={false}>
        <button>ignored</button>
        <button className="target">target</button>
      </AutoFocus>,
    );
    expect(document.activeElement).toBe(getByText("target"));
  });

  it("falls back to first focusable when selector doesn't match", () => {
    const { getByText } = render(
      <AutoFocus selector=".nope" delayed={false}>
        <button>a</button>
        <button>b</button>
      </AutoFocus>,
    );
    expect(document.activeElement).toBe(getByText("a"));
  });

  it("enabled={false} does not steal focus", () => {
    const before = document.activeElement;
    render(
      <AutoFocus enabled={false} delayed={false}>
        <button>x</button>
      </AutoFocus>,
    );
    expect(document.activeElement).toBe(before);
  });

  it("uses display:contents so it does not affect layout", () => {
    const { container } = render(
      <AutoFocus delayed={false}>
        <button>x</button>
      </AutoFocus>,
    );
    const wrapper = container.querySelector(
      "[data-forge-autofocus]",
    ) as HTMLElement;
    expect(wrapper.style.display).toBe("contents");
  });
});
