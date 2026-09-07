// packages/library/tests/components/Tabs.test.tsx
import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { Tabs } from "../../src/components/Tabs/Tabs";
import { TabPanel } from "../../src/components/TabPanel/TabPanel";

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
  // --- Panel-count regressions (docs/editor-audit/containment.md, probe
  // zzprobe-tabsn). `Tabs.tabs` defaults to null in the registry and its only
  // control destroys arrays, so the strip has to come from the children.
  it("renders one tab per child when tabs is empty", () => {
    const { container, getByText } = render(
      <Tabs tabs={[] as any} value="">
        <div>panel-0</div>
        <div>panel-1</div>
        <div>panel-2</div>
      </Tabs>
    );
    expect(container.querySelectorAll("[role='tab']").length).toBe(3);
    expect(container.querySelectorAll("[data-tab-panel]").length).toBe(3);
    getByText("panel-0"); getByText("panel-1"); getByText("panel-2");
  });

  it("takes each tab label from its TabPanel child", () => {
    const { getByText } = render(
      <Tabs tabs={[] as any} value="">
        <TabPanel label="Details" value="details"><div>d</div></TabPanel>
        <TabPanel label="History" value="history"><div>h</div></TabPanel>
      </Tabs>
    );
    expect(getByText("Details")).toBeTruthy();
    expect(getByText("History")).toBeTruthy();
  });

  it("opens the tab named by value even when tabs is empty", () => {
    const { container } = render(
      <Tabs tabs={[] as any} value="history">
        <TabPanel label="Details" value="details"><div>d</div></TabPanel>
        <TabPanel label="History" value="history"><div>h</div></TabPanel>
      </Tabs>
    );
    const panel = container.querySelector("[data-tab-panel='history']") as HTMLElement;
    expect(panel.getAttribute("data-tab-active")).toBe("true");
  });

  it("keeps declared tabs authoritative when there is one per child", () => {
    const { container, getByText } = render(
      <Tabs tabs={[{ id: "a", label: "A" }, { id: "b", label: "B" }]} value="b">
        <TabPanel label="ignored" value="x"><div>pa</div></TabPanel>
        <TabPanel label="ignored2" value="y"><div>pb</div></TabPanel>
      </Tabs>
    );
    expect(getByText("A")).toBeTruthy();
    expect(getByText("B")).toBeTruthy();
    expect(container.querySelector("[data-tab-panel='b']")!.getAttribute("data-tab-active")).toBe("true");
  });

  it("does not draw the TabPanel card chrome inside a Tabs", () => {
    // Outside Tabs a TabPanel shows its own heading + border so a stray panel
    // is not an anonymous box; inside, the tab button already carries the label.
    const { container } = render(
      <Tabs tabs={[] as any} value="">
        <TabPanel label="Details" value="details"><div>d</div></TabPanel>
      </Tabs>
    );
    expect(container.querySelectorAll("h3").length).toBe(0);
  });
});
