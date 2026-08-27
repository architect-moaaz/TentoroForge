/**
 * Regression tests: softened validators for Timeline, DataGrid,
 * ActivityFeed, and EmptyStateRich.
 *
 * Each component must accept a minimal { type: "X" } node (or one that omits
 * all previously-required fields) without rejection, so that LLM-generated
 * schemas that omit optional data still render instead of showing
 * "⚠ invalid props" placeholders.
 */
import { describe, it, expect } from "vitest";
import { TimelineNode, DataGridNode } from "../../src/nodes/data-display";
import { ActivityFeedNode, EmptyStateRichNode } from "../../src/nodes/enterprise";

// ── Timeline ──────────────────────────────────────────────────────────────────

describe("TimelineNode — softened", () => {
  it("accepts minimal node with no props at all", () => {
    const r = TimelineNode.safeParse({ type: "Timeline", props: {} });
    expect(r.success).toBe(true);
  });

  it("defaults entries to []", () => {
    const r = TimelineNode.parse({ type: "Timeline", props: {} });
    expect(r.props.entries).toEqual([]);
  });

  it("accepts a Mustache binding string for entries", () => {
    const r = TimelineNode.safeParse({
      type: "Timeline",
      props: { entries: "{{activityHistory}}" },
    });
    expect(r.success).toBe(true);
  });

  it("accepts a populated entries array", () => {
    const r = TimelineNode.safeParse({
      type: "Timeline",
      props: {
        entries: [
          { timestamp: "2026-01-01T00:00:00Z", title: "Request submitted", status: "pending" },
        ],
      },
    });
    expect(r.success).toBe(true);
  });

  it("accepts optional className + style", () => {
    const r = TimelineNode.safeParse({
      type: "Timeline",
      props: { className: "mt-4", style: { color: "red" } },
    });
    expect(r.success).toBe(true);
  });
});

// ── DataGrid ──────────────────────────────────────────────────────────────────

describe("DataGridNode — softened", () => {
  it("accepts minimal node with no props at all", () => {
    const r = DataGridNode.safeParse({ type: "DataGrid", props: {} });
    expect(r.success).toBe(true);
  });

  it("defaults columns to [], rows to [], rowKey to 'id'", () => {
    const r = DataGridNode.parse({ type: "DataGrid", props: {} });
    expect(r.props.columns).toEqual([]);
    expect(r.props.rows).toEqual([]);
    expect(r.props.rowKey).toBe("id");
  });

  it("still accepts populated columns + rows", () => {
    const r = DataGridNode.safeParse({
      type: "DataGrid",
      props: {
        columns: [{ key: "name", label: "Name" }],
        rows: [{ name: "Alice" }],
        rowKey: "name",
      },
    });
    expect(r.success).toBe(true);
  });

  it("accepts optional className + style", () => {
    const r = DataGridNode.safeParse({
      type: "DataGrid",
      props: { className: "w-full", style: { borderRadius: "8px" } },
    });
    expect(r.success).toBe(true);
  });
});

// ── ActivityFeed ──────────────────────────────────────────────────────────────

describe("ActivityFeedNode — softened", () => {
  it("accepts minimal node with no props at all", () => {
    const r = ActivityFeedNode.safeParse({ type: "ActivityFeed", props: {} });
    expect(r.success).toBe(true);
  });

  it("defaults entries to []", () => {
    const r = ActivityFeedNode.parse({ type: "ActivityFeed", props: {} });
    expect(r.props.entries).toEqual([]);
  });

  it("still accepts a Mustache binding string for entries", () => {
    const r = ActivityFeedNode.safeParse({
      type: "ActivityFeed",
      props: { entries: "{{stats.latestReviews}}" },
    });
    expect(r.success).toBe(true);
  });

  it("still accepts an inline array of entries", () => {
    const r = ActivityFeedNode.safeParse({
      type: "ActivityFeed",
      props: {
        entries: [
          {
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

  it("accepts optional className + style", () => {
    const r = ActivityFeedNode.safeParse({
      type: "ActivityFeed",
      props: { className: "mt-4", style: { maxHeight: "400px" } },
    });
    expect(r.success).toBe(true);
  });
});

// ── EmptyStateRich ────────────────────────────────────────────────────────────

describe("EmptyStateRichNode — softened", () => {
  it("accepts minimal node with no props at all", () => {
    const r = EmptyStateRichNode.safeParse({ type: "EmptyStateRich", props: {} });
    expect(r.success).toBe(true);
  });

  it("defaults heading to 'No data'", () => {
    const r = EmptyStateRichNode.parse({ type: "EmptyStateRich", props: {} });
    expect(r.props.heading).toBe("No data");
  });

  it("still accepts a full heading", () => {
    const r = EmptyStateRichNode.safeParse({
      type: "EmptyStateRich",
      props: { heading: "No Related Items", icon: "inbox" },
    });
    expect(r.success).toBe(true);
  });

  it("accepts primaryCta with no fields (all optional)", () => {
    const r = EmptyStateRichNode.safeParse({
      type: "EmptyStateRich",
      props: {
        heading: "Empty",
        primaryCta: {},
      },
    });
    expect(r.success).toBe(true);
  });

  it("accepts primaryCta with navigate action", () => {
    const r = EmptyStateRichNode.safeParse({
      type: "EmptyStateRich",
      props: {
        heading: "No Leave Requests",
        primaryCta: {
          label: "New Request",
          action: { type: "navigate", to: "/leave-requests/new" },
        },
      },
    });
    expect(r.success).toBe(true);
  });

  it("accepts optional className + style", () => {
    const r = EmptyStateRichNode.safeParse({
      type: "EmptyStateRich",
      props: { className: "py-16", style: { background: "white" } },
    });
    expect(r.success).toBe(true);
  });
});
