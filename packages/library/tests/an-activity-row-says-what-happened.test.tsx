import { describe, it, expect } from "vitest";
import { normalizeEntry } from "../src/components/ActivityFeed/normalizeEntry";

describe("an activity row says what happened", () => {
  // The dashboard's Recent activity showed "Someone" doing nothing at no time.
  it("reads a log entry's summary, time and category", () => {
    const e = normalizeEntry({ id: "a1", entryType: "approval_decision", summary: "Stage General Manager approved", occurredAt: "2026-09-14T07:49:48Z", userId: "u1" }, 0);
    expect(e.action).toBe("Stage General Manager approved");
    expect(e.timestamp).toBe("2026-09-14T07:49:48Z");
    expect(e.actorName).toBe("");
    expect(e.category).toBe("approve");
  });
  it("keeps a native entry", () => {
    const e = normalizeEntry({ actor: { name: "Ana" }, action: "approved", target: "Q1", timestamp: "2026-01-01T00:00:00Z" }, 0);
    expect(e.actorName).toBe("Ana");
  });
});
