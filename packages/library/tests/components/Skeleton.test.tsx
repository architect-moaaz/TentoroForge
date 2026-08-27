// packages/library/tests/components/Skeleton.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Skeleton } from "../../src/components/Skeleton/Skeleton";

describe("Skeleton", () => {
  it("renders with rect variant", () => {
    const { container } = render(<Skeleton variant="rect" />);
    expect(container.querySelector("[data-skeleton-variant='rect']")).toBeTruthy();
  });

  it("renders with circle variant", () => {
    const { container } = render(<Skeleton variant="circle" />);
    expect(container.querySelector("[data-skeleton-variant='circle']")).toBeTruthy();
  });

  it("renders text variant with multiple lines", () => {
    const { container } = render(<Skeleton variant="text" lines={3} />);
    const root = container.querySelector("[data-skeleton-variant='text']") as HTMLElement;
    expect(root.children.length).toBe(3);
  });

  it("renders text variant with single line when lines unset", () => {
    const { container } = render(<Skeleton variant="text" />);
    const root = container.querySelector("[data-skeleton-variant='text']") as HTMLElement;
    expect(root.children.length).toBe(1);
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Skeleton variant="rect" style={{ radius: "tokens.radius.md" }} />
    );
    expect((container.firstChild as HTMLElement).style.borderRadius)
      .toBe("var(--token-radius-md)");
  });

  it("emits data-motion attribute when motion set (default shimmer)", () => {
    const { container } = render(
      <Skeleton variant="rect" style={{ motion: "fade-in" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });
});
