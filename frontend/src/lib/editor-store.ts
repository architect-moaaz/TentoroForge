"use client";
/**
 * Editor store — the single source of truth for the in-progress artifacts,
 * the undo/redo stacks, and the current selection. Every modification of
 * the artifacts flows through dispatch(), which calls applyAction() from
 * @forge/patches and pushes the typed inverse onto the undo stack.
 *
 * A debounced subscriber (attachPersister) writes changes back to the
 * backend. Selection is editor-only state — never persisted.
 */
import { create } from "zustand";
import { applyAction, validateForCommit, type Artifacts, type EditorAction } from "@forge/patches";
import { starterRegistry } from "@forge/registry";
import { buildPersister, type Persister } from "./persistence";

/** A history entry is either a single inverse or — for a batched operation
 * (multi-delete, corner-resize) — an ordered list of inverses applied together
 * so one undo reverts the whole gesture. */
type HistoryEntry = EditorAction | EditorAction[];

interface State {
  artifacts: Artifacts | null;
  undoStack: HistoryEntry[];    // typed inverses (single or batched)
  redoStack: HistoryEntry[];
  /** Primary single-selection id — kept for backwards compat with existing consumers. */
  selectedNodeId: string | null;
  /** Full multi-selection set. selectedNodeId === selectedNodeIds[0] ?? null */
  selectedNodeIds: string[];
  currentPageId: string | null;
  /**
   * The open project's SHORT id (`output/<short_id>/` on disk) — the same value
   * `attachPersister` is given.
   *
   * Held in the store rather than threaded as a prop because the properties
   * panel is mounted from three places (PropertiesPanel, RightPanel,
   * PropsTokensSidebar) and none of them is handed a project id today; the
   * image control needs one to know where to upload. Not derivable from the
   * route: `/editor/[projectId]` carries the short id but
   * `/org/[orgId]/projects/[projectId]` carries the DB UUID and passes
   * `project.short_id` down instead.
   */
  projectId: string | null;
  lastError: string | null;
  /** Persistent save-failure message (distinct from the transient, auto-clearing
   * `lastError` used for rejected edits). Stays until the next successful save. */
  saveError: string | null;
  /** True after any dispatch, reset to false after successful persistence. */
  isDirty: boolean;

  setInitial: (a: Artifacts) => void;
  markClean: () => void;
  setSaveError: (e: string | null) => void;
  /** Backwards-compat single selection — replaces the full selection with [id]. */
  setSelection: (id: string | null) => void;
  /** Replace the entire selection set. */
  setSelectionMulti: (ids: string[]) => void;
  /** Toggle a single id in/out of the selection set. */
  toggleSelection: (id: string) => void;
  /** Append id if not already present; no-op if it is. */
  extendSelection: (id: string) => void;
  /** Clear the selection. */
  clearSelection: () => void;
  setCurrentPage: (pageId: string | null) => void;
  setProjectId: (id: string | null) => void;
  dispatch: (action: EditorAction) => void;
  /** Apply several actions as ONE undoable transaction. All-or-nothing: if any
   * action throws or the result fails validation, nothing is committed. */
  dispatchBatch: (actions: EditorAction[]) => void;
  undo: () => void;
  redo: () => void;
  clearError: () => void;
}

/**
 * Apply a list of actions in order, collecting each action's inverse. The
 * returned `inverses` are in REVERSE order (last-applied first) so replaying
 * them left-to-right cleanly undoes the whole batch. Throws (uncaught here) if
 * any action is structurally invalid — callers wrap in try/catch.
 */
function applyActions(
  artifacts: Artifacts,
  actions: EditorAction[],
): { next: Artifacts; inverses: EditorAction[] } {
  let working = artifacts;
  const inverses: EditorAction[] = [];
  for (const act of actions) {
    const r = applyAction(working, act);
    working = r.next;
    inverses.unshift(r.inverse);
  }
  return { next: working, inverses };
}

