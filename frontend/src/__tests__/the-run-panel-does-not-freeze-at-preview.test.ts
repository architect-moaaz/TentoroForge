/**
 * A completed run leaves no node still spinning.
 *
 * `preview` is the last node before the run ends. If its `node:done` is missed
 * — a stream that blinks just before the terminal event, or a poll that catches
 * the run on `preview` and then only sees the status flip to complete — the
 * panel used to sit at "preview running" forever, indistinguishable from a
 * genuinely stuck build. A `done` that ends the run must settle the nodes too.
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

// A run that has reached its last node with `preview` still running — the
// `node:done` for it has not arrived.
const atPreview = () => {
  let s = reduce(EMPTY, "plan", { nodes: ["page_layouts", "preview"], total: 2 });
  s = reduce(s, "node:done", { node: "page_layouts", nodesDone: 1, nodesTotal: 2 });
  s = reduce(s, "node:start", { node: "preview", subjects: 1 });
  return s;
};

describe("the run panel does not freeze at preview", () => {
  it("settles a lingering running node when the run completes", () => {
    const before = atPreview();
    expect(before.nodes.find((n) => n.key === "preview")?.state).toBe("running");

    const s = reduce(before, "done", { report: {} });
    expect(s.status).toBe("complete");
    expect(s.nodes.find((n) => n.key === "preview")?.state).toBe("done");
    expect(s.nodes.every((n) => n.state === "done")).toBe(true);
  });

  it("does not force nodes done when the run only paused at the approval gate", () => {
    // `awaitingApproval` is a checkpoint, not an end — the plan legitimately has
    // not run past the definition, so a waiting node must stay waiting.
    let s = reduce(EMPTY, "plan", { nodes: ["requirements", "pages"], total: 2 });
    s = reduce(s, "node:start", { node: "requirements", subjects: 1 });
    s = reduce(s, "done", { awaitingApproval: true });
    expect(s.awaitingApproval).toBe(true);
    expect(s.nodes.find((n) => n.key === "requirements")?.state).toBe("running");
  });

  it("leaves a failed node failed, not overwritten to done", () => {
    let s = reduce(EMPTY, "plan", { nodes: ["apis", "preview"], total: 2 });
    s = reduce(s, "node:failed", { node: "apis", reason: "no handler" });
    s = reduce(s, "node:start", { node: "preview", subjects: 1 });
    s = reduce(s, "done", { report: {} });
    expect(s.nodes.find((n) => n.key === "apis")?.state).toBe("failed");
    expect(s.nodes.find((n) => n.key === "preview")?.state).toBe("done");
  });
});
