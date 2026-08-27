/**
 * Wide content scrolls inside its own box instead of pushing the box wider.
 *
 * A grid/flex child defaults to `min-width: auto`, which means it refuses to
 * shrink below its content — so a 5-column table in a one-third-width card
 * does not overflow *itself*, it makes the CARD wider and the layout bleeds.
 * `min-w-0` is what lets the box be narrower than what's inside it;
 * `overflow-x-auto` is what makes the excess scroll rather than spill.
 * Both are required — either alone still bleeds.
 *
 * Table/DataGrid/Timeline/Kanban had the overflow half. List, DescriptionList,
 * KeyValueList and ActivityFeed had neither, so a long row widened the card.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { SCROLL_X, scrollEdgeStyle } from "../src/style/scroll";

describe("the horizontal scroll box", () => {
  it("can be narrower than its content", () => {
    expect(SCROLL_X).toContain("min-w-0");
  });

  it("scrolls the excess rather than spilling it", () => {
    expect(SCROLL_X).toContain("overflow-x-auto");
  });

  it("still fills the space it is given", () => {
    expect(SCROLL_X).toContain("w-full");
  });

  it("never scrolls vertically — the page owns that axis", () => {
    expect(SCROLL_X).not.toContain("overflow-y");
    expect(SCROLL_X).not.toContain("overflow-auto");
  });
});

describe("the edge affordance", () => {
  // A cut-off column with no scrollbar (macOS hides them) reads as a broken
  // layout rather than as more content. These shadows appear only when there
  // IS more content: the `local` gradient layers scroll away with the content
  // and uncover the `scroll`-attached shadow underneath.
  const s = scrollEdgeStyle();

  it("pins its layers so they cannot tile", () => {
    expect(s.backgroundRepeat).toBe("no-repeat");
  });

  it("mixes local and scroll attachment — that is what makes it conditional", () => {
    expect(s.backgroundAttachment).toContain("local");
    expect(s.backgroundAttachment).toContain("scroll");
  });

  it("masks with the surface colour so it works on any card", () => {
    expect(String(s.backgroundImage)).toContain("var(--card)");
  });

  it("takes a surface override for non-card surfaces", () => {
    expect(String(scrollEdgeStyle("var(--muted)").backgroundImage))
      .toContain("var(--muted)");
  });
});

// ── every render branch, not just the first one ──────────────────────────
//
// DescriptionList returns a <dl> twice: once for the loading skeleton and
// once for real rows. The first attempt at this fix guarded only the
// skeleton — the branch nobody looks at — and the live page kept bleeding
// while the change looked applied. A component's containment is a property
// of the component, so every root it can return has to carry it.
describe("the guard is on every branch that can render", () => {
  const ROOTS: Record<string, RegExp> = {
    "List/List": /<ul\b/g,
    "DescriptionList/DescriptionList": /<dl\b/g,
    "KeyValueList/KeyValueList": /<dl\b/g,
    "ActivityFeed/ActivityFeed": /<section\b/g,
    "Table/Table": /<table\b/g,
  };

  for (const [mod, rootTag] of Object.entries(ROOTS)) {
    it(`${mod.split("/")[1]} guards each root it returns`, () => {
      const src = readFileSync(
        join(__dirname, "..", "src", "components", `${mod}.tsx`), "utf8");
      const roots = (src.match(rootTag) || []).length;
      const guards = (src.match(/SCROLL_X/g) || []).length - 1;  // minus import
      expect(roots).toBeGreaterThan(0);
      expect(guards).toBeGreaterThanOrEqual(roots);
    });
  }
});
