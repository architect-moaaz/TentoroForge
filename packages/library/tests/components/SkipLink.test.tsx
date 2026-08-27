/**
 * SkipLink — Spec E Wave 2 accessibility spine.
 */
import { describe, it, expect, afterEach } from "vitest";
import { render, fireEvent, cleanup } from "@testing-library/react";
import { SkipLink } from "../../src/components/SkipLink/SkipLink";

describe("SkipLink", () => {
  afterEach(() => {
    cleanup();
    // Remove the fixture landmark if present
    document.getElementById("main")?.remove();
  });

  it("renders an anchor with the default label and href='#main'", () => {
    const { getByText, container } = render(<SkipLink />);
    const link = getByText("Skip to main content") as HTMLAnchorElement;
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe("#main");
    expect(container.querySelector("[data-forge-skip-link]")).not.toBeNull();
  });

  it("accepts a custom target and prefixes the # automatically", () => {
    const { getByText } = render(
      <SkipLink target="content-region" label="Skip nav" />,
    );
    const link = getByText("Skip nav") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("#content-region");
  });

  it("is visually hidden until focused (sr-only pattern)", () => {
    const { container } = render(<SkipLink />);
    const link = container.querySelector(
      "[data-forge-skip-link]",
    ) as HTMLElement;
    expect(link.style.position).toBe("absolute");
    expect(link.style.width).toBe("1px");
  });

  it("becomes visible on focus (fixed positioning)", () => {
    const { container } = render(<SkipLink />);
    const link = container.querySelector(
      "[data-forge-skip-link]",
    ) as HTMLElement;
    fireEvent.focus(link);
    expect(link.style.position).toBe("fixed");
  });

  it("activating focuses the target landmark and prevents default", () => {
    const main = document.createElement("main");
    main.id = "main";
    main.textContent = "content";
    document.body.appendChild(main);
    const { container } = render(<SkipLink />);
    const link = container.querySelector(
      "[data-forge-skip-link]",
    ) as HTMLAnchorElement;
    const evt = fireEvent.click(link);
    expect(evt).toBe(false); // preventDefault
    expect(document.activeElement).toBe(main);
  });
});
