/**
 * Regression — docs/editor-audit/panels.md, "PageGen — addPage overwrites an
 * existing page and its undo deletes it".
 *
 * The store-level contract this locks in: a colliding "New page" is REFUSED
 * with a message the UI already surfaces (PagePicker.tsx checks lastError
 * before flushing), the existing page's node tree is untouched, and no undo
 * entry is pushed — so Ctrl-Z cannot delete a page the create never made.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useEditorStore } from "@/lib/editor-store";

const ROOT_ID = "existing-root";

function seed() {
  useEditorStore.setState({
    artifacts: {
      pageSchemas: {
        items: {
          schemaVersion: "2", id: "items", route: "/items",
          root: { id: ROOT_ID, type: "Stack", props: {}, children: [] },
        },
      },
      navFlow: {
        version: "1.0", initialPage: "items",
        pages: [{ id: "items", route: "/items", title: "Items",
                  schemaFile: "src/schemas/items.json", params: [] }],
        transitions: [], guards: {},
      },
      tokens: {},
    } as never,
    undoStack: [], redoStack: [], lastError: null, isDirty: false,
  });
}

function state() {
  const s = useEditorStore.getState();
  return {
    pages: s.artifacts as never as {
      pageSchemas: Record<string, { root: { id: string } }>;
      navFlow: { pages: Array<{ id: string }> };
    },
    undoStack: s.undoStack,
    lastError: s.lastError,
  };
}

beforeEach(seed);

describe("addPage — a collision is refused, never absorbed", () => {
  it("keeps the existing page's tree and pushes no undo entry", () => {
    useEditorStore.getState().dispatch({
      type: "addPage", pageId: "items", route: "/items-2", title: "Items",
      root: { id: "brand-new", type: "Stack", props: {}, children: [] },
    } as never);
    const s = state();
    expect(s.lastError).toMatch(/already exists/);
    expect(s.pages.pageSchemas.items.root.id).toBe(ROOT_ID);
    expect(s.pages.navFlow.pages).toHaveLength(1);
    // No undo entry — so Ctrl-Z cannot remove the page that was already there.
    expect(s.undoStack).toHaveLength(0);
  });

  it("refuses a route collision even when the page id is new", () => {
    useEditorStore.getState().dispatch({
      type: "addPage", pageId: "products", route: "/items", title: "Products",
      root: { id: "p-root", type: "Stack", props: {}, children: [] },
    } as never);
    const s = state();
    expect(s.lastError).toMatch(/already served by page "items"/);
    expect(Object.keys(s.pages.pageSchemas)).toEqual(["items"]);
    expect(s.undoStack).toHaveLength(0);
  });

  it("a genuinely new page is added, and undo removes only it", () => {
    const store = useEditorStore.getState();
    store.dispatch({
      type: "addPage", pageId: "about", route: "/about", title: "About",
      root: { id: "a-root", type: "Stack", props: {}, children: [] },
    } as never);
    expect(state().lastError).toBeNull();
    expect(state().pages.pageSchemas.about).toBeDefined();
    useEditorStore.getState().undo();
    const s = state();
    expect(s.pages.pageSchemas.about).toBeUndefined();
    expect(s.pages.pageSchemas.items.root.id).toBe(ROOT_ID);
    expect(s.pages.navFlow.pages.map((p) => p.id)).toEqual(["items"]);
  });
});
