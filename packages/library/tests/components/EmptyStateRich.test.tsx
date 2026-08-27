import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { EmptyStateRich } from "../../src/components/EmptyStateRich/EmptyStateRich";

describe("EmptyStateRich", () => {
  it("renders heading + icon fallback when no illustration", () => {
    const { getByText, container } = render(
      <EmptyStateRich heading="No tasks yet" icon="inbox" />,
    );
    expect(getByText("No tasks yet")).toBeTruthy();
    // icon-fallback span with data-icon set
    expect(container.querySelector("[data-icon]")).not.toBeNull();
  });

  it("renders bare illustration URL via <img>", () => {
    const { container } = render(
      <EmptyStateRich
        heading="No tasks yet"
        illustration="/some/path.png"
      />,
    );
    const img = container.querySelector("img[src='/some/path.png']");
    expect(img).not.toBeNull();
  });

  it("renders structured illustration slot via IllustrationResolver", () => {
    const { container } = render(
      <EmptyStateRich
        heading="No tasks yet"
        illustration={{ slug: "empty-canvas", alt: "Empty canvas" }}
      />,
    );
    const img = container.querySelector("img[src*='empty-canvas.svg']");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("alt")).toBe("Empty canvas");
  });

  it("resolves illustration against injected __illustrationBasePath", () => {
    const { container } = render(
      <EmptyStateRich
        heading="No tasks yet"
        illustration={{ slug: "empty-canvas" }}
        __illustrationBasePath="/p/proj-y/illustrations"
      />,
    );
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("/p/proj-y/illustrations/empty-canvas.svg");
  });
});
