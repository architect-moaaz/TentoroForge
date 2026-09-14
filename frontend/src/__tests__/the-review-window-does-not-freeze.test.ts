/**
 * The render-review window settles when the run ends.
 *
 * A long re-compose drops the SSE stream; the panel falls back to polling the
 * run registry, which carries node state but NOT `review` events — so the
 * window never receives its terminal `review:done` and spins on "fixing…
 * round 2" forever, even though the review turn ended. When the run completes,
 * the window must settle instead of freezing.
 */
import { describe, expect, it } from "vitest";

import {
  reduce,
  finalizeReview,
  type BlueprintRun,
  type ReviewState,
} from "@/hooks/useBlueprintRun";

const EMPTY: BlueprintRun = {
  messages: [], thoughts: [], events: [], nodes: [], nodesDone: 0,
  nodesTotal: 0, callsDone: 0, alreadyComplete: [], awaitingApproval: false,
  unbuilt: [], forecast: null, usage: null, status: "running", error: null,
  review: null,
};

// A review caught mid-re-compose: it did work (round 1) but never reached done.
const fixing: ReviewState = {
  phase: "fixing", active: true, round: 1,
  shots: [{ route: "/support-requests/new", image: "data:," }],
  findings: [{ route: "/support-requests/new", kind: "duplicate_control", note: "x" }],
  fixing: ["/support-requests/new"],
};

describe("finalizeReview", () => {
  it("settles a review stuck mid-phase: done, no spinner, still visible", () => {
    const r = finalizeReview(fixing)!;
    expect(r.phase).toBe("done");
    expect(r.fixing).toEqual([]);
    expect(r.active).toBe(true); // round > 0 → it did work, keep it up
    // the work it managed to show is preserved
    expect(r.shots).toHaveLength(1);
    expect(r.findings).toHaveLength(1);
  });

  it("closes a review that never got past start (no work)", () => {
    const r = finalizeReview({ ...fixing, phase: "shots", round: 0, fixing: [] })!;
    expect(r.phase).toBe("done");
    expect(r.active).toBe(false);
  });

  it("leaves an already-done review and a null review untouched", () => {
    const done: ReviewState = { ...fixing, phase: "done", active: true };
    expect(finalizeReview(done)).toBe(done);
    expect(finalizeReview(null)).toBe(null);
  });
});

describe("a completed run settles the review window", () => {
  it("finalizes a mid-phase review on the terminal `done` event", () => {
    const s = reduce({ ...EMPTY, review: fixing }, "done", { report: {} });
    expect(s.status).toBe("complete");
    expect(s.review?.phase).toBe("done");
    expect(s.review?.fixing).toEqual([]);
  });

  it("does not touch the review at the approval-gate pause", () => {
    const s = reduce({ ...EMPTY, review: fixing }, "done", { awaitingApproval: true });
    expect(s.review?.phase).toBe("fixing"); // still going; the build only paused
  });
});
