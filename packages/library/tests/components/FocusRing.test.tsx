/**
 * FocusRing — Spec E Wave 2 accessibility spine.
 */
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { FocusRing } from "../../src/components/FocusRing/FocusRing";

describe("FocusRing", () => {
  afterEach(() => cleanup());

  it("renders children unchanged with data-forge-focus-ring", () => {
    const { getByText, container } = render(
      <FocusRing>
        <button>click me</button>
      </FocusRing>,
    );
    expect(getByText("click me")).toBeInTheDocument();
    expect(container.querySelector("[data-forge-focus-ring]")).not.toBeNull();
  });

  it("does not alter layout (display:contents)", () => {
    const { container } = render(
      <FocusRing>
        <span>x</span>
      </FocusRing>,
    );
    const wrapper = container.querySelector(
      "[data-forge-focus-ring]",
    ) as HTMLElement;
    expect(wrapper.style.display).toBe("contents");
  });

  it("passes color/width/offset as CSS custom properties", () => {
    const { container } = render(
      <FocusRing color="hotpink" width={3} offset={4}>
        <button>x</button>
      </FocusRing>,
    );
    const wrapper = container.querySelector(
      "[data-forge-focus-ring]",
    ) as HTMLElement;
    // Inline style becomes CSS text with -- vars
    const cssText = wrapper.getAttribute("style") ?? "";
    expect(cssText).toContain("--focus-ring-color: hotpink");
    expect(cssText).toContain("--focus-ring-width: 3px");
    expect(cssText).toContain("--focus-ring-offset: 4px");
  });
});
