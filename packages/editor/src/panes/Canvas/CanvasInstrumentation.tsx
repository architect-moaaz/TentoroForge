import type { ReactNode } from "react";
import type { EditorStoreApi } from "../../state/store";

export function CanvasInstrumentation({ store, children }: { store: EditorStoreApi; children: ReactNode }) {
  function handleClick(e: React.MouseEvent) {
    const target = (e.target as HTMLElement).closest("[data-node-id]");
    if (target) {
      const id = target.getAttribute("data-node-id")!;
      if (e.shiftKey || e.metaKey || e.ctrlKey) {
        store.getState().toggleSelection(id);
      } else {
        store.getState().selectNode(id);
      }
      e.stopPropagation();
    }
  }
  function handleMove(e: React.MouseEvent) {
    const target = (e.target as HTMLElement).closest("[data-node-id]");
    store.getState().setHover(target?.getAttribute("data-node-id") ?? null);
  }
  function handleLeave() {
    store.getState().setHover(null);
  }
  return (
    <div onClick={handleClick} onMouseMove={handleMove} onMouseLeave={handleLeave}>
      {children}
    </div>
  );
}
