/**
 * The stream reads the run ledger, which reports a fan-out node's pages one
 * by one and the node itself once. The card ticks a stage on that one line,
 * and shows the pages as "n of total" until then.
 */
import { describe, expect, it } from "vitest";

import { reduce, type BlueprintRun } from "@/hooks/useBlueprintRun";

const EMPTY: BlueprintRun = {
  messages: [],
  thoughts: [],
  events: [],
  nodes: [],
  nodesDone: 0,
  nodesTotal: 0,
  callsDone: 0,
  alreadyComplete: [],
  awaitingApproval: false,
  unbuilt: [],
  forecast: null,
  usage: null,
  status: "idle",
  error: null,
  review: null,
};

const planned = () =>
  reduce(EMPTY, "plan", { nodes: ["apis", "page_layouts"], total: 2 });

describe("a stage ticks when its node finishes", () => {
  it("keeps a fan-out node running through its pages", () => {
    let s = reduce(planned(), "node:start", { node: "page_layouts", subjects: 3 });
    s = reduce(s, "node:subject", {
      node: "page_layouts", subject: "PAGE-001", index: 1, total: 3, ok: true,
      nodesDone: 0, nodesTotal: 2, callsDone: 1,
    });

    const row = s.nodes.find((n) => n.key === "page_layouts");
    expect(row?.state).toBe("running");
    expect(row?.subject).toBe("1 of 3");
    expect(row?.calls).toBe(1);
    expect(s.nodesDone).toBe(0);
  });

  it("ticks the node on its own done line", () => {
    let s = reduce(planned(), "node:start", { node: "page_layouts", subjects: 3 });
    s = reduce(s, "node:done", { node: "page_layouts", nodesDone: 1, nodesTotal: 2, callsDone: 3 });

    const row = s.nodes.find((n) => n.key === "page_layouts");
    expect(row?.state).toBe("done");
    expect(row?.subject).toBeUndefined();
    expect([s.nodesDone, s.nodesTotal, s.callsDone]).toEqual([1, 2, 3]);
  });

  it("marks a node the ledger failed", () => {
    let s = reduce(planned(), "node:start", { node: "apis", subjects: 1 });
    s = reduce(s, "node:failed", { node: "apis", reason: "no service handler" });
    expect(s.nodes.find((n) => n.key === "apis")?.state).toBe("failed");
  });
});