export const useEditorStore = create<State>((set, get) => ({
  artifacts: null,
  undoStack: [],
  redoStack: [],
  selectedNodeId: null,
  selectedNodeIds: [],
  currentPageId: null,
  projectId: null,
  lastError: null,
  saveError: null,
  isDirty: false,

  setInitial: (a) => set({
    artifacts: a, undoStack: [], redoStack: [],
    selectedNodeId: null,
    selectedNodeIds: [],
    currentPageId: get().currentPageId ?? Object.keys(a.pageSchemas)[0] ?? null,
    isDirty: false,
  }),

  // A successful save clears any prior save error. markClean is called by the
  // persister only after runSave resolves (see persistence.ts).
  markClean: () => set({ isDirty: false, saveError: null }),
  setSaveError: (e) => set({ saveError: e }),

  setSelection: (id) => set({ selectedNodeId: id, selectedNodeIds: id ? [id] : [] }),

  setSelectionMulti: (ids) => set({
    selectedNodeId: ids[0] ?? null,
    selectedNodeIds: ids,
  }),

  toggleSelection: (id) => set((s) => {
    const exists = s.selectedNodeIds.includes(id);
    const next = exists
      ? s.selectedNodeIds.filter(x => x !== id)
      : [...s.selectedNodeIds, id];
    return { selectedNodeIds: next, selectedNodeId: next[0] ?? null };
  }),

  extendSelection: (id) => set((s) => {
    if (s.selectedNodeIds.includes(id)) return s;
    const next = [...s.selectedNodeIds, id];
    return { selectedNodeIds: next, selectedNodeId: s.selectedNodeId ?? next[0] };
  }),

  clearSelection: () => set({ selectedNodeIds: [], selectedNodeId: null }),

  setCurrentPage: (id) => set({ currentPageId: id, selectedNodeId: null, selectedNodeIds: [] }),
  setProjectId: (id) => set({ projectId: id }),
  clearError: () => set({ lastError: null }),

  dispatch: (action) => {
    const cur = get().artifacts;
    if (!cur) return;

    // applyAction throws on structurally-impossible actions (unknown page /
    // node id, removing/moving the root). Those must surface as a recoverable
    // lastError — never an uncaught exception that crashes the editor. e.g.
    // pressing Delete while the page root is selected, or acting on a node
    // that was removed by a concurrent edit.
    let next: ReturnType<typeof applyAction>["next"];
    let inverse: ReturnType<typeof applyAction>["inverse"];
    try {
      ({ next, inverse } = applyAction(cur, action));
    } catch (err) {
      set({ lastError: err instanceof Error ? err.message : String(err) });
      return;
    }

    // Validate before committing — reject the action on errors that
    // would actually break rendering (duplicate ids, unknown component
    // types). Unknown PROPS pass with a console warning since the
    // simplified @forge/registry doesn't list every prop the library
    // components accept — the runtime + library Zod schemas handle
    // unknown props gracefully.
    const errs = validateForCommit(next, starterRegistry as any);
    if (errs.length > 0) {
      set({ lastError: errs.slice(0, 3).join("\n") });
      return;
    }

    set((s) => ({
      artifacts: next,
      undoStack: [...s.undoStack, inverse],
      redoStack: [],
      lastError: null,
      isDirty: true,
    }));
  },

  dispatchBatch: (actions) => {
    const cur = get().artifacts;
    if (!cur || actions.length === 0) return;
    let next: Artifacts;
    let inverses: EditorAction[];
    try {
      ({ next, inverses } = applyActions(cur, actions));
    } catch (err) {
      set({ lastError: err instanceof Error ? err.message : String(err) });
      return; // all-or-nothing: nothing committed
    }
    const errs = validateForCommit(next, starterRegistry as any);
    if (errs.length > 0) {
      set({ lastError: errs.slice(0, 3).join("\n") });
      return;
    }
    // Push the batch as ONE history entry (the array of inverses) so a single
    // undo reverts the whole gesture. A length-1 batch stays a single entry.
    const entry: HistoryEntry = inverses.length === 1 ? inverses[0] : inverses;
    set((s) => ({
      artifacts: next,
      undoStack: [...s.undoStack, entry],
      redoStack: [],
      lastError: null,
      isDirty: true,
    }));
  },

  undo: () => {
    const { artifacts, undoStack } = get();
    if (!artifacts || undoStack.length === 0) return;
    const entry = undoStack[undoStack.length - 1];
    const invActions = Array.isArray(entry) ? entry : [entry];
    // Same crash-safety as dispatch: a bad inverse (stale/dangling target) must
    // surface as a recoverable error and drop the offending entry, not throw
    // uncaught inside the setter (white screen). Undo is where robustness matters.
    let next: Artifacts;
    let inverses: EditorAction[];
    try {
      ({ next, inverses } = applyActions(artifacts, invActions));
    } catch (err) {
      set((s) => ({ undoStack: s.undoStack.slice(0, -1), lastError: err instanceof Error ? err.message : String(err) }));
      return;
    }
    // isDirty:true so an undo AFTER an autosave is itself persisted (otherwise
    // in-memory + disk diverge while the indicator falsely shows "Saved").
    const redoEntry: HistoryEntry = inverses.length === 1 ? inverses[0] : inverses;
    set((s) => ({
      artifacts: next,
      undoStack: s.undoStack.slice(0, -1),
      redoStack: [...s.redoStack, redoEntry],
      isDirty: true,
    }));
  },

  redo: () => {
    const { artifacts, redoStack } = get();
    if (!artifacts || redoStack.length === 0) return;
    const entry = redoStack[redoStack.length - 1];
    const actions = Array.isArray(entry) ? entry : [entry];
    let next: Artifacts;
    let inverses: EditorAction[];
    try {
      ({ next, inverses } = applyActions(artifacts, actions));
    } catch (err) {
      set((s) => ({ redoStack: s.redoStack.slice(0, -1), lastError: err instanceof Error ? err.message : String(err) }));
      return;
    }
    const undoEntry: HistoryEntry = inverses.length === 1 ? inverses[0] : inverses;
    set((s) => ({
      artifacts: next,
      redoStack: s.redoStack.slice(0, -1),
      undoStack: [...s.undoStack, undoEntry],
      isDirty: true,
    }));
  },
}));

