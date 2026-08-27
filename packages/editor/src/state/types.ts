import type { Page, DataBinding, Expression, EventHandler, EventName, StyleProps, TokenRef } from "@tentoroforge/schema";
import type { TokenGroups } from "@tentoroforge/library";
import type { Suggestion } from "../suggestions/types";

export type { Suggestion };

export type NodeId = string;
export type SchemaPath = string;

export type ValidationError = {
  path: (string | number)[];
  message: string;
  code?: string;
};

export type Selection = NodeId[];

export type DragState = {
  sourceKind: "palette" | "canvas" | "tree" | null;
  sourcePayload: { kind: "palette"; libraryName: string } | { kind: "node"; id: NodeId } | null;
  overTargetId: NodeId | null;
  overPosition: "before" | "after" | "inside" | null;
};

export type SaveState = "clean" | "dirty" | "saving" | "saved" | "error";

export type Mutation =
  | { kind: "insert-node"; parentId: NodeId; index: number; node: any }
  | { kind: "remove-node"; id: NodeId; removed: { node: any; parentId: NodeId; index: number } }
  | { kind: "move-node"; id: NodeId; fromParentId: NodeId; fromIndex: number; toParentId: NodeId; toIndex: number }
  | { kind: "set-prop"; id: NodeId; key: string; value: unknown; prevValue: unknown }
  | { kind: "set-style"; id: NodeId; key: keyof StyleProps; value: TokenRef | undefined; prevValue: TokenRef | undefined }
  | { kind: "set-bind"; id: NodeId; bind: DataBinding | undefined; prevBind: DataBinding | undefined }
  | { kind: "set-visible-if"; id: NodeId; expr: Expression | undefined; prevExpr: Expression | undefined }
  | { kind: "set-event"; id: NodeId; eventName: EventName; handler: EventHandler | undefined; prevHandler: EventHandler | undefined }
  | { kind: "rename-node-id"; oldId: NodeId; newId: NodeId }
  | { kind: "composite"; mutations: Mutation[] };

export type PageState = {
  schemaPath: SchemaPath;
  schema: Page;
  schemaVersion: number;
  selection: Selection;
  hoverNodeId: NodeId | null;
  history: Mutation[];
  redoStack: Mutation[];
  saveState: SaveState;
  saveError: string | null;
  lastSavedAt: number | null;
  lastSavedSchema: Page;
  validationErrors: ValidationError[];
  openedAt: number;
  suggestions: Suggestion[];
  dismissedIds: string[];
};

export type ClipboardState = {
  mode: "copy" | "cut";
  nodes: any[];
  sourcePath: SchemaPath | null;
  copiedAt: number;
};

export type Viewport = "mobile" | "tablet" | "desktop";

export type EditorState = {
  pages: Record<SchemaPath, PageState>;
  currentPath: SchemaPath | null;
  drag: DragState;
  clipboard: ClipboardState | null;
  readonly historyLimit: number;
  theme: TokenGroups | null;
  themeSource: "default" | "custom" | null;
  themeDirty: boolean;
  viewport: Viewport;
};
