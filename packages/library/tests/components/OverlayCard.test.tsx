import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { OverlayCard } from "../../src/components/OverlayCard/OverlayCard";

describe("OverlayCard", () => {
  it("renders absolute positioned with default bottom-right anchor", () => {
    const { container } = render(
      <OverlayCard title="Sign up" description="Get started" />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.position).toBe("absolute");
    // bottom-right → bottom + right set
    expect(el.style.bottom).toBeTruthy();
    expect(el.style.right).toBeTruthy();
  });

  it("anchor=top-left sets top + left", () => {
    const { container } = render(
      <OverlayCard anchor="top-left" title="x" />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.style.top).toBeTruthy();
    expect(el.style.left).toBeTruthy();
  });

  it("anchor=center uses transform-translate centering", () => {
    const { container } = render(<OverlayCard anchor="center" title="x" />);
    const el = container.firstChild as HTMLElement;
    expect(el.style.top).toBe("50%");
    expect(el.style.left).toBe("50%");
    expect(el.style.transform).toContain("translate");
  });

  it("elevation=xl applies shadow class", () => {
    const { container } = render(
      <OverlayCard elevation="xl" title="x" />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.className).toMatch(/shadow-xl|shadow-2xl/);
  });

  it("renders title + description", () => {
    const { getByText } = render(
      <OverlayCard title="Hello" description="World" />
    );
    expect(getByText("Hello")).toBeTruthy();
    expect(getByText("World")).toBeTruthy();
  });

  it("data-anchor attribute reflects anchor prop", () => {
    const { container } = render(
      <OverlayCard anchor="top-right" title="x" />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.getAttribute("data-anchor")).toBe("top-right");
  });

  it("data-elevation attribute reflects elevation prop", () => {
    const { container } = render(
      <OverlayCard elevation="sm" title="x" />
    );
    const el = container.firstChild as HTMLElement;
    expect(el.getAttribute("data-elevation")).toBe("sm");
  });
});
