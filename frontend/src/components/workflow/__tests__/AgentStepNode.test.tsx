/**
 * The agent step as it looks on the canvas: its icon, its label, and a small badge with the assistant's name and how
 * much it may do by itself.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { WorkflowNode } from "../nodes/WorkflowNode";
import { AssistantNamesContext } from "../agentStepData";
import { NodePalette } from "../NodePalette";
import { NODE_CATEGORIES } from "@/types/workflow";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(config: Record<string, unknown>, names: Record<string, string> = {}, label = "Triage") {
  const props = { id: "agent_step_1", data: { label, nodeType: "agent_step", config }, selected: false } as any;
  act(() => {
    root.render(
      <ReactFlowProvider>
        <AssistantNamesContext.Provider value={names}>
          <WorkflowNode {...props} />
        </AssistantNamesContext.Provider>
      </ReactFlowProvider>,
    );
  });
}
const badge = () => container.querySelector('[data-testid="agent-step-badge"]') as HTMLElement | null;

describe("agent step on the canvas", () => {
  it("shows its label, the bot icon on the AI gradient, and how many answers it hands back", () => {
    render({ agentId: "wf_triage", outputFields: [{ name: "a" }, { name: "b" }, { name: "c" }] }, { wf_triage: "Triage helper" });
    expect(container.textContent).toContain("Triage");
    expect(container.textContent).toContain("3 answers");
    expect(container.querySelector("svg.lucide-bot")).toBeTruthy();
    expect(container.querySelector('div[class*="bg-gradient-to-br"]')).toBeTruthy();
  });

  it("badges the assistant's name and the autonomy (Suggest by default)", () => {
    render({ agentId: "wf_triage" }, { wf_triage: "Triage helper" });
    expect(badge()!.textContent).toBe("Triage helperSuggest");
  });

  it("falls back to the id until the name is known, and says so when there is no assistant yet", () => {
    render({ agentId: "wf_triage" });
    expect(badge()!.textContent).toBe("wf_triageSuggest");
    render({});
    expect(badge()!.textContent).toBe("No assistant yetSuggest");
    render({ agentBrief: { purpose: "Triage", reads: [] } });
    expect(badge()!.textContent).toBe("Assistant plannedSuggest");
  });

  it("makes Limited and Full stand out, because they can change data", () => {
    render({ agentId: "a", autonomy: "limited" });
    expect(badge()!.textContent).toBe("aLimited");
    expect(badge()!.innerHTML).toMatch(/bg-amber-100/);
    render({ agentId: "a", autonomy: "full" });
    expect(badge()!.textContent).toBe("aFull");
    expect(badge()!.innerHTML).toMatch(/bg-amber-100/);
    render({ agentId: "a", autonomy: "suggest" });
    expect(badge()!.innerHTML).not.toMatch(/bg-amber-100/);
  });

  it("has an in handle and an out handle, and no else handle", () => {
    render({ agentId: "a" });
    expect(container.querySelector(".react-flow__handle.target")).toBeTruthy();
    expect(container.querySelectorAll(".react-flow__handle.source")).toHaveLength(1);
    expect(container.querySelector('.react-flow__handle[data-handleid="else"]')).toBeNull();
    expect(container.textContent).not.toContain("2 out");
  });

  it("does not put the badge on other steps", () => {
    const props = { id: "n", data: { label: "Gen", nodeType: "ai_generate", config: {} }, selected: false } as any;
    act(() => root.render(<ReactFlowProvider><WorkflowNode {...props} /></ReactFlowProvider>));
    expect(badge()).toBeNull();
  });

  it("survives a config that is the wrong shape", () => {
    expect(() => render({ agentId: { oops: 1 }, outputFields: "no", autonomy: 7 })).not.toThrow();
    expect(badge()!.textContent).toBe("No assistant yetSuggest");
  });
});

describe("agent step in the palette", () => {
  it("is drawn under AI Nodes, can be dragged, and carries its safe defaults", () => {
    act(() => root.render(<NodePalette />));
    const entry = NODE_CATEGORIES.find((c) => c.label === "AI Nodes")!.nodes.find((n) => n.type === "agent_step")!;
    const card = [...container.querySelectorAll('[draggable="true"]')].find((e) => e.textContent?.includes(entry.label)) as HTMLElement;
    expect(card, "a draggable card named like the catalog entry").toBeTruthy();
    expect(card.querySelector("svg.lucide-bot")).toBeTruthy();
    const store: Record<string, string> = {};
    const event = new Event("dragstart", { bubbles: true }) as any;
    event.dataTransfer = { setData: (k: string, v: string) => { store[k] = v; }, effectAllowed: "" };
    act(() => { card.dispatchEvent(event); });
    expect(store["application/workflow-node-type"]).toBe("agent_step");
    expect(JSON.parse(store["application/workflow-node-config"])).toMatchObject({ autonomy: "suggest", onFailure: "human" });
  });
});
