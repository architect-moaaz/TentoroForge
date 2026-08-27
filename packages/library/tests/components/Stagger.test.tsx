import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Stagger } from "../../src/components/Stagger/Stagger";

describe("Stagger", () => {
  it("emits data-motion=stagger and CSS custom prop for interval", () => {
    const { container } = render(
      <Stagger interval={120}>
        <span>a</span>
        <span>b</span>
      </Stagger>
    );
    const root = container.firstChild as HTMLElement;
    expect(root.getAttribute("data-motion")).toBe("stagger");
    expect(root.style.getPropertyValue("--stagger-interval")).toBe("120ms");
  });

  it("default interval is 80ms when omitted", () => {
    const { container } = render(
      <Stagger>
        <span>a</span>
      </Stagger>
    );
    const root = container.firstChild as HTMLElement;
    expect(root.style.getPropertyValue("--stagger-interval")).toBe("80ms");
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Stagger style={{ padding: "tokens.spacing.4" }}>
        <span>x</span>
      </Stagger>
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-4)");
  });
});
