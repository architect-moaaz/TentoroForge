import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { List } from "../src/components/List/List";
import { Timeline } from "../src/components/Timeline/Timeline";
import { asListItem, asTimelineEntry } from "../src/style/rowShape";

describe("a data row becomes an item", () => {
  // A record page bound its Notes list to the notes of the case; each note
  // has body and createdAt, the List wanted title and subtitle, and every
  // note rendered blank.
  it("titles a note by its body and dates it", () => {
    const item = asListItem({ id: "n1", body: "Guest confirmed the refund.", createdAt: "2026-09-14T08:15:49Z", authorId: "u1" });
    expect(item.title).toBe("Guest confirmed the refund.");
    expect(item.subtitle).toContain("2026");
  });
  it("keeps an authored item as it is", () => {
    expect(asListItem({ title: "Folio", subtitle: "PDF" })).toEqual({ title: "Folio", subtitle: "PDF" });
  });
  it("renders the shaped rows", () => {
    const { container } = render(<List items={[{ body: "First note", createdAt: "2026-09-14T08:00:00Z" }] as any} />);
    expect(container.textContent).toContain("First note");
  });
  it("makes an activity entry from a log row", () => {
    const e = asTimelineEntry({ id: "a1", entryType: "approval_decision", summary: "Stage General Manager approved", occurredAt: "2026-09-14T07:49:48Z" }, 0);
    expect(e.title).toBe("Stage General Manager approved");
    expect(e.timestamp).toBe("2026-09-14T07:49:48Z");
    const { container } = render(<Timeline entries={[e] as any} />);
    expect(container.textContent).toContain("Stage General Manager approved");
  });
});
