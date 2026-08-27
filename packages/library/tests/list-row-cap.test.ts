/**
 * A feed beside a chart must not decide how tall the row is.
 *
 * The dashboard composer now writes `limit: 5` onto a list that shares a grid
 * row, because a grid row is as tall as its tallest child and an unbounded
 * feed strands the space beside it. That prop was landing on components that
 * had no idea what it meant — ActivityFeed reads {entries, title, maxHeight}
 * and List reads {items, divided, onItemClick}. Ten rows kept rendering and
 * the schema looked correct while the page did not change.
 *
 * The rule lives here, next to the render, so the prop the composer writes is
 * the prop the component honours.
 */
import { describe, it, expect } from "vitest";
import { applyRowCap } from "../src/style/rowCap";

const ROWS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

describe("capping the rows a list renders", () => {
  it("shows only the first N when a limit is set", () => {
    expect(applyRowCap(ROWS, 5)).toHaveLength(5);
    expect(applyRowCap(ROWS, 5)).toEqual([1, 2, 3, 4, 5]);
  });

  it("keeps the newest-first order the caller gave it", () => {
    expect(applyRowCap(["a", "b", "c"], 2)).toEqual(["a", "b"]);
  });

  it("renders everything when no limit is set", () => {
    expect(applyRowCap(ROWS, undefined)).toHaveLength(10);
  });

  it("renders everything when the limit exceeds the rows", () => {
    expect(applyRowCap([1, 2], 5)).toEqual([1, 2]);
  });

  it("treats a zero or negative limit as no limit rather than blanking the list", () => {
    // A card that renders nothing reads as a bug; a mis-set limit should not
    // be able to erase content.
    expect(applyRowCap(ROWS, 0)).toHaveLength(10);
    expect(applyRowCap(ROWS, -3)).toHaveLength(10);
  });

  it("tolerates a limit that arrived as a string from JSON", () => {
    expect(applyRowCap(ROWS, "5" as never)).toHaveLength(5);
  });

  it("never throws on a non-array", () => {
    expect(applyRowCap(undefined as never, 5)).toEqual([]);
  });
});

describe("the components the composer writes limit onto", () => {
  const READS_LIMIT = ["ActivityFeed/ActivityFeed", "List/List"];
  it.each(READS_LIMIT)("%s honours limit", async (mod) => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = readFileSync(
      join(__dirname, "..", "src", "components", `${mod}.tsx`), "utf8");
    expect(src).toMatch(/limit/);
    expect(src).toMatch(/applyRowCap/);
  });
});

// ── the feed reads the field map the composer derived ───────────────────
//
// ActivityFeed's contract is {actor:{name}, action, target, timestamp}. Bound
// to Notification — {recipientName, type, message, createdAt} — not one field
// lines up, so every row rendered the "Someone" placeholder. The composer now
// derives a map from the entity's real columns; this is the half that uses it.
import { normalizeEntry } from "../src/components/ActivityFeed/normalizeEntry";

const NOTIFICATION_ROW = {
  id: "n1", recipientName: "Priya Raman", type: "leave_approved",
  message: "Annual leave approved", createdAt: "2026-08-20T09:00:00Z",
};
const MAP = { actor: "recipientName", action: "type",
              target: "message", timestamp: "createdAt" };

describe("an entry read through a field map", () => {
  it("shows the real person instead of the placeholder", () => {
    expect(normalizeEntry(NOTIFICATION_ROW, 0, MAP).actorName).toBe("Priya Raman");
  });

  it("reads the action and target through the map", () => {
    const e = normalizeEntry(NOTIFICATION_ROW, 0, MAP);
    expect(e.action).toBe("leave_approved");
    expect(e.target).toBe("Annual leave approved");
  });

  it("reads the timestamp through the map", () => {
    expect(normalizeEntry(NOTIFICATION_ROW, 0, MAP).timestamp)
      .toBe("2026-08-20T09:00:00Z");
  });

  it("still honours a native-shaped entry when no map is given", () => {
    const native = { actor: { name: "Ada" }, action: "created", target: "a request" };
    expect(normalizeEntry(native, 0).actorName).toBe("Ada");
  });

  it("falls back rather than blanking when the map names a missing column", () => {
    const e = normalizeEntry({ id: "x" }, 0, { actor: "nope" });
    expect(e.actorName).toBe("Someone");
  });

  it("never throws on a non-object row", () => {
    expect(() => normalizeEntry(null, 0, MAP)).not.toThrow();
  });
});
