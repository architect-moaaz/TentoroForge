import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Heading } from "../../src/components/Heading/Heading";

describe("Heading type-scale", () => {
  it("level 1 renders h1 with text-page-title class", () => {
    const { container } = render(<Heading level={1} content="Hi" />);
    const el = container.querySelector("h1");
    expect(el).not.toBeNull();
    expect(el?.className).toContain("text-page-title");
  });
  it("level 2 renders h2 with text-section-title class", () => {
    const { container } = render(<Heading level={2} content="Hi" />);
    const el = container.querySelector("h2");
    expect(el?.className).toContain("text-section-title");
  });
  it("level 3 renders h3 with text-card-title class", () => {
    const { container } = render(<Heading level={3} content="Hi" />);
    expect(container.querySelector("h3")?.className).toContain("text-card-title");
  });
  it("level 4-6 use body / caption / micro", () => {
    const { container: c4 } = render(<Heading level={4} content="x" />);
    expect(c4.querySelector("h4")?.className).toContain("text-body");
    const { container: c5 } = render(<Heading level={5} content="x" />);
    expect(c5.querySelector("h5")?.className).toContain("text-caption");
    const { container: c6 } = render(<Heading level={6} content="x" />);
    expect(c6.querySelector("h6")?.className).toContain("text-micro");
  });
});
