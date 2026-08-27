import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Button } from "../../src/components/Button/Button";

describe("Button icon rendering", () => {
  it("renders an icon next to the label when icon is set", () => {
    const { container } = render(<Button label="Add" icon="plus" />);
    const btn = container.querySelector("button");
    expect(btn).not.toBeNull();
    // Lucide renders an <svg> element; we also set data-icon on it
    const iconEl =
      btn?.querySelector("[data-icon='plus']") ??
      btn?.querySelector("svg");
    expect(iconEl).not.toBeNull();
    expect(btn?.textContent).toContain("Add");
  });

  it("renders icon-only when no label is set", () => {
    const { container } = render(
      <Button icon="more-horizontal" aria-label="More" />
    );
    const btn = container.querySelector("button");
    expect(btn?.getAttribute("aria-label")).toBe("More");
    // icon-only: textContent should be empty (only SVG, no text nodes)
    expect(btn?.textContent?.trim() ?? "").toBe("");
  });

  it("places icon on the right when iconPosition='right'", () => {
    const { container } = render(
      <Button label="Next" icon="chevron-right" iconPosition="right" />
    );
    const btn = container.querySelector("button");
    const children = Array.from(btn?.childNodes ?? []);
    // Find icon (SVG element) and label (text node containing "Next")
    const iconIdx = children.findIndex(
      (n) =>
        n instanceof Element &&
        (n.tagName.toLowerCase() === "svg" ||
          n.querySelector("svg") !== null ||
          n.getAttribute("data-icon") !== null)
    );
    const labelIdx = children.findIndex(
      (n) => n.nodeType === Node.TEXT_NODE && n.textContent?.includes("Next")
    );
    // Both must be found and icon must come after label
    expect(iconIdx).toBeGreaterThan(-1);
    expect(labelIdx).toBeGreaterThan(-1);
    expect(iconIdx).toBeGreaterThan(labelIdx);
  });
});
