import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SideNav } from "../src/components/SideNav/SideNav";
import { SideNavProps } from "../src/components/SideNav/SideNav.schema";

// The rail's brand block has always drawn a square with the first letter of the
// application's name in it. That square is a STAND-IN for a logo nobody could
// supply: there was no Blueprint field for an image, so "put our logo in the
// corner" had nowhere to land. Given one it draws the mark instead — the
// substitution is the whole feature, and these pin both halves of it.
//
// `shell.json` is validated against SideNavProps (`.strict()`), so a prop the
// projection writes and the schema does not declare is a rail that will not
// render at all. That is the last test here.

describe("SideNav — the owner's mark in the corner", () => {
  const brandBlock = (c: HTMLElement) =>
    c.querySelector("nav.tf-sidenav > div:first-of-type") as HTMLElement;

  it("draws the application's initial when no logo was given", () => {
    const { container } = render(<SideNav appName="Bright Care" groups={[]} />);
    expect(container.querySelector("img.tf-logo")).toBeNull();
    expect(brandBlock(container).firstElementChild?.tagName).toBe("SPAN");
    expect(brandBlock(container).firstElementChild?.textContent).toBe("B");
  });

  it("draws the mark in place of the initial when one was given", () => {
    const { container } = render(
      <SideNav appName="Bright Care" groups={[]}
               logoSrc="/brand/0123456789abcdef.png" logoAlt="Bright Care" />
    );
    const img = container.querySelector("img.tf-logo") as HTMLImageElement;
    expect(img).toBeTruthy();
    expect(img.getAttribute("src")).toBe("/brand/0123456789abcdef.png");
    expect(img.getAttribute("alt")).toBe("Bright Care");
    // The mark replaces the WHOLE lockup — the square and the name both.
    // Setting a logo beside the name in text reads as a stutter, and worst
    // where the mark is a wordmark, which is what most of them are.
    const block = brandBlock(container);
    expect(block.firstElementChild).toBe(img);
    expect(block.children.length).toBe(1);
    expect(block.textContent).not.toContain("Bright Care");
  });

  it("falls back to the application's name rather than going unnamed", () => {
    const { container } = render(
      <SideNav appName="Bright Care" groups={[]} logoSrc="/brand/abc.svg" />
    );
    expect(container.querySelector("img.tf-logo")?.getAttribute("alt"))
      .toBe("Bright Care");
  });

  it("sizes a wordmark by its ratio so it is not squared off", () => {
    // 240×60 — four times wider than tall. Without the ratio an SVG with no
    // intrinsic width lays out at zero and the corner looks empty.
    const { container } = render(
      <SideNav appName="Bright Care" groups={[]} logoSrc="/brand/w.svg" logoAspect={4} />
    );
    const img = container.querySelector("img.tf-logo") as HTMLImageElement;
    expect(img.style.width).toBe("112px");   // 28px tall × 4
  });

  it("takes the row's height and is clipped, never squeezed to fit", () => {
    // The collapsed rail is 64px wide. Capping the mark's WIDTH there
    // letterboxed a 4:1 wordmark to 28x7 — a smudge. Sized by height and
    // clipped by the rail, the same mark shows its leading 28px at full
    // height, which for a wordmark is the icon it starts with.
    const { container } = render(
      <SideNav appName="Bright Care" groups={[]} logoSrc="/brand/w.svg" logoAspect={4} />
    );
    const css = container.querySelector("style")?.textContent ?? "";
    expect(css).toContain(".tf-logo{display:block;flex-shrink:0;height:28px;"
      + "object-fit:contain;object-position:left center}");
    expect(css).not.toContain("max-width:28px");
    expect(css).toContain(".tf-sidenav{position:fixed");   // the rail clips it
    expect(css).toContain("overflow:hidden");
    const img = container.querySelector("img.tf-logo") as HTMLImageElement;
    expect(img.style.width).toBe("112px");
  });

  it("declares the props the projection writes", () => {
    // `.strict()`: an undeclared prop in shell.json is a rail that does not
    // render, so the schema and `project_shell` have to agree.
    const parsed = SideNavProps.parse({
      appName: "Bright Care",
      logoSrc: "/brand/0123456789abcdef.png",
      logoAlt: "Bright Care",
      logoAspect: 4,
    });
    expect(parsed.logoSrc).toBe("/brand/0123456789abcdef.png");
    expect(() => SideNavProps.parse({ logoUrl: "/brand/x.png" })).toThrow();
  });
});
