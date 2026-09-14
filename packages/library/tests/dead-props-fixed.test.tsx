/**
 * Props that the registry declares, the editor renders a control for, and the
 * component silently ignored. Each of these fails against the pre-fix source.
 *
 * Found by the registry-vs-component conformance check, not by a browser sweep —
 * NavLink.icon in particular sat in a blind spot between two test suites.
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { NavLink } from "../src/components/NavLink/NavLink";
import { Divider } from "../src/components/Divider/Divider";

describe("NavLink — props declared in the registry are honoured", () => {
  it("uses `target` as the destination when href/navigate are absent", () => {
    const { container } = render(<NavLink label="Go" target="/reports" />);
    expect(container.querySelector("a")?.getAttribute("href")).toBe("/reports");
  });

  it("still prefers href, then navigate, over target", () => {
    const { container: a } = render(<NavLink label="x" href="/h" navigate="/n" target="/t" />);
    expect(a.querySelector("a")?.getAttribute("href")).toBe("/h");
    const { container: b } = render(<NavLink label="x" navigate="/n" target="/t" />);
    expect(b.querySelector("a")?.getAttribute("href")).toBe("/n");
  });

  it("falls back to # when no destination is given", () => {
    const { container } = render(<NavLink label="x" />);
    expect(container.querySelector("a")?.getAttribute("href")).toBe("#");
  });

  it("renders a leading icon when `icon` names a known glyph", () => {
    const { container } = render(<NavLink label="Home" icon="home" />);
    expect(container.querySelector("a svg")).not.toBeNull();
  });

  it("renders no icon element when `icon` is absent", () => {
    const { container } = render(<NavLink label="Home" />);
    expect(container.querySelector("a svg")).toBeNull();
  });

  it("an unknown icon name degrades to no icon rather than throwing", () => {
    expect(() => render(<NavLink label="Home" icon="definitely-not-an-icon" />)).not.toThrow();
  });
});

describe("Divider — thickness is honoured", () => {
  it("maps thin/medium/thick to distinct strokes", () => {
    const h = (t?: "thin" | "medium" | "thick") =>
      (render(<Divider thickness={t} />).container.querySelector("hr") as HTMLElement).style.height;
    expect(h("thin")).toBe("1px");
    expect(h("medium")).toBe("2px");
    expect(h("thick")).toBe("4px");
    expect(new Set([h("thin"), h("medium"), h("thick")]).size).toBe(3);
  });

  it("applies the stroke to width when vertical", () => {
    const el = render(<Divider orientation="vertical" thickness="thick" />)
      .container.querySelector("hr") as HTMLElement;
    expect(el.style.width).toBe("4px");
    expect(el.style.height).toBe("100%");
  });

  it("defaults to thin", () => {
    const el = render(<Divider />).container.querySelector("hr") as HTMLElement;
    expect(el.style.height).toBe("1px");
  });
});
