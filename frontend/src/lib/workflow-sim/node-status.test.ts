import { describe, it, expect } from "vitest";
import { computeNodeStatuses, computeTakenEdges } from "./node-status";
import type { NodeLogDTO } from "./types";

function log(node_id: string, status: NodeLogDTO["status"], at: string): NodeLogDTO {
  return {
    id: `${node_id}-${status}`, node_id, node_type: "action", node_label: node_id,
    status, output_snapshot: null, error_message: null, started_at: at,
    completed_at: status === "started" ? null : at, duration_ms: status === "started" ? null : 1,
  };
}

describe("computeNodeStatuses", () => {
  it("marks completed and skipped logs as done", () => {
    const s = computeNodeStatuses([log("a", "completed", "1"), log("b", "skipped", "2")], []);
    expect(s).toEqual({ a: "done", b: "done" });
  });

  it("marks a failed log as failed", () => {
    expect(computeNodeStatuses([log("a", "failed", "1")], [])).toEqual({ a: "failed" });
  });

  it("uses the latest log per node by started_at", () => {
    const s = computeNodeStatuses(
      [log("a", "started", "2026-01-01T00:00:00.000Z"), log("a", "completed", "2026-01-02T00:00:00.000Z")],
      [],
    );
    expect(s.a).toBe("done");
  });

  it("forces current (paused) nodes to active even if a stale log exists", () => {
    const s = computeNodeStatuses([log("a", "started", "1")], ["a"]);
    expect(s.a).toBe("active");
  });

  it("marks a current node with no log as active", () => {
    expect(computeNodeStatuses([], ["x"])).toEqual({ x: "active" });
  });
});

describe("computeTakenEdges", () => {
  it("returns edges whose source is done and target has been reached", () => {
    const statuses = { a: "done", b: "active" } as const;
    const edges = [
      { id: "e1", source: "a", target: "b" },
      { id: "e2", source: "a", target: "c" }, // c not reached
    ];
    expect(computeTakenEdges(statuses, edges)).toEqual(["e1"]);
  });
});
