import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Split } from "../../src/components/Split/Split";

describe("Split", () => {
  it("renders 2 children with ratio data attribute", () => {
    const { container, getByText } = render(
      <Split ratio="2:1">
        <div>left</div>
        <div>right</div>
      </Split>
    );
    expect(getByText("left")).toBeTruthy();
    expect(getByText("right")).toBeTruthy();
    expect(container.querySelector("[data-split-ratio='2:1']")).toBeTruthy();
  });

  it("emits breakpoint data attribute when set", () => {
    const { container } = render(
      <Split ratio="1:1" breakpoint="md">
        <div>a</div>
        <div>b</div>
      </Split>
    );
    expect(container.querySelector("[data-split-breakpoint='md']")).toBeTruthy();
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Split ratio="1:1" style={{ padding: "tokens.spacing.6" }}>
        <div>a</div><div>b</div>
      </Split>
    );
    const splitDiv = container.querySelector("[data-split-ratio]") as HTMLElement;
    expect(splitDiv.style.padding).toBe("var(--token-spacing-6)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Split ratio="1:1" style={{ motion: "fade-in" }}>
        <div>a</div><div>b</div>
      </Split>
    );
    const splitDiv = container.querySelector("[data-split-ratio]") as HTMLElement;
    expect(splitDiv.getAttribute("data-motion")).toBe("fade-in");
  });
  it("folds a third child into the second pane instead of wrapping a row", () => {
    const { container } = render(
      <Split ratio="1:1"><div>a</div><div>b</div><div>c</div></Split>
    );
    const grid = container.querySelector("[data-split-id]")!;
    expect(grid.children.length).toBe(2);
    expect(container.querySelector('[data-split-pane="2"]')!.textContent).toBe("bc");
  });

  it("breakpoint 'none' emits the ratio with no media query", () => {
    const { container } = render(
      <Split ratio="2:1" breakpoint={"none" as any}><div>a</div><div>b</div></Split>
    );
    const css = container.querySelector("style")!.textContent!;
    expect(css).not.toContain("@media");
    expect(css).toContain("grid-template-columns: 2fr 1fr");
  });
});
