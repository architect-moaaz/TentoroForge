import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import { useNodeRect } from "./useNodeRect";
import { selectCurrentPage } from "../../state/selectors";
import { ResizeHandles } from "./ResizeHandles";

export function SelectionOverlay({ store }: { store: EditorStoreApi }) {
  const selectedId = useStore(store, (s) => selectCurrentPage(s)?.selection[0] ?? null);
  const rect = useNodeRect(selectedId);
  if (!selectedId || !rect) return null;
  return (
    <div
      role="presentation"
      style={{
        position: "fixed",
        top: rect.top, left: rect.left, width: rect.width, height: rect.height,
        outline: "2px solid var(--editor-selection-color, #3b82f6)",
        outlineOffset: -2,
        // Outline itself does not capture pointer events; handles do
        pointerEvents: "none",
        zIndex: 1000,
      }}
    >
      <ResizeHandles store={store} rect={{ width: rect.width, height: rect.height }} />
    </div>
  );
}
