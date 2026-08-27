export const SCHEMA_VERSION = "1" as const;
export * from "./tokens";
export * from "./expressions";
export * from "./nodes/layout";
export * from "./nodes/primitive";
export * from "./nodes/library";
export * from "./nodes/data";
export * from "./nodes/slot";
export * as Nodes from "./nodes";
export * from "./page";
export * from "./layout-template";
export * from "./json-schema";
export * from "./cross-ref-validator";
export * from "./style-slot";
export * from "./nodes/custom";
export * from "./nodes/foundation";
export * from "./nodes/layout-v2";
export * from "./nodes/display";
export * from "./nodes/inputs";
export * from "./nodes/motion";
export { migratePage, type PageV2Migrated } from "./migrate";
export * from "./nodes/charts";
export * from "./nodes/data-display";
export * from "./nodes/enterprise";
export * from "./nodes/page-outlet";
export {
  NavFlow,
  NavFlowPageEntry,
  NavFlowTransition,
  NavFlowGuard,
} from "./nav-flow";
export type { NavFlowT } from "./nav-flow";

// --- Living Application Blueprint (PRD §9-25) -------------------------------
// Namespaced like `Nodes` above: the Blueprint's section schemas use generic
// names (Field, Entity, Test, Database, Runtime) that would crowd the package
// root and collide with future node types. `Blueprint` itself is lifted.
export * as BlueprintSchema from "./blueprint/index";
export {
  Blueprint,
  blueprintJsonSchema,
  BLUEPRINT_SCHEMA_VERSION,
} from "./blueprint/index";
