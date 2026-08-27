import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import { TreeNode } from "./TreeNode";
import { selectCurrentPage } from "../../state/selectors";

export function Tree({ store }: { store: EditorStoreApi }) {
  const schema = useStore(store, (s) => selectCurrentPage(s)?.schema);
  return (
    <div style={{ width: 240, borderRight: "1px solid #e5e7eb", overflowY: "auto" }}>
      <TreeNode node={(schema as any).root} depth={0} store={store} />
    </div>
  );
}
