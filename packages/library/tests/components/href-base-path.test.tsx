import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { NavigatorProvider, createBasePathNavigator } from "@tentoroforge/renderer";
import { Breadcrumb } from "../../src/components/Breadcrumb/Breadcrumb";
import { Link } from "../../src/components/Link/Link";
import { NavLink } from "../../src/components/NavLink/NavLink";

/**
 * THE HALF OF THE BASE-PATH FIX THAT WAS LEFT STANDING.
 *
 * `Navigator.push` was taught the host's prefix, which fixed the click. The
 * `href` ATTRIBUTE was not, and an anchor is more than its click handler:
 * middle-click, ⌘-click, "copy link address", a crawler and the entire
 * pre-hydration window read the attribute. Link and NavLink hijack the plain
 * left-click so the bug hid behind that; Breadcrumb renders plain `<a href>`
 * with no handler at all and was simply broken under `/p/<project>/`.
 *
 * All three are asserted through the same provider so they cannot diverge, and
 * the no-provider case is asserted too — a host that declares no prefix must
 * see exactly the URLs it sees today.
 */

const inner = { push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn() };
const withBase = (ui: React.ReactElement) => (
  <NavigatorProvider value={createBasePathNavigator("/p/proj1", inner as any)}>
    {ui}
  </NavigatorProvider>
);

const CRUMBS = [
  { label: "Items", href: "/items" },
  { label: "Widget A", href: "/items/1" },
  { label: "Edit" },
];

describe("hrefs resolve under the host's base path", () => {
  it("Breadcrumb crumbs point inside the previewed app", () => {
    const { container } = render(withBase(<Breadcrumb items={CRUMBS} />));
    const hrefs = Array.from(container.querySelectorAll("a")).map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toEqual(["/p/proj1/items", "/p/proj1/items/1"]);
  });

  it("Link's rendered href matches where its click would go", () => {
    const { container } = render(withBase(<Link label="Go" navigate="/items" />));
    expect(container.querySelector("a")!.getAttribute("href")).toBe("/p/proj1/items");
  });

  it("NavLink's rendered href does too", () => {
    const { container } = render(withBase(<NavLink label="Items" navigate="/items" />));
    expect(container.querySelector("a")!.getAttribute("href")).toBe("/p/proj1/items");
  });

  it("an external URL is left exactly as authored", () => {
    const { container } = render(
      withBase(<Link label="Docs" navigate="https://example.com/docs" />),
    );
    expect(container.querySelector("a")!.getAttribute("href")).toBe(
      "https://example.com/docs",
    );
  });

  it("a route already under the base is not prefixed twice", () => {
    const { container } = render(
      withBase(<Breadcrumb items={[{ label: "Items", href: "/p/proj1/items" }, { label: "x" }]} />),
    );
    expect(container.querySelector("a")!.getAttribute("href")).toBe("/p/proj1/items");
  });
});

describe("no base path declared — nothing changes", () => {
  it("Breadcrumb, Link and NavLink render the authored route verbatim", () => {
    const b = render(<Breadcrumb items={CRUMBS} />);
    expect(b.container.querySelector("a")!.getAttribute("href")).toBe("/items");
    const l = render(<Link label="Go" navigate="/items" />);
    expect(l.container.querySelector("a")!.getAttribute("href")).toBe("/items");
    const n = render(<NavLink label="Items" navigate="/items" />);
    expect(n.container.querySelector("a")!.getAttribute("href")).toBe("/items");
  });
});
