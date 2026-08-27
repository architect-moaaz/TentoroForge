/**
 * IR Editor Store — manages the IR document state for visual editing.
 *
 * Handles: selection, undo/redo, IR mutations, and sync with backend.
 */

import { create } from "zustand";

// ---------------------------------------------------------------------------
// Types (mirrors @tentoroforge/ir types for the frontend)
// ---------------------------------------------------------------------------

export type NodePath = number[];

export interface IRNode {
  node: string;
  children?: IRNode[];
  [key: string]: unknown;
}

export interface PageIR {
  $id: string;
  route: string;
  title?: string;
  state?: Record<string, unknown>;
  root: IRNode;
  modals?: Record<string, unknown>;
}

export interface AppIR {
  $schema: string;
  app: { name: string };
  tokens: Record<string, unknown>;
  dataSources: Record<string, unknown>;
  pages: PageIR[];
  fragments?: Record<string, unknown>;
  navigation?: { items: Array<{ label: string; icon?: string; route?: string }> };
}

export interface IROperation {
  type: "setProp" | "addChild" | "removeChild" | "moveChild" | "wrapWith" | "unwrap" | "duplicate" | "replace";
  path: NodePath;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Node navigation helpers
// ---------------------------------------------------------------------------

export function getNodeAtPath(root: IRNode, path: NodePath): IRNode | null {
  let node = root;
  for (const index of path) {
    const children = node.children;
    if (!Array.isArray(children) || index >= children.length) return null;
    node = children[index];
  }
  return node;
}

export function getParentPath(path: NodePath): NodePath {
  return path.slice(0, -1);
}

export function getNodeLabel(node: IRNode): string {
  if (node.content && typeof node.content === "string") {
    const text = node.content as string;
    if (text.startsWith("{{")) return `${node.node}`;
    if (text.length > 25) return `${node.node}: ${text.slice(0, 22)}...`;
    return `${node.node}: ${text}`;
  }
  if (node.label && typeof node.label === "string") return `${node.node}: ${node.label}`;
  if (node.data && typeof node.data === "string") return `${node.node} → ${(node.data as string).replace("source:", "")}`;
  return node.node;
}

// ---------------------------------------------------------------------------
// IR Operations (apply + inverse for undo)
// ---------------------------------------------------------------------------

function applyOperation(root: IRNode, op: IROperation): { inverse: IROperation } | null {
  const cloned = structuredClone(root);

  switch (op.type) {
    case "setProp": {
      const node = getNodeAtPath(cloned, op.path);
      if (!node) return null;
      const prop = op.prop as string;
      const oldValue = node[prop];
      node[prop] = op.value;
      // Mutate root in-place (caller uses the clone)
      Object.assign(root, cloned);
      return { inverse: { type: "setProp", path: op.path, prop, value: oldValue } };
    }

    case "addChild": {
      const parent = getNodeAtPath(cloned, op.path);
      if (!parent || !Array.isArray(parent.children)) return null;
      const index = op.index as number;
      const newNode = op.node as IRNode;
      parent.children.splice(index, 0, structuredClone(newNode));
      Object.assign(root, cloned);
      return { inverse: { type: "removeChild", path: op.path, index } };
    }

    case "removeChild": {
      const parent = getNodeAtPath(cloned, op.path);
      if (!parent || !Array.isArray(parent.children)) return null;
      const index = op.index as number;
      const [removed] = parent.children.splice(index, 1);
      Object.assign(root, cloned);
      return { inverse: { type: "addChild", path: op.path, index, node: removed } };
    }

    case "moveChild": {
      const fromParent = getNodeAtPath(cloned, op.from as NodePath);
      const toParent = getNodeAtPath(cloned, op.to as NodePath);
      if (!fromParent?.children || !toParent?.children) return null;
      const fromIndex = op.fromIndex as number;
      const toIndex = op.toIndex as number;
      const [moved] = fromParent.children.splice(fromIndex, 1);
      toParent.children.splice(toIndex, 0, moved);
      Object.assign(root, cloned);
      return {
        inverse: {
          type: "moveChild",
          path: [],
          from: op.to as NodePath,
          fromIndex: toIndex,
          to: op.from as NodePath,
          toIndex: fromIndex,
        },
      };
    }

    case "wrapWith": {
      const parentPath = getParentPath(op.path);
      const parent = op.path.length === 0 ? null : getNodeAtPath(cloned, parentPath);
      if (!parent?.children) return null;
      const index = op.path[op.path.length - 1];
      const child = parent.children[index];
      const wrapper = structuredClone(op.wrapper as IRNode);
      wrapper.children = [child];
      parent.children[index] = wrapper;
      Object.assign(root, cloned);
      return { inverse: { type: "unwrap", path: op.path } };
    }

    case "unwrap": {
      const parentPath = getParentPath(op.path);
      const parent = op.path.length === 0 ? null : getNodeAtPath(cloned, parentPath);
      if (!parent?.children) return null;
      const index = op.path[op.path.length - 1];
      const wrapper = parent.children[index];
      if (!wrapper.children?.length) return null;
      const { children: wrapperChildren, ...wrapperProps } = wrapper;
      parent.children.splice(index, 1, ...wrapperChildren);
      Object.assign(root, cloned);
      return { inverse: { type: "wrapWith", path: op.path, wrapper: wrapperProps } };
    }

    case "duplicate": {
      const parentPath = getParentPath(op.path);
      const parent = op.path.length === 0 ? null : getNodeAtPath(cloned, parentPath);
      if (!parent?.children) return null;
      const index = op.path[op.path.length - 1];
      const original = parent.children[index];
      parent.children.splice(index + 1, 0, structuredClone(original));
      Object.assign(root, cloned);
      return { inverse: { type: "removeChild", path: parentPath, index: index + 1 } };
    }

    case "replace": {
      const parentPath = getParentPath(op.path);
      const parent = op.path.length === 0 ? null : getNodeAtPath(cloned, parentPath);
      if (!parent?.children) return null;
      const index = op.path[op.path.length - 1];
      const old = parent.children[index];
      parent.children[index] = structuredClone(op.node as IRNode);
      Object.assign(root, cloned);
      return { inverse: { type: "replace", path: op.path, node: old } };
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

interface IREditorState {
  // Document
  ir: AppIR | null;
  activePageId: string | null;
  projectId: string | null;

  // Selection
  selectedPath: NodePath | null;
  hoveredPath: NodePath | null;

  // Undo/redo
  undoStack: IROperation[][];
  redoStack: IROperation[][];

  // UI state
  leftPanelWidth: number;
  rightPanelWidth: number;
  devicePreview: "desktop" | "tablet" | "mobile";
  showCode: boolean;
  isDirty: boolean;

  // Actions
  loadIR: (ir: AppIR, projectId: string) => void;
  setActivePage: (pageId: string) => void;
  selectNode: (path: NodePath | null) => void;
  hoverNode: (path: NodePath | null) => void;

  // Mutations
  applyOps: (ops: IROperation[]) => void;
  undo: () => void;
  redo: () => void;

  // UI
  setDevicePreview: (device: "desktop" | "tablet" | "mobile") => void;
  setShowCode: (show: boolean) => void;
  setLeftPanelWidth: (w: number) => void;
  setRightPanelWidth: (w: number) => void;

  // Helpers
  getActivePage: () => PageIR | null;
  getSelectedNode: () => IRNode | null;
  canUndo: () => boolean;
  canRedo: () => boolean;

  reset: () => void;
}

const initialState = {
  ir: null as AppIR | null,
  activePageId: null as string | null,
  projectId: null as string | null,
  selectedPath: null as NodePath | null,
  hoveredPath: null as NodePath | null,
  undoStack: [] as IROperation[][],
  redoStack: [] as IROperation[][],
  leftPanelWidth: 260,
  rightPanelWidth: 300,
  devicePreview: "desktop" as const,
  showCode: false,
  isDirty: false,
};

export const useIREditorStore = create<IREditorState>((set, get) => ({
  ...initialState,

  loadIR: (ir, projectId) =>
    set({
      ir,
      projectId,
      activePageId: ir.pages[0]?.$id || null,
      selectedPath: null,
      undoStack: [],
      redoStack: [],
      isDirty: false,
    }),

  setActivePage: (pageId) =>
    set({ activePageId: pageId, selectedPath: null, hoveredPath: null }),

  selectNode: (path) => set({ selectedPath: path }),

  hoverNode: (path) => set({ hoveredPath: path }),

  applyOps: (ops) => {
    const state = get();
    if (!state.ir || !state.activePageId) return;

    const page = state.ir.pages.find((p) => p.$id === state.activePageId);
    if (!page) return;

    const inverses: IROperation[] = [];
    for (const op of ops) {
      const result = applyOperation(page.root, op);
      if (result) {
        inverses.unshift(result.inverse);
      }
    }

    set({
      ir: { ...state.ir },
      undoStack: [...state.undoStack, inverses],
      redoStack: [],
      isDirty: true,
    });
  },

  undo: () => {
    const state = get();
    const inverses = state.undoStack[state.undoStack.length - 1];
    if (!inverses || !state.ir || !state.activePageId) return;

    const page = state.ir.pages.find((p) => p.$id === state.activePageId);
    if (!page) return;

    const redoOps: IROperation[] = [];
    for (const op of inverses) {
      const result = applyOperation(page.root, op);
      if (result) redoOps.unshift(result.inverse);
    }

    set({
      ir: { ...state.ir },
      undoStack: state.undoStack.slice(0, -1),
      redoStack: [...state.redoStack, redoOps],
      isDirty: true,
    });
  },

  redo: () => {
    const state = get();
    const ops = state.redoStack[state.redoStack.length - 1];
    if (!ops || !state.ir || !state.activePageId) return;

    const page = state.ir.pages.find((p) => p.$id === state.activePageId);
    if (!page) return;

    const undoOps: IROperation[] = [];
    for (const op of ops) {
      const result = applyOperation(page.root, op);
      if (result) undoOps.unshift(result.inverse);
    }

    set({
      ir: { ...state.ir },
      redoStack: state.redoStack.slice(0, -1),
      undoStack: [...state.undoStack, undoOps],
      isDirty: true,
    });
  },

  setDevicePreview: (device) => set({ devicePreview: device }),
  setShowCode: (show) => set({ showCode: show }),
  setLeftPanelWidth: (w) => set({ leftPanelWidth: w }),
  setRightPanelWidth: (w) => set({ rightPanelWidth: w }),

  getActivePage: () => {
    const { ir, activePageId } = get();
    if (!ir || !activePageId) return null;
    return ir.pages.find((p) => p.$id === activePageId) || null;
  },

  getSelectedNode: () => {
    const { ir, activePageId, selectedPath } = get();
    if (!ir || !activePageId || !selectedPath) return null;
    const page = ir.pages.find((p) => p.$id === activePageId);
    if (!page) return null;
    return getNodeAtPath(page.root, selectedPath);
  },

  canUndo: () => get().undoStack.length > 0,
  canRedo: () => get().redoStack.length > 0,

  reset: () => set(initialState),
}));
