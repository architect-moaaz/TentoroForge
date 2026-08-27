import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Section } from "../../src/components/Section/Section";

describe("Section variant=full-bleed", () => {
  it("default variant has normal width (no breakout)", () => {
    const { container } = render(<Section variant="plain">content</Section>);
    const el = container.firstChild as HTMLElement;
    expect(el.style.width).not.toBe("100vw");
  });

  it("full-bleed sets width:100vw + horizontal breakout transform", () => {
    const { container } = render(<Section variant="full-bleed">x</Section>);
    const el = container.firstChild as HTMLElement;
    expect(el.style.width).toBe("100vw");
    // breakout pattern: marginLeft 50% + transform translateX(-50%)
    expect(el.style.marginLeft).toBe("50%");
    expect(el.style.transform).toContain("translateX(-50%)");
  });

  it("full-bleed sets data-variant attribute", () => {
    const { container } = render(<Section variant="full-bleed">x</Section>);
    const el = container.firstChild as HTMLElement;
    expect(el.getAttribute("data-variant")).toBe("full-bleed");
  });
});

describe("Section", () => {
  it("renders title + children", () => {
    const { getByText } = render(
      <Section variant="feature" title="Stats">
        <span>child</span>
      </Section>
    );
    expect(getByText("Stats")).toBeTruthy();
    expect(getByText("child")).toBeTruthy();
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Section variant="feature" style={{ padding: "tokens.spacing.semantic.section" }}>
        <span>x</span>
      </Section>
    );
    const root = container.firstChild as HTMLElement;
    expect(root.style.padding).toBe("var(--token-spacing-semantic-section)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Section variant="feature" style={{ motion: "fade-in" }}>
        <span>x</span>
      </Section>
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });

  it("renders illustration side-by-side when slug provided", () => {
    const { container, getByText } = render(
      <Section
        variant="plain"
        illustration={{ slug: "sign-in", alt: "Sign in illustration" }}
      >
        <span>form-here</span>
      </Section>
    );
    expect(container.querySelector("img[src*='sign-in.svg']")).not.toBeNull();
    expect(getByText("form-here")).toBeTruthy();
  });
});
