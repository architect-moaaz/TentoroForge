// packages/patches/src/index.ts
export type {
  NodeId, PageId,
  SchemaNode, PageSchema, Tokens, Artifacts,
  PropPath, PropValue,
  EditorAction, ApplyResult,
} from "./types";

export { applyAction } from "./apply";
export { normalize } from "./normalize";
export { validateAll, validateForCommit, validateIdUniqueness,
         validateRegistryTypes, validateRegistryClosure,
         validateTokenClosure, validateNavConsistency } from "./validate";
export type { RegistryLike } from "./validate";

export { syntheticNodeId } from "./synthetic-id";

export const PATCHES_VERSION = "0.1.0";
