"use client";
import * as React from "react";
import { starterRegistry } from "@forge/registry";
import { useEditorStore } from "@/lib/editor-store";

export type ReorderPos = "before" | "after" | "inside";
export interface ReorderIndicatorState {
  targetId: string;
  pos: ReorderPos;
}

/** dataTransfer type that marks a canvas-internal node move (distinct from the
 *  palette's "text/x-forge-component" add-a-new-component drag). */
const REORDER_MIME = "text/x-forge-reorder";

interface NodeLoc {
  pageId: string;
  /** null for a page root (which cannot be moved). */
  parentId: string | null;
  index: number;
  node: any;
}

/** Locate a node by id across all page schemas, tracking its parent + index
 *  within the parent's `children` array. Mirrors what @forge/patches moveNode
 *  operates on (children arrays), so the client-side math matches the reducer. */
function locate(artifacts: any, nodeId: string): NodeLoc | null {
  for (const [pageId, page] of Object.entries(artifacts?.pageSchemas ?? {})) {
    const root = (page as any).root;
    const stack: Array<{ node: any; parent: any; index: number }> = [
      { node: root, parent: null, index: -1 },
    ];
    while (stack.length) {
      const cur = stack.pop()!;
      if (cur.node?.id === nodeId) {
        return {
          pageId,
          parentId: cur.parent ? cur.parent.id : null,
          index: cur.index,
          node: cur.node,
        };
      }
      if (Array.isArray(cur.node?.children)) {
        cur.node.children.forEach((c: any, i: number) =>
          stack.push({ node: c, parent: cur.node, index: i }),
        );
      }
    }
  }
  return null;
}

/** True if `descId` is `ancestorId` itself or lives anywhere in its subtree.
 *  Prevents dropping a node into its own descendant (which would detach a
 *  chunk of the tree). */
function isSelfOrDescendant(node: any, descId: string): boolean {
  if (!node) return false;
  if (node.id === descId) return true;
  if (Array.isArray(node.children)) {
    for (const c of node.children) if (isSelfOrDescendant(c, descId)) return true;
  }
  return false;
}

function isContainerType(type: string | undefined): boolean {
  if (!type) return false;
  const entry = (starterRegistry as any)[type];
  return !!entry && entry.slots?.type !== "leaf";
}

/** Whether a parent of `parentType` will accept a child of `childType`. */
function accepts(
  parentType: string | undefined,
  childType: string | undefined,
  /** Effective child count AFTER the move (excludes the dragged node if it's
   * already a child of this parent) — enables maxChildren/single enforcement. */
  effectiveCount = 0,
): boolean {
  if (!parentType || !childType) return false;
  const parent = (starterRegistry as any)[parentType];
  if (!parent) return false;
  const slots = parent.slots ?? {};
  if (slots.type === "leaf") return false;
  if (slots.type === "single" && effectiveCount >= 1) return false;
  if (slots.type === "list") {
    if (slots.accepts) {
      // `["*"]` is a wildcard (e.g. Dialog accepts any child).
      const list: string[] = slots.accepts;
      if (!list.includes("*") && !list.includes(childType)) return false;
    }
    if (Array.isArray(slots.rejects) && slots.rejects.includes(childType)) return false;
    if (typeof slots.maxChildren === "number" && effectiveCount >= slots.maxChildren) return false;
  }
  return true;
}

/**
 * Drag-to-reorder for existing canvas nodes. The live Canvas renders the page
 * via <Engine>, so nodes are plain DOM with `data-node-id` — there is no
 * per-node React wrapper to hang handlers on. We therefore use event
 * DELEGATION on the canvas-root container (same pattern as useSelection /
 * useCanvasDrop) and drive an HTML5 drag whose source id is stashed in a ref
 * (dataTransfer payload is unreadable during dragover).
 *
 * The handlers return `true` when they've consumed a reorder drag, so Canvas
 * can fall through to the palette-drop handler for the add-a-component drag.
 */
