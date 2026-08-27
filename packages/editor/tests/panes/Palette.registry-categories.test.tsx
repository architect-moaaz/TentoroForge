import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Palette } from "../../src/panes/Palette/Palette";

/**
 * One entry per LibraryCategory — covers all 9 categories including the two
 * new ones ("motion", "custom") added in Task 34.
 */
const reg = {
  list: () => [
    { name: "Button",      category: "interactive", acceptsChildren: false },
    { name: "Heading",     category: "static",      acceptsChildren: false },
    { name: "Input",       category: "form",        acceptsChildren: false },
    { name: "Table",       category: "data",        acceptsChildren: false },
    { name: "Skeleton",    category: "feedback",    acceptsChildren: false },
    { name: "NavLink",     category: "navigation",  acceptsChildren: false },
    { name: "Hero",        category: "layout",      acceptsChildren: true  },
    { name: "FadeIn",      category: "motion",      acceptsChildren: true  },
    { name: "CustomBlock", category: "custom",      acceptsChildren: false },
  ],
} as any;

describe("Palette — all 9 category headings render", () => {
  it("renders each category as a section heading", () => {
    render(<Palette registry={reg} />);

    // Palette renders the raw category string as the heading text (uppercased via CSS).
    // Some categories share substrings with component names (e.g. "custom" / "CustomBlock"),
    // so we query the heading <span> via data-testid instead of a CSS-class selector.
    const headingSpans = screen.getAllByTestId("palette-category-heading");
    const headingTexts = headingSpans.map((s) =>
      s.textContent?.toLowerCase() ?? ""
    );

    expect(headingTexts).toContain("interactive");
    expect(headingTexts).toContain("static");
    expect(headingTexts).toContain("form");
    expect(headingTexts).toContain("data");
    expect(headingTexts).toContain("feedback");
    expect(headingTexts).toContain("navigation");
    expect(headingTexts).toContain("layout");
    expect(headingTexts).toContain("motion");
    expect(headingTexts).toContain("custom");
  });

  it("renders all 9 component names in the palette", () => {
    render(<Palette registry={reg} />);
    expect(screen.getByText("Button")).toBeInTheDocument();
    expect(screen.getByText("Heading")).toBeInTheDocument();
    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getByText("Table")).toBeInTheDocument();
    expect(screen.getByText("Skeleton")).toBeInTheDocument();
    expect(screen.getByText("NavLink")).toBeInTheDocument();
    expect(screen.getByText("Hero")).toBeInTheDocument();
    expect(screen.getByText("FadeIn")).toBeInTheDocument();
    expect(screen.getByText("CustomBlock")).toBeInTheDocument();
  });
});
