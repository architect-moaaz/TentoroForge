import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Sidebar } from "../../src/components/Sidebar/Sidebar";

describe("Sidebar", () => {
  it("renders 2 children with sidebar+main pane attributes", () => {
    const { container, getByText } = render(
      <Sidebar width="240px">
        <nav>nav</nav>
        <main>main</main>
      </Sidebar>
    );
    expect(getByText("nav")).toBeTruthy();
    expect(getByText("main")).toBeTruthy();
    expect(container.querySelector('[data-sidebar-pane="aside"]')).toBeTruthy();
    expect(container.querySelector('[data-sidebar-pane="main"]')).toBeTruthy();
  });

  it("emits a media-query rule using the configured width", () => {
    const { container } = render(
      <Sidebar width="200px">
        <div>a</div><div>b</div>
      </Sidebar>
    );
    // The responsive width is applied via an inline <style> + media query
    // (scoped per instance via data-sidebar-id) instead of a CSS custom
    // property — Tailwind's JIT can't generate arbitrary md: rules from a
    // runtime-supplied width.
    const styleEl = container.querySelector("style");
    expect(styleEl?.textContent).toContain("200px");
    expect(styleEl?.textContent).toMatch(/min-width:\s*768px/);
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Sidebar width="200px" style={{ padding: "tokens.spacing.4" }}>
        <div>a</div><div>b</div>
      </Sidebar>
    );
    const root = container.querySelector("[data-sidebar-id]") as HTMLElement;
    expect(root.style.padding).toBe("var(--token-spacing-4)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Sidebar width="200px" style={{ motion: "slide-in" }}>
        <div>a</div><div>b</div>
      </Sidebar>
    );
    const root = container.querySelector("[data-sidebar-id]") as HTMLElement;
    expect(root.getAttribute("data-motion")).toBe("slide-in");
  });
  // --- Contract + responsiveness (docs/editor-audit/containment.md).
  it("folds a third child into the main pane instead of a phantom row", () => {
    // maxChildren:2 is an editor rule only; a JSON edit or an LLM patch could
    // write three, and every extra used to get its own [data-sidebar-pane]
    // labelled "main" in an implicit third grid row.
    const { container } = render(
      <Sidebar width="240px">
        <div>aside</div><div>one</div><div>two</div>
      </Sidebar>
    );
    expect(container.querySelectorAll("[data-sidebar-pane]").length).toBe(2);
    const main = container.querySelector('[data-sidebar-pane="main"]')!;
    expect(main.textContent).toBe("onetwo");
  });

  it("honours the breakpoint prop", () => {
    const { container } = render(
      <Sidebar width="200px" breakpoint="lg"><div>a</div><div>b</div></Sidebar>
    );
    expect(container.querySelector("style")!.textContent).toMatch(/min-width:\s*1024px/);
    expect(container.querySelector('[data-sidebar-breakpoint="lg"]')).toBeTruthy();
  });

  it("breakpoint 'none' emits the two-column rule with no media query", () => {
    // The stacking point used to be hard-coded at 768px, so a two-column layout
    // the user arranged was a vertical stack on every phone and tablet.
    const { container } = render(
      <Sidebar width="200px" breakpoint="none"><div>a</div><div>b</div></Sidebar>
    );
    const css = container.querySelector("style")!.textContent!;
    expect(css).not.toContain("@media");
    expect(css).toContain("grid-template-columns: 200px 1fr");
  });
});
