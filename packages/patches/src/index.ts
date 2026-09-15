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
         validateTokenClosure, validateNavConsistency,
         validateNoLegacyBindings } from "./validate";
export type { RegistryLike } from "./validate";

export { syntheticNodeId } from "./synthetic-id";

// The single owner of the "{{expr}}" binding format — shared by the reducer, the
// commit guard and the load-time migration so the three cannot drift apart.
export { isBinding, isLegacyBinding, isMustacheBinding,
         bindingExpression, toBindingValue, migrateBindingsDeep } from "./binding";
export type { LegacyBindingObject } from "./binding";

export const PATCHES_VERSION = "0.1.0";
