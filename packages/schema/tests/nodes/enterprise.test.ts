import { describe, it, expect } from "vitest";
import { ActivityFeedNode } from "../../src/nodes/enterprise";

describe("ActivityFeed node — entries binding", () => {
  it("accepts Mustache string binding for entries", () => {
    const r = ActivityFeedNode.safeParse({
      id: "feed",
      type: "ActivityFeed",
      props: {
        entries: "{{stats.latestReviews}}",
        title: "Latest activity",
      },
    });
    expect(r.success).toBe(true);
  });

  it("still accepts an inline array of entries", () => {
    const r = ActivityFeedNode.safeParse({
      id: "feed",
      type: "ActivityFeed",
      props: {
        entries: [
          {
            id: "e1",
            timestamp: "2026-05-12T10:00:00Z",
            actor: { name: "Jane" },
            action: "approved",
            target: "Q1 Vacation Request",
          },
        ],
      },
    });
    expect(r.success).toBe(true);
  });

  it("rejects empty string for entries (must be a valid binding)", () => {
    const r = ActivityFeedNode.safeParse({
      id: "feed",
      type: "ActivityFeed",
      props: { entries: "" },
    });
    expect(r.success).toBe(false);
  });
});
