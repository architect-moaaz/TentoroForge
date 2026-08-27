import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { FadeIn } from "../../src/components/FadeIn/FadeIn";

describe("FadeIn", () => {
  it("renders children inside a fade-in wrapper", () => {
    const { getByText, container } = render(
      <FadeIn>
        <span>hello</span>
      </FadeIn>
    );
    expect(getByText("hello")).toBeTruthy();
    expect(container.querySelector("[data-motion='fade-in']")).toBeTruthy();
  });

  it("applies delay + duration via inline custom properties", () => {
    const { container } = render(
      <FadeIn delay={50} duration={400}>
        <span>x</span>
      </FadeIn>
    );
    const root = container.firstChild as HTMLElement;
    expect(root.style.getPropertyValue("--fadein-delay")).toBe("50ms");
    expect(root.style.getPropertyValue("--fadein-duration")).toBe("400ms");
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <FadeIn style={{ padding: "tokens.spacing.4" }}>
        <span>x</span>
      </FadeIn>
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-4)");
  });
});
