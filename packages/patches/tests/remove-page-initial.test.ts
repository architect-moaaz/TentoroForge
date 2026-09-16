/**
 * ED-14 — deleting a page from the editor.
 *
 * `removePage` already removed the page from `pageSchemas` and `navFlow.pages`
 * and scrubbed referencing transitions. It did NOT touch `navFlow.initialPage`,
 * which nothing exercised because no UI could reach the action at all.
 *
 * The moment a delete control exists, the entry page is deletable like any
 * other — and a dangling `initialPage` is not a cosmetic leftover:
 * `validateNavConsistency` rejects it outright ("navFlow.initialPage=… unknown"),
 * so the artifacts fail their own validation and the generated app opens on a
 * page that is no longer there.
 */
import { describe, it, expect } from "vitest";
import { applyAction } from "../src/apply";
import { validateNavConsistency } from "../src/validate";
import type { Artifacts, EditorAction } from "../src/types";

const page = (id: string, route: string) => ({
  schemaVersion: "2" as const,
  id,
  route,
  root: { id: `${id}_root`, type: "Stack", children: [] },
});

function fixture(initialPage = "home"): Artifacts {
  return {
    pageSchemas: {
      home: page("home", "/"),
      about: page("about", "/about"),
      contact: page("contact", "/contact"),
    },
    navFlow: {
      initialPage,
      pages: [
        { id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] },
        { id: "about", route: "/about", title: "About", schemaFile: "src/schemas/about.json", params: [] },
        { id: "contact", route: "/contact", title: "Contact", schemaFile: "src/schemas/contact.json", params: [] },
      ],
      transitions: [
        { id: "t1", from: "home", to: "about" },
        { id: "t2", from: "about", to: "contact" },
      ],
    },
    tokens: {},
  } as unknown as Artifacts;
}

const del = (a: Artifacts, pageId: string) =>
  applyAction(a, { type: "removePage", pageId } as EditorAction);

describe("removePage — the entry page", () => {
  it("hands initialPage to the next remaining page when the entry page goes", () => {
    const { next } = del(fixture("home"), "home");
    expect(next.navFlow.initialPage).toBe("about");
  });

  it("leaves initialPage alone when some OTHER page is deleted", () => {
    const { next } = del(fixture("home"), "about");
    expect(next.navFlow.initialPage).toBe("home");
  });

  it("leaves no entry to name when the last page goes", () => {
    let a = fixture("home");
    a = del(a, "about").next;
    a = del(a, "contact").next;
    a = del(a, "home").next;
    expect(a.navFlow.pages).toEqual([]);
    expect(a.navFlow.initialPage).toBeUndefined();
  });

  it("leaves artifacts that still pass nav validation", () => {
    // This is the assertion that matters: before the fix, initialPage pointed at
    // the deleted page and this returned an error.
    const { next } = del(fixture("home"), "home");
    expect(validateNavConsistency(next)).toEqual([]);
  });

  it("still scrubs every transition touching the deleted page", () => {
    const { next } = del(fixture("home"), "about");
    expect(next.navFlow.transitions).toEqual([]);
  });
});

describe("removePage — undo restores the entry, not just the page", () => {
  it("undo of deleting the entry page puts initialPage back", () => {
    const before = fixture("home");
    const { next, inverse } = del(before, "home");
    expect(next.navFlow.initialPage).toBe("about");

    const restored = applyAction(next, inverse).next;
    expect(restored.navFlow.initialPage).toBe("home");
    expect(restored.pageSchemas.home).toBeDefined();
  });

  it("undo of deleting a NON-entry page does not steal the entry", () => {
    const before = fixture("home");
    const { next, inverse } = del(before, "about");
    const restored = applyAction(next, inverse).next;
    expect(restored.navFlow.initialPage).toBe("home");
  });

  it("the round trip restores title, route and the node tree", () => {
    const before = fixture("home");
    const { next, inverse } = del(before, "about");
    const restored = applyAction(next, inverse).next;
    const nav = restored.navFlow.pages.find((p) => p.id === "about");
    expect(nav?.title).toBe("About");
    expect(nav?.route).toBe("/about");
    expect(restored.pageSchemas.about.root).toEqual(before.pageSchemas.about.root);
  });

  it("a plain addPage does not silently claim the entry", () => {
    // `wasInitialPage` is removePage's private channel back to its own undo.
    // An ordinary "new page" must never move the entry point.
    const { next } = applyAction(fixture("home"), {
      type: "addPage", pageId: "extra", route: "/extra", title: "Extra",
      root: { id: "extra_root", type: "Stack", children: [] },
    } as EditorAction);
    expect(next.navFlow.initialPage).toBe("home");
  });
});
