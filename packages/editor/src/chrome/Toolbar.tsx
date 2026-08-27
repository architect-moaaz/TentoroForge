import { useStore } from "zustand";
import type { EditorStoreApi } from "../state/store";
import { selectCurrentPage } from "../state/selectors";
import { ViewportToggle } from "../panes/Canvas/ViewportToggle";

export type ToolbarProps = {
  store: EditorStoreApi;
  onSave: () => void;
  onRegenerate?: () => void;
};

/**
 * Editor toolbar — matches the visual language of IREditor / UnifiedEditor:
 *   compact 32px-tall bar, h-7 ghost buttons, inline separators, semantic
 *   save-state pill on the right.
 *
 * Uses Tailwind class names which the consuming app's globals.css opts in
 * to scan via `@source` at the top of that file.
 */
export function Toolbar({ store, onSave, onRegenerate }: ToolbarProps) {
  const canUndo = useStore(store, (s) => (selectCurrentPage(s)?.history.length ?? 0) > 0);
  const canRedo = useStore(store, (s) => (selectCurrentPage(s)?.redoStack.length ?? 0) > 0);
  const saveState = useStore(store, (s) => selectCurrentPage(s)?.saveState ?? "clean");
  const selectionCount = useStore(store, (s) => selectCurrentPage(s)?.selection.length ?? 0);

  const saveDisabled = saveState === "saving" || saveState === "clean";
  const saveLabel =
    saveState === "saving"
      ? "Saving…"
      : saveState === "saved"
        ? "Saved"
        : saveState === "dirty"
          ? "Save"
          : "Saved";

  return (
    <div className="flex items-center justify-between border-b bg-background px-3 py-1.5 shrink-0">
      <div className="flex items-center gap-2">
        <ViewportToggle store={store} />

        <div className="w-px h-5 bg-border" />

        <button
          type="button"
          onClick={() => store.getState().undo()}
          disabled={!canUndo}
          aria-label="Undo (Cmd+Z)"
          title="Undo (Cmd+Z)"
          className="h-7 w-7 inline-flex items-center justify-center rounded-md text-sm text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent"
        >
          ↶
        </button>
        <button
          type="button"
          onClick={() => store.getState().redo()}
          disabled={!canRedo}
          aria-label="Redo (Cmd+Shift+Z)"
          title="Redo (Cmd+Shift+Z)"
          className="h-7 w-7 inline-flex items-center justify-center rounded-md text-sm text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent"
        >
          ↷
        </button>

        {selectionCount > 1 && (
          <span className="ml-2 text-xs text-muted-foreground">
            {selectionCount} selected
          </span>
        )}
      </div>

      <div className="flex items-center gap-2">
        {selectionCount === 1 && onRegenerate && (
          <button
            type="button"
            onClick={onRegenerate}
            aria-label="Regenerate selected section"
            className="h-7 inline-flex items-center gap-1.5 rounded-md bg-violet-600 px-2.5 text-xs font-medium text-white hover:bg-violet-700"
          >
            ✨ Regenerate
          </button>
        )}

        <span
          className={
            "text-xs " +
            (saveState === "dirty"
              ? "text-amber-600"
              : saveState === "saved"
                ? "text-emerald-600"
                : saveState === "error"
                  ? "text-red-600"
                  : "text-muted-foreground")
          }
        >
          {saveState === "dirty"
            ? "● Unsaved"
            : saveState === "saved"
              ? "✓ Saved"
              : saveState === "error"
                ? "⚠ Error"
                : ""}
        </span>

        <button
          type="button"
          onClick={onSave}
          disabled={saveDisabled}
          className="h-7 inline-flex items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {saveLabel}
        </button>
      </div>
    </div>
  );
}
