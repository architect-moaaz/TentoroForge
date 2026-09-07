/**
 * Divider — the two defects from docs/editor-audit/containment.md:
 * `thickness` was a live select the component did not accept, and the
 * drop-derived width overwrote the vertical hairline.
 */
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import * as React from "react";

import { Divider } from "../../src/components/Divider/Divider";

function rule(container: HTMLElement): HTMLElement {
  return container.querySelector("hr")!;
}

describe("Divider", () => {
  afterEach(() => cleanup());

  it("maps thickness to a real stroke on the horizontal axis", () => {
    for (const [t, px] of [["thin", "1px"], ["medium", "2px"], ["thick", "4px"]] as const) {
      const { container, unmount } = render(<Divider thickness={t} />);
      expect(rule(container).style.height).toBe(px);
      unmount();
    }
  });

  it("maps thickness to a real stroke on the vertical axis", () => {
    const { container } = render(<Divider orientation="vertical" thickness="thick" />);
    expect(rule(container).style.width).toBe("4px");
  });

  it("survives the drop-derived width on a vertical divider", () => {
    // deriveDropStyle gives a dropped node the width of the drop rectangle.
    // resolveStyle used to be spread AFTER the stroke, so `width: 900px` turned
    // the 1px vertical hairline into a full-height grey slab.
    const { container } = render(
      <Divider orientation="vertical" style={{ width: "900px" }} />
    );
    expect(rule(container).style.width).toBe("1px");
  });

  it("still lets the style slot set the divider's LENGTH", () => {
    const h = render(<Divider orientation="horizontal" style={{ width: "240px" }} />);
    expect(rule(h.container).style.width).toBe("240px");
    const v = render(<Divider orientation="vertical" style={{ height: "120px" }} />);
    expect(rule(v.container).style.height).toBe("120px");
  });

  it("does not depend on an undefined spacing.px token for its stroke", () => {
    // No token set in this repo defines spacing.px, so `var(--token-spacing-px)`
    // resolved to nothing and a "1px" rule measured 0px tall on the canvas.
    const { container } = render(<Divider />);
    expect(rule(container).style.height).not.toContain("spacing-px");
  });
});
