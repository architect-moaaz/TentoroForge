import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Button } from "../src/components/Button/Button";

// The Button's isNavAction path stamps `data-nav-trigger` on the DOM element so
// the Engine's delegated click listener resolves + fires the route. The full
// family of route-carrying keys the LLM emits (trigger|to|route|target|href|path)
// must all reach the attribute; before the widen-fix a `.route` descriptor
// silently no-op'd — the visible symptom the user hit as "no buttons work".

function trigger(html: HTMLElement): string | null {
  const btn = html.querySelector("button");
  return btn ? btn.getAttribute("data-nav-trigger") : null;
}

describe("Button — onClick NavActionDescriptor alias chain", () => {
  it.each([
    ["trigger", { action: "navigate", trigger: "/batches/new" }],
    ["to",      { action: "navigate", to:      "/batches/new" }],
    ["route",   { action: "navigate", route:   "/batches/new" }],
    ["target",  { action: "navigate", target:  "/batches/new" }],
    ["href",    { action: "navigate", href:    "/batches/new" }],
    ["path",    { action: "navigate", path:    "/batches/new" }],
  ])("recognises .%s as the nav trigger", (_key, onClick) => {
    const { container } = render(
      <Button label="Upload batch" onClick={onClick as never} />,
    );
    expect(trigger(container)).toBe("/batches/new");
  });

  it("prefers the earlier alias when multiple are set (trigger > to > route)", () => {
    const { container } = render(
      <Button
        label="X"
        onClick={{ action: "navigate", trigger: "/a", to: "/b", route: "/c" } as never}
      />,
    );
    expect(trigger(container)).toBe("/a");
  });

  it("leaves data-nav-trigger unset when onClick is not a nav descriptor", () => {
    const { container } = render(<Button label="X" onClick={() => {}} />);
    expect(trigger(container)).toBeNull();
  });
});