let unsubscribePersister: (() => void) | null = null;
let activePersister: Persister | null = null;

/**
 * Attach a debounced auto-save subscriber. Call once per project session.
 * Returns the unsubscribe function (also stored internally so re-calling
 * detaches the previous binding).
 */
export function attachPersister(projectId: string): () => void {
  if (unsubscribePersister) unsubscribePersister();
  const persist = buildPersister(projectId);
  activePersister = persist;
  let lastSavedRef: Artifacts | null = null;
  const unsub = useEditorStore.subscribe((state) => {
    // Only persist on actual edits (isDirty). Without the isDirty guard the
    // persister's own markClean() at the end of a save re-triggers this
    // subscriber → an infinite save loop. AND only when the artifacts REFERENCE
    // actually changed — otherwise unrelated dirty-state store updates
    // (selection on every canvas click, error auto-clear, page switch) re-arm
    // the 500ms debounce and can starve the autosave indefinitely.
    if (state.artifacts && state.isDirty && state.artifacts !== lastSavedRef) {
      lastSavedRef = state.artifacts;
      persist.save(state.artifacts);
    }
  });
  unsubscribePersister = () => {
    unsub();
    // Fix (Important 2): clear activePersister on detach so flushPersister()
    // doesn't flush an orphaned persister after the session ends.
    activePersister = null;
    unsubscribePersister = null;
  };
  return unsubscribePersister;
}

/**
 * Flush any pending or in-flight saves from the active persister.
 * Resolves immediately if no persister is attached.
 */
export async function flushPersister(): Promise<void> {
  if (activePersister) {
    await activePersister.flush();
  }
}
