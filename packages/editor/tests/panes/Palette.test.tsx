import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Palette } from "../../src/panes/Palette/Palette";

const reg = {
  list: () => [
    { name: "Button", category: "interactive", acceptsChildren: false },
    { name: "Card", category: "static", acceptsChildren: true },
    { name: "Form", category: "form", acceptsChildren: false },
  ],
} as any;

describe("Palette", () => {
  it("renders one item per registered library entry, grouped by category", () => {
    render(<Palette registry={reg} />);
    expect(screen.getByText("Button")).toBeInTheDocument();
    expect(screen.getByText("Card")).toBeInTheDocument();
    expect(screen.getByText("Form")).toBeInTheDocument();
    expect(screen.getByText(/interactive/i)).toBeInTheDocument();
    expect(screen.getByText(/static/i)).toBeInTheDocument();
  });
});
