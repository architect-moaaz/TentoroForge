import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import { selectCurrentPage } from "../../state/selectors";

export function TreeNode({ node, depth, store }: { node: any; depth: number; store: EditorStoreApi }) {
  const isSelected = useStore(store, (s) => selectCurrentPage(s)?.selection.includes(node.id) ?? false);
  return (
    <div>
      <div
        onClick={(e) => {
          e.stopPropagation();
          if (e.shiftKey || e.metaKey || e.ctrlKey) {
            store.getState().toggleSelection(node.id);
          } else {
            store.getState().selectNode(node.id);
          }
        }}
        onMouseEnter={() => store.getState().setHover(node.id)}
        onMouseLeave={() => store.getState().setHover(null)}
        style={{
          paddingLeft: depth * 12 + 8,
          paddingTop: 4,
          paddingBottom: 4,
          background: isSelected ? "#dbeafe" : "transparent",
          cursor: "pointer",
          fontSize: 13,
        }}
      >
        {node.type}
      </div>
      {(node.children ?? []).map((c: any) => (
        <TreeNode key={c.id} node={c} depth={depth + 1} store={store} />
      ))}
    </div>
  );
}
