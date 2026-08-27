// packages/library/tests/components/Tabs.test.tsx
import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { Tabs } from "../../src/components/Tabs/Tabs";

describe("Tabs", () => {
  it("renders tab labels and shows panel matching value", () => {
    const { getByText, container } = render(
      <Tabs tabs={[
        { id: "a", label: "Alpha" },
        { id: "b", label: "Beta" },
      ]} value="a">
        <div>panel-a</div>
        <div>panel-b</div>
      </Tabs>
    );
    expect(getByText("Alpha")).toBeTruthy();
    expect(getByText("Beta")).toBeTruthy();
    expect(getByText("panel-a")).toBeTruthy();
    // Panel-b should be in DOM but hidden via [hidden] / data-active="false"
    const panelB = container.querySelector("[data-tab-panel='b']") as HTMLElement;
    expect(panelB?.getAttribute("data-tab-active")).toBe("false");
  });

  it("emits data-tab-active='true' on the matching panel", () => {
    const { container } = render(
      <Tabs tabs={[
        { id: "a", label: "A" },
        { id: "b", label: "B" },
      ]} value="b">
        <div>pa</div>
        <div>pb</div>
      </Tabs>
    );
    const panelA = container.querySelector("[data-tab-panel='a']") as HTMLElement;
    const panelB = container.querySelector("[data-tab-panel='b']") as HTMLElement;
    expect(panelA.getAttribute("data-tab-active")).toBe("false");
    expect(panelB.getAttribute("data-tab-active")).toBe("true");
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Tabs tabs={[{ id: "a", label: "A" }]} value="a"
            style={{ padding: "tokens.spacing.4" }}>
        <div>p</div>
      </Tabs>
    );
    expect((container.firstChild as HTMLElement).style.padding)
      .toBe("var(--token-spacing-4)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Tabs tabs={[{ id: "a", label: "A" }]} value="a"
            style={{ motion: "fade-in" }}>
        <div>p</div>
      </Tabs>
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });

  it("calls onChange when a tab button is clicked", () => {
    const calls: string[] = [];
    const { getByText } = render(
      <Tabs tabs={[
        { id: "a", label: "Alpha" },
        { id: "b", label: "Beta" },
      ]} value="a" onChange={(v) => calls.push(v)}>
        <div>pa</div>
        <div>pb</div>
      </Tabs>
    );
    fireEvent.click(getByText("Beta"));
    expect(calls).toEqual(["b"]);
  });
});
