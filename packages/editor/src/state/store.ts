import { create, type StoreApi, type UseBoundStore } from "zustand";
import { produce } from "immer";
import type { Page } from "@tentoroforge/schema";
import type { TokenGroups } from "@tentoroforge/library";
import type { ClipboardState, EditorState, Mutation, NodeId, PageState, SchemaPath, Suggestion, Viewport } from "./types";
import { dispatchApply, invert, findNodeDeep, findParentId, findIndexInParent, cloneNodeWithFreshIds, buildRemoveNode, buildBulkRemove } from "./mutations";
import { selectCurrentPage } from "./selectors";
import { runRules } from "../suggestions/runner";

const HISTORY_LIMIT = 100;

function makePageState(schemaPath: SchemaPath, schema: Page): PageState {
  return {
    schemaPath,
    schema,
    schemaVersion: 0,
    selection: [],
    hoverNodeId: null,
    history: [],
    redoStack: [],
    saveState: "clean",
    saveError: null,
    lastSavedAt: null,
    lastSavedSchema: schema,
    // Validation runs synchronously inline below was the original behaviour, but
    // for rich v2 schemas (deep recursive node unions, ~80 nodes) Page.safeParse
    // can spend 1-5s on the main thread per call — and store.ts calls it on every
    // open/apply/undo/redo. validationErrors isn't consumed by any UI component,
    // so we leave it empty here and let validate.test.ts re-parse on demand.
    validationErrors: [],
    openedAt: Date.now(),
    suggestions: runRules(schema, {}),
    dismissedIds: [],
  };
}

export type EditorStoreActions = {
  // Page management
  openPage: (path: SchemaPath, schema: Page) => void;
  switchPage: (path: SchemaPath) => void;
  closePage: (path: SchemaPath) => void;
  // Per-page mutations (target current page)
  apply: (m: Mutation) => void;
  undo: () => void;
  redo: () => void;
  selectNode: (id: NodeId) => void;
  toggleSelection: (id: NodeId) => void;
  clearSelection: () => void;
  setHover: (id: NodeId | null) => void;
  setDrag: (drag: Partial<EditorState["drag"]>) => void;
  setSaveState: (state: PageState["saveState"], error?: string | null) => void;
  markSaved: (savedSchema: Page) => void;
  // Clipboard
  copyToClipboard: () => void;
  cutToClipboard: () => void;
  pasteFromClipboard: () => void;
  // Bulk operations
  deleteSelection: () => void;
  // Theme
  loadTheme: (tokens: TokenGroups, source: "default" | "custom") => void;
  setTokenValue: (group: string, name: string, value: string) => void;
  markThemeSaved: () => void;
  // Suggestions
  dismissSuggestion: (id: string) => void;
  appendLlmSuggestions: (path: SchemaPath, suggestions: Suggestion[]) => void;
  applySuggestion: (id: string) => void;
  // Viewport
  setViewport: (v: Viewport) => void;
};

export type EditorStore = EditorState & EditorStoreActions;

/** The Zustand store instance type returned by createEditorStore. */
export type EditorStoreApi = UseBoundStore<StoreApi<EditorStore>>;

