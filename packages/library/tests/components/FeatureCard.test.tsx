import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { FeatureCard } from "../../src/components/FeatureCard/FeatureCard";

describe("FeatureCard", () => {
  it("renders title + description", () => {
    const { getByText } = render(
      <FeatureCard title="Fast" description="Built for speed" layout="icon-top" />
    );
    expect(getByText("Fast")).toBeTruthy();
    expect(getByText("Built for speed")).toBeTruthy();
  });

  it("renders cta as anchor when href set", () => {
    const { container } = render(
      <FeatureCard title="X" description="x" layout="icon-top"
        cta={{ label: "Learn more", href: "/docs" }} />
    );
    const link = container.querySelector("a[href='/docs']") as HTMLAnchorElement;
    expect(link).toBeTruthy();
    expect(link.textContent).toContain("Learn more");
  });

  it("encodes layout in data attribute", () => {
    const { container } = render(
      <FeatureCard title="X" description="x" layout="icon-left" />
    );
    expect(container.querySelector("[data-feature-layout='icon-left']")).toBeTruthy();
  });

  it("renders icon span with data-icon when icon set", () => {
    const { container } = render(
      <FeatureCard title="X" description="x" layout="icon-top" icon="zap" />
    );
    expect(container.querySelector("[data-icon='zap']")).toBeTruthy();
  });

  it("does not render icon span when icon absent", () => {
    const { container } = render(
      <FeatureCard title="X" description="x" layout="icon-top" />
    );
    expect(container.querySelector("[data-icon]")).toBeNull();
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <FeatureCard title="X" description="x" layout="icon-top"
        style={{ padding: "tokens.spacing.semantic.card" }} />
    );
    const root = container.firstChild as HTMLElement;
    expect(root.style.padding).toBe("var(--token-spacing-semantic-card)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <FeatureCard title="X" description="x" layout="icon-top"
        style={{ motion: "fade-up" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-up");
  });
});
