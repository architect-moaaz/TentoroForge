"use client";
import { useEditorStore } from "@/lib/editor-store";

/**
 * Returns a click handler to mount on the canvas wrapper. On any click,
 * walks up from the target to the nearest [data-node-id] and selects it.
 * Modifier key behaviour:
 *   - plain click      → setSelection (replace, single)
 *   - shift+click      → extendSelection (append without dup)
 *   - cmd/ctrl+click   → toggleSelection (add or remove)
 *   - click empty area → clearSelection
 *
 * Stops propagation so the underlying rendered component's own onClick
 * (e.g. real button submitForm) doesn't fire while the user is editing.
 */
export function useCanvasClick() {
  return (e: React.MouseEvent) => {
    const target = (e.target as HTMLElement).closest("[data-node-id]") as HTMLElement | null;
    const id = target?.getAttribute("data-node-id") ?? null;
    const s = useEditorStore.getState();
    if (!id) {
      s.clearSelection();
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    if (e.shiftKey) {
      s.extendSelection(id);
    } else if (e.metaKey || e.ctrlKey) {
      s.toggleSelection(id);
    } else {
      s.setSelection(id);
    }
  };
}
