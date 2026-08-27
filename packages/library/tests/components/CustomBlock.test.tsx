import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { CustomBlock } from "../../src/components/CustomBlock/CustomBlock";

describe("CustomBlock", () => {
  it("renders sanitized HTML inside a wrapper", () => {
    const { container } = render(
      <CustomBlock html="<p>hello <strong>world</strong></p>" />
    );
    expect(container.querySelector("strong")?.textContent).toBe("world");
  });

  it("strips script tags via dompurify", () => {
    const { container } = render(
      <CustomBlock html='<p>safe</p><script>alert(1)</script>' />
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("p")?.textContent).toBe("safe");
  });

  it("strips on* event handlers", () => {
    const { container } = render(
      <CustomBlock html='<button onclick="alert(1)">click</button>' />
    );
    const btn = container.querySelector("button") as HTMLElement;
    expect(btn).toBeTruthy();
    expect(btn.getAttribute("onclick")).toBeNull();
  });

  it("applies tailwind classes to wrapper when provided", () => {
    const { container } = render(
      <CustomBlock html="<p>x</p>" tailwind="p-4 bg-primary-500" />
    );
    const root = container.firstChild as HTMLElement;
    expect(root.className).toContain("custom-block");
    expect(root.className).toContain("p-4");
    expect(root.className).toContain("bg-primary-500");
  });

  it("emits data-custom-label when label is provided", () => {
    const { container } = render(
      <CustomBlock html="<p>x</p>" label="Hero with parallax" />
    );
    expect(container.querySelector("[data-custom-label='Hero with parallax']")).toBeTruthy();
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <CustomBlock html="<p>x</p>" style={{ padding: "tokens.spacing.4" }} />
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-4)");
  });
});
