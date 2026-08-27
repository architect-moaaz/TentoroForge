import { useStore } from "zustand";
import type { ReactNode } from "react";
import type { EditorStoreApi } from "../../state/store";
import type { Registry } from "@tentoroforge/library";
import { renderNode, type DispatchContext } from "@tentoroforge/renderer";
import { CanvasInstrumentation } from "./CanvasInstrumentation";
import { SelectionOverlay } from "./SelectionOverlay";
import { HoverOverlay } from "./HoverOverlay";
import { useDroppable } from "../../dnd/useDroppable";
import { selectCurrentPage, selectViewport } from "../../state/selectors";
import { CustomNodePreview } from "./CustomNodePreview";

const VIEWPORT_WIDTHS = { mobile: 375, tablet: 768, desktop: undefined } as const;

/**
 * Edit-mode custom renderer for Custom nodes (Task 33).
 * Passed as ctx.customRenderer so the renderer delegates Custom-node dispatch
 * here rather than rendering dangerouslySetInnerHTML directly. This gives the
 * editor the floating edit chip and pointer-events guard from CustomNodePreview
 * without forking the renderer's dispatch switch.
 */
function renderCustomNode(node: any, _ctx: DispatchContext): ReactNode {
  return <CustomNodePreview node={node} />;
}

export function Canvas({ store, registry }: { store: EditorStoreApi; registry: Registry }) {
  const schema = useStore(store, (s) => selectCurrentPage(s)?.schema);
  const viewport = useStore(store, selectViewport);
  const rootId = (schema as any).root.id;
  const { setNodeRef, isOver } = useDroppable({ id: rootId });
  // Pass customRenderer so Custom nodes are displayed via CustomNodePreview
  // (with edit chip + pointer-events guard) in edit mode.
  const ctx: DispatchContext = { data: {}, registry, customRenderer: renderCustomNode };
  const maxWidth = VIEWPORT_WIDTHS[viewport];

  return (
    <div
      ref={setNodeRef}
      style={{
        position: "relative",
        flex: 1,
        overflow: "auto",
        outline: isOver ? "2px solid var(--editor-drop-valid, #22c55e)" : "none",
      }}
    >
      <div
        data-viewport={viewport}
        style={{
          maxWidth: maxWidth ? `${maxWidth}px` : "100%",
          margin: "0 auto",
          width: "100%",
        }}
      >
        <CanvasInstrumentation store={store}>
          {renderNode((schema as any).root, ctx)}
        </CanvasInstrumentation>
      </div>
      <SelectionOverlay store={store} />
      <HoverOverlay store={store} />
    </div>
  );
}
