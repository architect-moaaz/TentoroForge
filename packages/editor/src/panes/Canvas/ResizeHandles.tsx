import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import { selectCurrentPage, selectTheme } from "../../state/selectors";
import { useResizeDrag, type ResizeHandle } from "./useResizeDrag";
import { snapToSpacingToken } from "./snapToToken";
import { buildSetStyle } from "../../state/mutations";

const HANDLES: ResizeHandle[] = ["n", "s", "e", "w", "ne", "nw", "se", "sw"];

// Absolute-positioned style for each handle relative to the outline wrapper
const HANDLE_POS: Record<ResizeHandle, React.CSSProperties> = {
  n:  { top: -4,    left: "50%", transform: "translate(-50%, 0)",  cursor: "ns-resize"   },
  s:  { bottom: -4, left: "50%", transform: "translate(-50%, 0)",  cursor: "ns-resize"   },
  e:  { top: "50%", right: -4,   transform: "translate(0, -50%)",  cursor: "ew-resize"   },
  w:  { top: "50%", left: -4,    transform: "translate(0, -50%)",  cursor: "ew-resize"   },
  ne: { top: -4,    right: -4,                                      cursor: "nesw-resize" },
  nw: { top: -4,    left: -4,                                       cursor: "nwse-resize" },
  se: { bottom: -4, right: -4,                                      cursor: "nwse-resize" },
  sw: { bottom: -4, left: -4,                                       cursor: "nesw-resize" },
};

export interface ResizeHandlesProps {
  store: EditorStoreApi;
  rect: { width: number; height: number };
}

export function ResizeHandles({ store, rect }: ResizeHandlesProps) {
  const selection = useStore(store, (s) => selectCurrentPage(s)?.selection ?? []);
  const theme = useStore(store, selectTheme);

  // Handles only shown for single-node selection
  if (selection.length !== 1) return null;
  const id = selection[0];

  const { startDrag } = useResizeDrag({
    onDelta: () => {
      // Live preview via inline style could be added in Phase 2F
    },
    onCommit: (dx, dy, handle) => {
      const changesWidth  = handle.includes("e") || handle.includes("w");
      const changesHeight = handle.includes("s") || handle.includes("n");

      // Compute new pixel dimensions
      const newWidth  = changesWidth
        ? rect.width  + (handle.includes("e") ? dx : -dx)
        : rect.width;
      const newHeight = changesHeight
        ? rect.height + (handle.includes("s") ? dy : -dy)
        : rect.height;

      // Snap to nearest spacing token (if no theme, fall back to raw pixel string)
      const widthToken  = theme ? snapToSpacingToken(newWidth,  theme) : null;
      const heightToken = theme ? snapToSpacingToken(newHeight, theme) : null;

      const page = selectCurrentPage(store.getState());
      if (!page) return;

      const mutations = [];
      if (changesWidth) {
        const val = widthToken ?? `${Math.round(newWidth)}px`;
        mutations.push(buildSetStyle(id, "width" as any, val as any, page.schema));
      }
      if (changesHeight) {
        const val = heightToken ?? `${Math.round(newHeight)}px`;
        mutations.push(buildSetStyle(id, "height" as any, val as any, page.schema));
      }

      if (mutations.length === 1) {
        store.getState().apply(mutations[0]);
      } else if (mutations.length > 1) {
        store.getState().apply({ kind: "composite", mutations });
      }
    },
  });

  return (
    <>
      {HANDLES.map((h) => (
        <div
          key={h}
          data-resize-handle={h}
          onMouseDown={(e) => startDrag(h, e)}
          style={{
            position: "absolute",
            width: 8,
            height: 8,
            background: "#fff",
            border: "1px solid var(--editor-selection-color, #3b82f6)",
            borderRadius: 1,
            pointerEvents: "auto",
            zIndex: 1001,
            ...HANDLE_POS[h],
          }}
        />
      ))}
    </>
  );
}
