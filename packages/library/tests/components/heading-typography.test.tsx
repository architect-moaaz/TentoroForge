import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Heading } from "../../src/components/Heading/Heading";

describe("Heading typography", () => {
  it("applies var(--font-heading) family", () => {
    const { container } = render(<Heading level={1} content="Title" />);
    const el = container.firstChild as HTMLElement;
    expect(el.getAttribute("style") || "").toMatch(/var\(--font-heading[,)]/);
  });

  it("applies var(--font-heading-weight) when set", () => {
    const { container } = render(<Heading level={1} content="Title" />);
    const el = container.firstChild as HTMLElement;
    expect(el.getAttribute("style") || "").toMatch(/var\(--font-heading-weight[,)]/);
  });

  it("applies var(--font-heading-tracking) when set", () => {
    const { container } = render(<Heading level={1} content="Title" />);
    const el = container.firstChild as HTMLElement;
    expect(el.getAttribute("style") || "").toMatch(/var\(--font-heading-tracking[,)]/);
  });
});
