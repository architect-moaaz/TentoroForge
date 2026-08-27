import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Split } from "../../src/components/Split/Split";

describe("Split", () => {
  it("renders 2 children with ratio data attribute", () => {
    const { container, getByText } = render(
      <Split ratio="2:1">
        <div>left</div>
        <div>right</div>
      </Split>
    );
    expect(getByText("left")).toBeTruthy();
    expect(getByText("right")).toBeTruthy();
    expect(container.querySelector("[data-split-ratio='2:1']")).toBeTruthy();
  });

  it("emits breakpoint data attribute when set", () => {
    const { container } = render(
      <Split ratio="1:1" breakpoint="md">
        <div>a</div>
        <div>b</div>
      </Split>
    );
    expect(container.querySelector("[data-split-breakpoint='md']")).toBeTruthy();
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Split ratio="1:1" style={{ padding: "tokens.spacing.6" }}>
        <div>a</div><div>b</div>
      </Split>
    );
    const splitDiv = container.querySelector("[data-split-ratio]") as HTMLElement;
    expect(splitDiv.style.padding).toBe("var(--token-spacing-6)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Split ratio="1:1" style={{ motion: "fade-in" }}>
        <div>a</div><div>b</div>
      </Split>
    );
    const splitDiv = container.querySelector("[data-split-ratio]") as HTMLElement;
    expect(splitDiv.getAttribute("data-motion")).toBe("fade-in");
  });
});