export function createEditorStore(): EditorStoreApi {
  return create<EditorStore>((set, _get) => {
    const withCurrent = (fn: (page: PageState) => void) =>
      set((state) =>
        produce(state, (d) => {
          if (!d.currentPath) return;
          const p = d.pages[d.currentPath];
          if (!p) return;
          fn(p as PageState);
        })
      );

    return {
      pages: {},
      currentPath: null,
      drag: { sourceKind: null, sourcePayload: null, overTargetId: null, overPosition: null },
      clipboard: null,
      historyLimit: HISTORY_LIMIT,
      theme: null,
      themeSource: null,
      themeDirty: false,
      viewport: "desktop" as Viewport,

      openPage(path, schema) {
        set((state) =>
          produce(state, (d) => {
            if (!d.pages[path]) {
              d.pages[path] = makePageState(path, schema) as any;
            }
            d.currentPath = path;
          })
        );
      },

      switchPage(path) {
        set((state) =>
          produce(state, (d) => {
            if (d.pages[path]) d.currentPath = path;
          })
        );
      },

      closePage(path) {
        set((state) =>
          produce(state, (d) => {
            delete d.pages[path];
            if (d.currentPath === path) {
              const remaining = Object.values(d.pages as Record<string, PageState>).sort(
                (a, b) => b.openedAt - a.openedAt
              );
              d.currentPath = remaining[0]?.schemaPath ?? null;
            }
          })
        );
      },

      apply(m) {
        withCurrent((p) => {
          dispatchApply(p.schema, m);
          p.schemaVersion++;
          p.history.push(m);
          if (p.history.length > HISTORY_LIMIT) p.history.shift();
          p.redoStack = [];
          p.saveState = "dirty";
          // Skipped on the hot path — see makePageState comment.
          // Keep only LLM suggestions; refresh rule suggestions
          const llmSuggestions = p.suggestions.filter((s) => s.source === "llm");
          p.suggestions = [...runRules(p.schema, {}), ...llmSuggestions];
        });
      },

      undo() {
        withCurrent((p) => {
          if (p.history.length === 0) return;
          const m = p.history[p.history.length - 1];
          dispatchApply(p.schema, invert(m));
          p.history.pop();
          p.redoStack.push(m);
          p.schemaVersion++;
          // Skipped on the hot path — see makePageState comment.
          p.saveState =
            JSON.stringify(p.schema) === JSON.stringify(p.lastSavedSchema) ? "clean" : "dirty";
          const llmSuggestions = p.suggestions.filter((s) => s.source === "llm");
          p.suggestions = [...runRules(p.schema, {}), ...llmSuggestions];
        });
      },

      redo() {
        withCurrent((p) => {
          if (p.redoStack.length === 0) return;
          const m = p.redoStack[p.redoStack.length - 1];
          dispatchApply(p.schema, m);
          p.redoStack.pop();
          p.history.push(m);
          p.schemaVersion++;
          // Skipped on the hot path — see makePageState comment.
          p.saveState =
            JSON.stringify(p.schema) === JSON.stringify(p.lastSavedSchema) ? "clean" : "dirty";
          const llmSuggestions = p.suggestions.filter((s) => s.source === "llm");
          p.suggestions = [...runRules(p.schema, {}), ...llmSuggestions];
        });
      },

      selectNode(id) {
        withCurrent((p) => {
          p.selection = [id];
        });
      },
      toggleSelection(id) {
        withCurrent((p) => {
          const i = p.selection.indexOf(id);
          if (i === -1) p.selection.push(id);
          else p.selection.splice(i, 1);
        });
      },
      clearSelection() {
        withCurrent((p) => {
          p.selection = [];
        });
      },
      setHover(id) {
        withCurrent((p) => {
          p.hoverNodeId = id;
        });
      },
      setDrag(patch) {
        set((s) => ({ drag: { ...s.drag, ...patch } }));
      },
      setSaveState(state, error = null) {
        withCurrent((p) => {
          p.saveState = state;
          p.saveError = error ?? null;
        });
      },
      markSaved(savedSchema) {
        withCurrent((p) => {
          p.lastSavedSchema = savedSchema;
          p.saveState = "saved";
          p.saveError = null;
          p.lastSavedAt = Date.now();
        });
      },

      copyToClipboard() {
        set((state) =>
          produce(state, (d) => {
            if (!d.currentPath) return;
            const page = d.pages[d.currentPath];
            if (!page) return;
            const ids = page.selection;
            if (ids.length === 0) return;
            const nodes = ids
              .map((id: NodeId) => findNodeDeep(page.schema.root, id))
              .filter(Boolean);
            d.clipboard = {
              mode: "copy",
              nodes: JSON.parse(JSON.stringify(nodes)),
              sourcePath: d.currentPath,
              copiedAt: Date.now(),
            } as ClipboardState;
          })
        );
      },

      cutToClipboard() {
        // Copy first
        _get().copyToClipboard();
        // Then bulk-remove selection via composite
        const path = _get().currentPath;
        if (!path) return;
        const page = _get().pages[path];
        if (!page) return;
        const ids = page.selection;
        if (ids.length === 0) return;
        const composite = buildBulkRemove(ids, page.schema);
        _get().apply(composite);
        set((state) =>
          produce(state, (d) => {
            if (d.clipboard) d.clipboard.mode = "cut";
          })
        );
      },

      pasteFromClipboard() {
        const cb = _get().clipboard;
        if (!cb) return;
        const path = _get().currentPath;
        if (!path) return;
        const page = _get().pages[path];
        if (!page) return;
        const root = page.schema.root;
        const firstSelected = page.selection[0];
        const targetParentId = firstSelected
          ? (findParentId(root, firstSelected) ?? root.id)
          : root.id;
        const insertIndex = firstSelected
          ? findIndexInParent(root, firstSelected) + 1
          : (findNodeDeep(root, targetParentId)?.children?.length ?? 0);
        const cloned = cb.nodes.map(cloneNodeWithFreshIds);
        const composite: Mutation = {
          kind: "composite",
          mutations: cloned.map((node: any, i: number) => ({
            kind: "insert-node" as const,
            parentId: targetParentId,
            index: insertIndex + i,
            node,
          })),
        };
        _get().apply(composite);
        // Select newly pasted nodes
        set((state) =>
          produce(state, (d) => {
            const p = d.pages[d.currentPath!];
            if (p) p.selection = cloned.map((n: any) => n.id);
          })
        );
      },

      deleteSelection() {
        const path = _get().currentPath;
        if (!path) return;
        const page = _get().pages[path];
        if (!page) return;
        const sel = page.selection;
        if (sel.length === 0) return;
        // Don't delete root
        const rootId = page.schema.root.id;
        const ids = sel.filter((id) => id !== rootId);
        if (ids.length === 0) return;
        const m = buildBulkRemove(ids, page.schema);
        _get().apply(m);
        // Clear selection after delete
        set((state) =>
          produce(state, (d) => {
            if (d.currentPath && d.pages[d.currentPath]) {
              d.pages[d.currentPath].selection = [];
            }
          })
        );
      },

      loadTheme(tokens, source) {
        set((state) =>
          produce(state, (d) => {
            d.theme = tokens as any;
            d.themeSource = source;
            d.themeDirty = false;
          })
        );
      },

      setTokenValue(group, name, value) {
        set((state) =>
          produce(state, (d) => {
            if (!d.theme) return;
            // Wave 2: when name is empty string, set the group key as a
            // top-level scalar (e.g. density = "comfortable").
            if (name === "") {
              (d.theme as any)[group] = value;
            } else {
              if (!d.theme[group]) d.theme[group] = {} as any;
              (d.theme[group] as Record<string, string>)[name] = value;
            }
            d.themeDirty = true;
          })
        );
      },

      markThemeSaved() {
        set((state) =>
          produce(state, (d) => {
            d.themeDirty = false;
          })
        );
      },

      dismissSuggestion(id) {
        set((state) =>
          produce(state, (d) => {
            if (!d.currentPath) return;
            const p = d.pages[d.currentPath];
            if (!p) return;
            if (!p.dismissedIds.includes(id)) p.dismissedIds.push(id);
          })
        );
      },

      appendLlmSuggestions(path, suggestions) {
        set((state) =>
          produce(state, (d) => {
            const p = d.pages[path];
            if (!p) return;
            const existing = new Set(p.suggestions.map((s: Suggestion) => s.id));
            for (const s of suggestions) {
              if (!existing.has(s.id)) p.suggestions.push(s as any);
            }
          })
        );
      },

      applySuggestion(id) {
        const path = _get().currentPath;
        if (!path) return;
        const page = _get().pages[path];
        if (!page) return;
        const s = page.suggestions.find((x) => x.id === id);
        if (!s?.fix) return;
        _get().apply(s.fix);
        _get().dismissSuggestion(id);
      },

      setViewport(v) {
        set((state) => produce(state, (d) => { d.viewport = v; }));
      },
    };
  });
}

export type { Selection, Mutation, NodeId, SchemaPath, PageState } from "./types";
