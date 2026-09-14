import { describe, it, expect } from "vitest";
import { ListNode } from "../../src/nodes/display";
import { TimelineNode } from "../../src/nodes/data-display";

describe("a List item may be a data row", () => {
  it("keeps a note's own columns", () => {
    const r = ListNode.safeParse({ type: "List", props: { items: [
      { title: "Folio", subtitle: "PDF" },
      { id: "n1", body: "Guest confirmed the refund.", createdAt: "2026-09-14T08:15:49Z" },
    ] } });
    expect(r.success).toBe(true);
    if (r.success) expect((r.data.props.items[1] as any).body).toBe("Guest confirmed the refund.");
  });
  it("still refuses an empty list", () => {
    expect(ListNode.safeParse({ type: "List", props: { items: [] } }).success).toBe(false);
  });
  it("admits a bound data source, like Table.rows", () => {
    // A record page binds a List to a child collection. The composer writes
    // `items: "{{condition_evidences}}"`; admitting only a literal array made
    // that fail strict validation and the whole page fell back to "as-is".
    const r = ListNode.safeParse({
      type: "List", props: { divided: true, items: "{{condition_evidences}}" },
    });
    expect(r.success).toBe(true);
  });
});

describe("a Timeline entry may be a data row", () => {
  it("keeps an activity log entry's own columns", () => {
    const r = TimelineNode.safeParse({ type: "Timeline", props: { entries: [
      { id: "a1", entryType: "approval_decision", summary: "Stage General Manager approved", occurredAt: "2026-09-14T07:49:48Z" },
    ] } });
    expect(r.success).toBe(true);
  });
});
