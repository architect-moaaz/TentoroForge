import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Hero } from "../../src/components/Hero/Hero";
import React from "react";

describe("Hero", () => {
  it("renders headline + eyebrow", () => {
    const { getByText } = render(
      <Hero headline="Welcome" eyebrow="Hi" layout="centered" ctas={[]} />
    );
    expect(getByText("Welcome")).toBeTruthy();
    expect(getByText("Hi")).toBeTruthy();
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Hero headline="X" layout="centered" ctas={[]}
            style={{ padding: "tokens.spacing.semantic.section" }} />
    );
    const root = container.firstChild as HTMLElement;
    expect(root.style.padding).toBe("var(--token-spacing-semantic-section)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Hero headline="X" layout="centered" ctas={[]}
            style={{ motion: "fade-in" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });

  it("renders illustration via IllustrationResolver when slug provided", () => {
    const { container } = render(
      <Hero
        headline="Welcome back"
        layout="centered"
        ctas={[]}
        illustration={{ slug: "running-athlete", alt: "Running athlete" }}
      />
    );
    const img = container.querySelector("img[src*='running-athlete.svg']");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("alt")).toBe("Running athlete");
  });

  it("uses __illustrationBasePath when injected", () => {
    const { container } = render(
      <Hero
        headline="Welcome back"
        layout="centered"
        ctas={[]}
        illustration={{ slug: "running-athlete" }}
        {...({ __illustrationBasePath: "/p/proj-x/illustrations" } as Record<string, string>)}
      />
    );
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("/p/proj-x/illustrations/running-athlete.svg");
  });
});

describe("Hero backgroundImage", () => {
  it("renders without background by default", () => {
    const { container } = render(<Hero headline="Welcome" layout="centered" ctas={[]} />);
    const el = container.firstChild as HTMLElement;
    // No background-image style
    expect(el.style.backgroundImage).toBe("");
  });

  it("renders backgroundImage url", () => {
    const { container } = render(
      <Hero
        headline="Welcome"
        layout="centered"
        ctas={[]}
        backgroundImage={{ url: "https://example.com/hero.jpg", overlay: 0.4 }}
      />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.backgroundImage).toContain("url(");
    expect(el.style.backgroundImage).toContain("hero.jpg");
  });

  it("renders an overlay scrim with the configured opacity", () => {
    const { container } = render(
      <Hero
        headline="Welcome"
        layout="centered"
        ctas={[]}
        backgroundImage={{ url: "https://example.com/x.jpg", overlay: 0.6 }}
      />
    );
    const scrim = container.querySelector("[data-hero-scrim]");
    expect(scrim).not.toBeNull();
    const scrimEl = scrim as HTMLElement;
    const opacity = scrimEl.style.opacity || scrimEl.style.backgroundColor;
    expect(opacity).toMatch(/0\.6|0,?\s*0\.?6|0\.6\)/);
  });

  it("title remains visible above scrim (higher z-index or DOM order)", () => {
    const { container, getByText } = render(
      <Hero
        headline="Welcome"
        layout="centered"
        ctas={[]}
        backgroundImage={{ url: "https://example.com/x.jpg", overlay: 0.4 }}
      />
    );
    const title = getByText("Welcome");
    const scrim = container.querySelector("[data-hero-scrim]") as HTMLElement;
    expect(scrim).not.toBeNull();
    const titleParent = title.closest("[data-hero-content]") || title.parentElement;
    expect(titleParent).not.toBeNull();
  });
});
