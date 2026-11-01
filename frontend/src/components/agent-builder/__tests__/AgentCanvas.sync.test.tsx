/**
 * AgentCanvas ⇄ AgentBuilderPanel sync.
 *
 * The canvas holds React Flow's own node state and reports it to the panel; the
 * panel hands back `initialNodes` and passes the report handlers INLINE, so they
 * are new functions on every render. The canvas used to list those handlers in
 * its report-effect's dependencies, so every report re-rendered the panel, which
 * made new handlers, which re-ran the effect, which reported again — "Maximum
 * update depth exceeded" the moment an agent was opened.
 *
 * The second half pins the other thing the loop was hiding: a property edited in
 * the panel's side form (the parent's state) has to reach the canvas, or the next
 * drag reports the canvas's stale copy back and the edit is silently undone.
 *
 * jsdom + manual createRoot + act() — same house style as ToolPicker.mcp.test.tsx.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React, { useState } from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
if (typeof window !== "undefined" && !(window as any).DOMMatrixReadOnly) {
  (window as any).DOMMatrixReadOnly = class {
    m22 = 1;
    constructor(_: unknown) {}
  };
}
if (typeof window !== "undefined" && !(window as any).matchMedia) {
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  })) as unknown as typeof window.matchMedia;
}

import { AgentCanvas } from "../AgentCanvas";
import type { Node as RFNode, Edge as RFEdge } from "@xyflow/react";
import type {
  AgentEdgeSerialized,
  AgentNodeData,
  AgentNodeSerialized,
} from "@/types/agent-builder";

const entry = (label = "System Prompt", prompt = "You help."): AgentNodeSerialized => ({
  id: "sp_entry",
  type: "system_prompt",
  position: { x: 250, y: 120 },
  data: { label, nodeType: "system_prompt", config: { prompt, is_entry_point: true } },
});

const tool = (id: string, x: number): AgentNodeSerialized => ({
  id,
  type: "tool",
  position: { x, y: 300 },
  data: { label: id, nodeType: "tool", config: { tool_name: id, tool_type: "function" } },
});

/** The panel's wiring, as AgentBuilderPanel.tsx writes it: state in the parent,
 *  report handlers declared inline in JSX. */
let renders = 0;
let setParentNodes: React.Dispatch<React.SetStateAction<AgentNodeSerialized[]>>;
let parentNodes: AgentNodeSerialized[] = [];
function Panel({ start }: { start: AgentNodeSerialized[] }) {
  const [nodes, setNodes] = useState<AgentNodeSerialized[]>(start);
  const [edges, setEdges] = useState<AgentEdgeSerialized[]>([]);
  renders++;
  setParentNodes = setNodes;
  parentNodes = nodes;
  return (
    <div style={{ width: 800, height: 600 }}>
      <AgentCanvas
        initialNodes={nodes}
        initialEdges={edges}
        onNodesChange={(rf: RFNode[]) =>
          setNodes(
            rf.map((n) => ({
              id: n.id,
              type: (n.data as AgentNodeData).nodeType,
              position: n.position,
              data: n.data as AgentNodeData,
            })),
          )
        }
        onEdgesChange={(rf: RFEdge[]) =>
          setEdges(
            rf.map((e) => ({
              id: e.id,
              source: e.source,
              target: e.target,
              sourceHandle: e.sourceHandle ?? undefined,
              data: e.data as AgentEdgeSerialized["data"] | undefined,
            })),
          )
        }
      />
    </div>
  );
}

let container: HTMLDivElement;
let root: Root;
let errors: string[];

beforeEach(() => {
  renders = 0;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  errors = [];
  vi.spyOn(console, "error").mockImplementation((...a: unknown[]) => {
    errors.push(a.map(String).join(" "));
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function settle() {
  // Let effects and React Flow's measuring/queued updates run to rest.
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
  }
}

describe("AgentCanvas reports to its panel without looping", () => {
  it("opening an agent settles instead of exceeding the update depth", async () => {
    await act(async () => {
      root.render(<Panel start={[entry(), tool("t1", 100)]} />);
    });
    await settle();

    expect(errors.filter((e) => /Maximum update depth/i.test(e))).toEqual([]);
    // A handful of renders (mount, the canvas's first report, React Flow measuring);
    // a loop is hundreds.
    expect(renders).toBeLessThan(25);
  });

  it("an empty agent settles too", async () => {
    await act(async () => {
      root.render(<Panel start={[]} />);
    });
    await settle();
    expect(errors.filter((e) => /Maximum update depth/i.test(e))).toEqual([]);
    expect(renders).toBeLessThan(25);
  });

  it("the panel still receives what the canvas holds", async () => {
    await act(async () => {
      root.render(<Panel start={[entry(), tool("t1", 100)]} />);
    });
    await settle();
    expect(parentNodes.map((n) => n.id).sort()).toEqual(["sp_entry", "t1"]);
    expect(parentNodes.find((n) => n.id === "t1")!.position).toEqual({ x: 100, y: 300 });
  });
});

describe("a property edited in the panel reaches the canvas", () => {
  it("shows the edit, and keeps it when the canvas next reports", async () => {
    await act(async () => {
      root.render(<Panel start={[entry("System Prompt"), tool("t1", 100)]} />);
    });
    await settle();
    const before = renders;

    // The Properties side form edits the parent's copy of a node's data.
    await act(async () => {
      setParentNodes((prev) =>
        prev.map((n) => (n.id === "t1" ? { ...n, data: { ...n.data, label: "look_up_order" } } : n)),
      );
    });
    await settle();

    expect(container.textContent).toContain("look_up_order");
    // …and the canvas did not hand back its stale copy and undo it.
    expect(parentNodes.find((n) => n.id === "t1")!.data.label).toBe("look_up_order");
    // The edit settles in a few renders, it does not start a loop.
    expect(renders - before).toBeLessThan(25);
    expect(errors.filter((e) => /Maximum update depth/i.test(e))).toEqual([]);
  });

  it("keeps a node's position when its data is edited", async () => {
    await act(async () => {
      root.render(<Panel start={[entry(), tool("t1", 100)]} />);
    });
    await settle();
    await act(async () => {
      setParentNodes((prev) =>
        prev.map((n) => (n.id === "t1" ? { ...n, data: { ...n.data, label: "renamed" } } : n)),
      );
    });
    await settle();
    expect(parentNodes.find((n) => n.id === "t1")!.position).toEqual({ x: 100, y: 300 });
  });
});