export function useCanvasReorder() {
  const [indicator, setIndicator] = React.useState<ReorderIndicatorState | null>(null);
  const draggingIdRef = React.useRef<string | null>(null);

  const clear = React.useCallback(() => {
    setIndicator(null);
    draggingIdRef.current = null;
  }, []);

  const onDragStart = (e: React.DragEvent) => {
    const el = (e.target as HTMLElement).closest("[data-node-id]") as HTMLElement | null;
    const id = el?.getAttribute("data-node-id");
    if (!id) return;
    const store = useEditorStore.getState();
    const loc = locate(store.artifacts, id);
    // Root nodes (no parent) can't be moved — let the drag be a no-op.
    if (!loc || loc.parentId === null) return;
    e.stopPropagation();
    draggingIdRef.current = id;
    e.dataTransfer.setData(REORDER_MIME, id);
    e.dataTransfer.effectAllowed = "move";
  };

  /** @returns true if this was a reorder drag (consumed). */
  const onDragOver = (e: React.DragEvent): boolean => {
    if (!e.dataTransfer.types.includes(REORDER_MIME)) return false;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";

    const draggingId = draggingIdRef.current;
    if (!draggingId) {
      setIndicator(null);
      return true;
    }

    const targetEl = (e.target as HTMLElement).closest("[data-node-id]") as HTMLElement | null;
    const targetId = targetEl?.getAttribute("data-node-id") ?? null;
    if (!targetId || targetId === draggingId) {
      setIndicator(null);
      return true;
    }

    const store = useEditorStore.getState();
    const dragLoc = locate(store.artifacts, draggingId);
    const targetLoc = locate(store.artifacts, targetId);
    if (!dragLoc || !targetLoc) {
      setIndicator(null);
      return true;
    }
    // Never drop a node into itself or its own subtree.
    if (isSelfOrDescendant(dragLoc.node, targetId)) {
      setIndicator(null);
      return true;
    }

    const childType = dragLoc.node?.type as string | undefined;
    const rect = targetEl!.getBoundingClientRect();
    const y = e.clientY - rect.top;
    const h = rect.height || 1;
    const targetIsContainer = isContainerType(targetLoc.node?.type);

    let pos: ReorderPos;
    if (targetIsContainer) {
      if (y < h * 0.25) pos = "before";
      else if (y > h * 0.75) pos = "after";
      else pos = "inside";
    } else {
      pos = y < h * 0.5 ? "before" : "after";
    }

    // Resolve the prospective parent for this position and require it to accept
    // the dragged child type. If an "inside" drop isn't accepted, degrade to a
    // sibling drop next to the container rather than rejecting outright.
    // Resolve the prospective parent node + its EFFECTIVE child count for a
    // given position (excluding the dragged node when it's already a child, so a
    // within-container reorder isn't falsely blocked by maxChildren).
    const parentInfoFor = (p: ReorderPos): { type?: string; count: number } => {
      const node = p === "inside"
        ? targetLoc.node
        : (targetLoc.parentId ? locate(store.artifacts, targetLoc.parentId)?.node : undefined);
      const count = Array.isArray(node?.children) ? node!.children.length : 0;
      const alreadyChild = dragLoc.parentId === node?.id;
      return { type: node?.type, count: alreadyChild ? Math.max(0, count - 1) : count };
    };
    const info = parentInfoFor(pos);
    if (!accepts(info.type, childType, info.count)) {
      const after = parentInfoFor("after");
      if (pos === "inside" && accepts(after.type, childType, after.count)) {
        pos = "after";
      } else {
        setIndicator(null);
        return true;
      }
    }

    setIndicator({ targetId, pos });
    return true;
  };

  const onDragLeave = () => setIndicator(null);

  const onDragEnd = () => clear();

  /** @returns true if this was a reorder drop (consumed). */
  const onDrop = (e: React.DragEvent): boolean => {
    if (!e.dataTransfer.types.includes(REORDER_MIME)) return false;
    e.preventDefault();

    const draggingId = e.dataTransfer.getData(REORDER_MIME) || draggingIdRef.current;
    const ind = indicator;
    clear();
    if (!draggingId || !ind) return true;

    const store = useEditorStore.getState();
    const dragLoc = locate(store.artifacts, draggingId);
    const targetLoc = locate(store.artifacts, ind.targetId);
    if (!dragLoc || dragLoc.parentId === null || !targetLoc) return true;
    if (isSelfOrDescendant(dragLoc.node, ind.targetId)) return true;

    let newParentId: string;
    let rawIndex: number;
    if (ind.pos === "inside") {
      newParentId = ind.targetId;
      rawIndex = Array.isArray(targetLoc.node?.children) ? targetLoc.node.children.length : 0;
    } else {
      if (targetLoc.parentId === null) return true; // sibling of a root — impossible
      newParentId = targetLoc.parentId;
      rawIndex = ind.pos === "after" ? targetLoc.index + 1 : targetLoc.index;
    }

    // Moving into own subtree guard (parent could be a descendant for "inside").
    if (newParentId === draggingId || isSelfOrDescendant(dragLoc.node, newParentId)) return true;

    // @forge/patches moveNode removes the node from its old parent FIRST, then
    // splices into the new parent. When staying in the same parent and moving
    // to a later slot, that removal shifts everything left by one — compensate.
    let newIndex = rawIndex;
    if (newParentId === dragLoc.parentId && dragLoc.index < rawIndex) {
      newIndex = rawIndex - 1;
    }
    // Dropped exactly where it already is — nothing to do.
    if (newParentId === dragLoc.parentId && newIndex === dragLoc.index) return true;

    store.dispatch({
      type: "moveNode",
      pageId: dragLoc.pageId,
      nodeId: draggingId,
      newParentId,
      newIndex,
    } as any);
    store.setSelection(draggingId);
    return true;
  };

  return { indicator, onDragStart, onDragOver, onDragLeave, onDragEnd, onDrop };
}
