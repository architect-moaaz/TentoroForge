/**
 * The flowchart while a chat is being watched: the boxes the chat is working on pulse, finished ones are green,
 * failed ones red, held ones amber, and what a chat does to a box outranks a warning about it. Nothing is stored:
 * take the live states away and the boxes are as drawn.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}
if (typeof window !== "undefined" && !(window as any).DOMMatrixReadOnly) {
  (window as any).DOMMatrixReadOnly = class { m22 = 1; constructor(_: unknown) {} };
}
if (typeof window !== "undefined" && !(window as any).matchMedia) {
  window.matchMedia = ((q: string) => ({ matches: false, media: q, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; } })) as unknown as typeof window.matchMedia;
}

import { AgentCanvas } from "../AgentCanvas";
import type { AgentNodeSerialized } from "@/types/agent-builder";
import type { NodeState } from "@/lib/agent-watch";

const node = (id: string, type: "system_prompt" | "tool" | "guardrail", x: number): AgentNodeSerialized => ({
  id, type, position: { x, y: 100 }, data: { label: id, nodeType: type, config: type === "tool" ? { tool_name: id, tool_type: "function" } : { prompt: "x" } },
});
const NODES = [node("guard", "guardrail", 0), node("sp", "system_prompt", 250), node("tool-a", "tool", 500)];

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

async function mount(props: { liveStates?: Record<string, NodeState>; problems?: Record<string, "error" | "warning"> }) {
  await act(async () => {
    root.render(
      <div style={{ width: 900, height: 600 }}>
        <AgentCanvas initialNodes={NODES} initialEdges={[]} {...props} />
      </div>,
    );
  });
}
const box = (id: string) => container.querySelector(`.react-flow__node[data-id="${id}"]`) as HTMLElement;

describe("AgentCanvas, watching a chat", () => {
  it("draws each box by what the chat is doing to it", async () => {
    await mount({ liveStates: { guard: "done", sp: "active", "tool-a": "failed" } });
    expect(box("guard").className).toContain("ring-green-500");
    expect(box("sp").className).toContain("ring-sky-500");
    expect(box("sp").className).toContain("animate-pulse");
    expect(box("tool-a").className).toContain("ring-red-500");
  });

  it("draws a held change amber", async () => {
    await mount({ liveStates: { "tool-a": "held" } });
    expect(box("tool-a").className).toContain("ring-amber-400");
  });

  it("leaves a box the chat has not reached as drawn", async () => {
    await mount({ liveStates: { sp: "active" } });
    expect(box("guard").className).not.toMatch(/ring-(green|sky|red|amber)/);
  });

  it("lets what a chat does outrank a warning about the same box, and keeps the warning on the others", async () => {
    await mount({ liveStates: { sp: "active" }, problems: { sp: "error", guard: "warning" } });
    expect(box("sp").className).toContain("ring-sky-500");
    expect(box("sp").className).not.toContain("ring-red-500");
    expect(box("guard").className).toContain("ring-amber-400");
  });

  it("is as drawn once there is nothing to show", async () => {
    await mount({ liveStates: { sp: "active" } });
    await mount({ liveStates: {} });
    expect(box("sp").className).not.toMatch(/ring-(green|sky|red|amber)/);
    await mount({});
    expect(box("sp").className).not.toMatch(/ring-(green|sky|red|amber)/);
  });
});
