import { describe, it, expect, beforeEach } from "vitest";
import { createEditorStore } from "../../src/state/store";
import { selectSuggestions } from "../../src/state/selectors";

const page = (): any => ({
  schemaVersion: "1",
  id: "p",
  route: "/",
  root: {
    id: "r",
    type: "Stack",
    children: [
      { id: "btn", type: "IconButton", props: {} }, // missing aria-label → rule fires
    ],
  },
});

let store: ReturnType<typeof createEditorStore>;

beforeEach(() => {
  store = createEditorStore();
  store.getState().openPage("p", page());
});

describe("suggestions on page open", () => {
  it("populates suggestions from rule engine on page open", () => {
    expect(store.getState().pages["p"].suggestions.length).toBeGreaterThan(0);
    expect(store.getState().pages["p"].suggestions[0].ruleId).toBe("iconbutton-aria-label");
  });

  it("starts with empty dismissedIds", () => {
    expect(store.getState().pages["p"].dismissedIds).toEqual([]);
  });
});

describe("dismissSuggestion", () => {
  it("adds id to dismissedIds", () => {
    const sid = store.getState().pages["p"].suggestions[0].id;
    store.getState().dismissSuggestion(sid);
    expect(store.getState().pages["p"].dismissedIds).toContain(sid);
  });

  it("selectSuggestions filters out dismissed ids", () => {
    const sid = store.getState().pages["p"].suggestions[0].id;
    store.getState().dismissSuggestion(sid);
    const active = selectSuggestions(store.getState());
    expect(active.map((s) => s.id)).not.toContain(sid);
  });
});

describe("appendLlmSuggestions", () => {
  it("merges LLM suggestions into the page's suggestions", () => {
    store.getState().appendLlmSuggestions("p", [
      {
        id: "llm:abc",
        source: "llm",
        severity: "info",
        title: "Test LLM suggestion",
        description: "An LLM suggestion",
      },
    ]);
    const ids = store.getState().pages["p"].suggestions.map((s) => s.id);
    expect(ids).toContain("llm:abc");
  });

  it("de-dupes by id", () => {
    const s = {
      id: "llm:dup",
      source: "llm" as const,
      severity: "info" as const,
      title: "Dup",
      description: "dup",
    };
    store.getState().appendLlmSuggestions("p", [s]);
    store.getState().appendLlmSuggestions("p", [s]);
    const count = store
      .getState()
      .pages["p"].suggestions.filter((x) => x.id === "llm:dup").length;
    expect(count).toBe(1);
  });

  it("ignores unknown path", () => {
    expect(() =>
      store.getState().appendLlmSuggestions("nonexistent", [])
    ).not.toThrow();
  });
});

describe("applySuggestion", () => {
  it("applies the fix mutation and auto-dismisses", () => {
    // Add a suggestion with a fix
    store.getState().appendLlmSuggestions("p", [
      {
        id: "rule:fix-test",
        source: "rule",
        severity: "warn",
        title: "Fix test",
        description: "test",
        fix: {
          kind: "set-prop",
          id: "btn",
          key: "aria-label",
          value: "Close",
          prevValue: undefined,
        },
      },
    ]);
    store.getState().applySuggestion("rule:fix-test");
    // Should be dismissed
    expect(store.getState().pages["p"].dismissedIds).toContain("rule:fix-test");
    // Prop should be set
    const root = store.getState().pages["p"].schema.root as any;
    const btn = root.children[0];
    expect(btn.props["aria-label"]).toBe("Close");
  });

  it("no-ops if suggestion has no fix", () => {
    const sid = store.getState().pages["p"].suggestions[0].id;
    // iconbutton-aria-label rule has no fix
    expect(() => store.getState().applySuggestion(sid)).not.toThrow();
  });
});

describe("suggestions refreshed after mutations", () => {
  it("re-runs rules after apply", () => {
    // Initially has iconbutton-aria-label warning
    const before = store.getState().pages["p"].suggestions.length;
    expect(before).toBeGreaterThan(0);

    // Fix the aria-label via apply
    store.getState().apply({
      kind: "set-prop",
      id: "btn",
      key: "aria-label",
      value: "Close",
      prevValue: undefined,
    });

    const after = store.getState().pages["p"].suggestions;
    // Should no longer have iconbutton-aria-label
    expect(after.some((s) => s.ruleId === "iconbutton-aria-label")).toBe(false);
  });

  it("re-runs rules after undo", () => {
    // First add aria-label
    store.getState().apply({
      kind: "set-prop",
      id: "btn",
      key: "aria-label",
      value: "Close",
      prevValue: undefined,
    });
    expect(
      store.getState().pages["p"].suggestions.some((s) => s.ruleId === "iconbutton-aria-label")
    ).toBe(false);

    // Undo should bring back the warning
    store.getState().undo();
    expect(
      store.getState().pages["p"].suggestions.some((s) => s.ruleId === "iconbutton-aria-label")
    ).toBe(true);
  });

  it("re-runs rules after redo", () => {
    store.getState().apply({
      kind: "set-prop",
      id: "btn",
      key: "aria-label",
      value: "Close",
      prevValue: undefined,
    });
    store.getState().undo();
    store.getState().redo();
    expect(
      store.getState().pages["p"].suggestions.some((s) => s.ruleId === "iconbutton-aria-label")
    ).toBe(false);
  });
});

describe("selectSuggestions", () => {
  it("returns non-dismissed suggestions for current page", () => {
    const all = store.getState().pages["p"].suggestions;
    const active = selectSuggestions(store.getState());
    expect(active.length).toBe(all.length);
  });

  it("returns empty array when no page is open", () => {
    const emptyStore = createEditorStore();
    expect(selectSuggestions(emptyStore.getState())).toEqual([]);
  });
});
