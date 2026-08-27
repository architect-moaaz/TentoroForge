import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import { useNodeRect } from "./useNodeRect";
import { selectCurrentPage } from "../../state/selectors";

export function HoverOverlay({ store }: { store: EditorStoreApi }) {
  const hoverId = useStore(store, (s) => selectCurrentPage(s)?.hoverNodeId ?? null);
  const selectedId = useStore(store, (s) => selectCurrentPage(s)?.selection[0] ?? null);
  const rect = useNodeRect(hoverId === selectedId ? null : hoverId);
  if (!rect) return null;
  return (
    <div
      role="presentation"
      style={{
        position: "fixed",
        top: rect.top, left: rect.left, width: rect.width, height: rect.height,
        outline: "1px dashed var(--editor-hover-color, #93c5fd)",
        outlineOffset: -1,
        pointerEvents: "none",
        zIndex: 999,
      }}
    />
  );
}
