import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SurfaceBackground } from "../../src/components/surfaces/SurfaceBackground";

describe("SurfaceBackground", () => {
  it("renders a div with linear-gradient style for a gradient background", () => {
    const { container } = render(
      <SurfaceBackground
        background={{ type: "linear", angle: 135, from: "#fff", to: "#eee" }}
        data-testid="bg"
      >
        <span>content</span>
      </SurfaceBackground>
    );
    const el = container.querySelector("[data-testid='bg']") as HTMLElement;
    expect(el).not.toBeNull();
    expect(el.style.background).toContain("linear-gradient");
    expect(el.textContent).toBe("content");
  });

  it("renders a solid color when background is a string", () => {
    const { container } = render(
      <SurfaceBackground background="#ff00ff" data-testid="bg">
        <span>x</span>
      </SurfaceBackground>
    );
    const el = container.querySelector("[data-testid='bg']") as HTMLElement;
    // jsdom normalises hex to rgb; either form confirms the background is set
    expect(el.style.background).toMatch(/#ff00ff|rgb\(255,\s*0,\s*255\)/);
  });

  it("renders unstyled when background is undefined", () => {
    const { container } = render(
      <SurfaceBackground data-testid="bg">
        <span>x</span>
      </SurfaceBackground>
    );
    const el = container.querySelector("[data-testid='bg']") as HTMLElement;
    expect(el.style.background).toBe("");
  });
});
