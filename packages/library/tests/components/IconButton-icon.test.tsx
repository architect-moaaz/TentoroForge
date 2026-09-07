import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { IconButton } from "../../src/components/IconButton/IconButton";

/**
 * docs/editor-audit/input-components-2.md finding #5 — an IconButton dropped
 * from the palette rendered the literal WORD "Plus".
 *
 * Cause: the component interpolated the raw `icon` string into the DOM and
 * never called `resolveIcon`, while the catalog's default for the prop is the
 * icon NAME "Plus".
 */
describe("IconButton renders a glyph, not the name of one", () => {
  it("draws an SVG for the registry default icon:\"Plus\"", () => {
    const { container } = render(<IconButton icon="Plus" aria-label="Add" />);
    const btn = screen.getByRole("button", { name: "Add" });
    expect(container.querySelector("svg")).not.toBeNull();
    // The bug, stated as an assertion.
    expect(btn.textContent).not.toContain("Plus");
  });

  it("resolves the kebab spelling to the same glyph", () => {
    const { container } = render(<IconButton icon="chevron-down" aria-label="Open" />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(container.querySelector('[data-icon="chevron-down"]')).not.toBeNull();
  });

  it("shows a visible empty slot — not silence, not text — for a name we do not have", () => {
    const { container } = render(<IconButton icon="NotAnIcon" aria-label="Mystery" />);
    const marker = container.querySelector('[data-unresolved-icon="NotAnIcon"]');
    expect(marker).not.toBeNull();
    expect(screen.getByRole("button", { name: "Mystery" }).textContent).toBe("");
  });

  it("still renders a glyph the author typed directly", () => {
    // "✕" is not an icon name and must not be mistaken for a failed lookup.
    render(<IconButton icon="✕" aria-label="Close" />);
    expect(screen.getByRole("button", { name: "Close" }).textContent).toBe("✕");
  });

  it("keeps iconSrc winning over icon (the Figma-export path)", () => {
    const { container } = render(
      <IconButton icon="Plus" iconSrc="/api/asset/x.svg" aria-label="Add" />,
    );
    expect(container.querySelector('img[src="/api/asset/x.svg"]')).not.toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });
});
