import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { IllustrationResolver } from "../../src/components/surfaces/IllustrationResolver";

describe("IllustrationResolver", () => {
  it("renders an img pointing at /illustrations/<slug>.svg by default", () => {
    const { container } = render(
      <IllustrationResolver slug="running-athlete" alt="Running athlete" />
    );
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img).not.toBeNull();
    expect(img.src).toContain("/illustrations/running-athlete.svg");
    expect(img.alt).toBe("Running athlete");
  });

  it("respects an explicit basePath override (for the scaffold preview server)", () => {
    const { container } = render(
      <IllustrationResolver
        slug="happy-news"
        alt="Happy news"
        basePath="/p/proj-123/illustrations"
      />
    );
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img.src).toContain("/p/proj-123/illustrations/happy-news.svg");
  });

  it("renders nothing when slug is falsy", () => {
    const { container } = render(<IllustrationResolver slug="" alt="" />);
    expect(container.querySelector("img")).toBeNull();
  });
});
