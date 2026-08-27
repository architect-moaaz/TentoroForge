// packages/patches/src/types.ts
import type { NavFlowT } from "@tentoroforge/schema";

export type NodeId = string;
export type PageId = string;

/**
 * Mirrors the SchemaNode shape used across the codebase (renderer + library).
 * Structural type — patches doesn't validate the inner detail since the
 * renderer + Zod schemas already do that downstream.
 */
export interface SchemaNode {
  id: NodeId;
  type: string;
  props?: Record<string, unknown>;
  children?: SchemaNode[];
  slots?: Record<string, SchemaNode[]>;
  visibleIf?: string;
}

export interface DataSource {
  name: string;
  entity?: string;
  op?: string;
  source?: string;
  groupBy?: string;
  agg?: { fn: string; field?: string };
  metrics?: Record<string, unknown>;
  dateField?: string;
  [k: string]: unknown;
}

export interface PageSchema {
  schemaVersion: "2";
  id: PageId;
  route?: string;
  layout?: string;
  meta?: Record<string, unknown>;
  dataSources?: DataSource[];
  root: SchemaNode;
}

export interface Tokens {
  color: Record<string, Record<string, string>>;
  typography: { fontFamily?: Record<string, string>; scale?: Record<string, number> };
  spacing: Record<string, number>;
  radius: Record<string, number>;
  shadow: Record<string, string>;
  motion: Record<string, string>;
  breakpoints: Record<string, number>;
}

/**
 * The full artifact set. Per Tentoro Forge convention, page schemas live
 * as N separate files keyed by page id; we represent them here as an
 * in-memory map for editor convenience. Persistence writes one file per
 * page back to src/schemas/.
 */
export interface Artifacts {
  pageSchemas: Record<PageId, PageSchema>;
  navFlow: NavFlowT;
  tokens: Tokens;
}

// ---------------- EditorAction union ----------------

export type PropPath = string;          // e.g. "label" or "style.color"
export type PropValue = unknown;

export type EditorAction =
  | { type: "insertNode"; pageId: PageId; parentId: NodeId; index: number; node: SchemaNode; slotKey?: string }
  | { type: "removeNode"; pageId: PageId; nodeId: NodeId }
  | { type: "moveNode"; pageId: PageId; nodeId: NodeId; newParentId: NodeId; newIndex: number }
  | { type: "duplicateNode"; pageId: PageId; nodeId: NodeId }
  | { type: "updateProp"; pageId: PageId; nodeId: NodeId; propName: PropPath; value: PropValue }
  | { type: "updateStyle"; pageId: PageId; nodeId: NodeId; styleKey: string; value: PropValue }
  | { type: "bindProp"; pageId: PageId; nodeId: NodeId; propName: PropPath; binding: string }
  | { type: "unbindProp"; pageId: PageId; nodeId: NodeId; propName: PropPath; literalValue: PropValue }
  | { type: "addPage"; pageId: PageId; route: string; title: string; root: SchemaNode; shell?: boolean }
  | { type: "removePage"; pageId: PageId }
  | { type: "renamePage"; pageId: PageId; title: string }
  | { type: "updateRoute"; pageId: PageId; route: string }
  | { type: "addDataSource"; pageId: PageId; source: DataSource }
  | { type: "removeDataSource"; pageId: PageId; name: string }
  | { type: "setInitialPage"; pageId: PageId }
  | { type: "addTransition"; transition: NavFlowT["transitions"][number] }
  | { type: "removeTransition"; transitionId: string }
  | { type: "setGuard"; pageId: PageId; guard: string | null }
  | { type: "updateToken"; path: string[]; value: unknown }
  | { type: "addToken"; path: string[]; value: unknown }
  | { type: "removeToken"; path: string[] }
  | { type: "renameToken"; oldPath: string[]; newPath: string[] }
  | { type: "replaceArtifacts"; artifacts: Artifacts; rationale?: string };

export interface ApplyResult {
  next: Artifacts;
  inverse: EditorAction;
}
