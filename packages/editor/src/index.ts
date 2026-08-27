export const EDITOR_VERSION = "0.2.0" as const;
export type * from "./state/types";
export { Editor } from "./Editor";
export type { EditorProps } from "./Editor";
export { createEditorStore } from "./state/store";
export type { EditorStore, EditorStoreApi } from "./state/store";
export {
  selectCurrentPage,
  selectPageState,
  selectOpenPaths,
  selectAnyDirty,
} from "./state/selectors";
