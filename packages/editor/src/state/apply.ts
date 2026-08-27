import { current } from "immer";
import type { Page } from "@tentoroforge/schema";
import type { NodeId } from "./types";

type AnyNode = any;

function findNode(root: AnyNode, id: NodeId): AnyNode | null {
  if (root.id === id) return root;
  for (const c of root.children ?? []) {
    const f = findNode(c, id);
    if (f) return f;
  }
  return null;
}

function findParent(root: AnyNode, id: NodeId): { parent: AnyNode; index: number } | null {
  for (const [i, c] of (root.children ?? []).entries()) {
    if (c.id === id) return { parent: root, index: i };
    const f = findParent(c, id);
    if (f) return f;
  }
  return null;
}

export function insertNode(page: Page, parentId: NodeId, index: number, node: AnyNode): void {
  const parent = findNode((page as any).root, parentId);
  if (!parent) throw new Error(`insertNode: parent ${parentId} not found`);
  if (!parent.children) parent.children = [];
  const idx = Math.max(0, Math.min(index, parent.children.length));
  parent.children.splice(idx, 0, node);
}

export function removeNode(page: Page, id: NodeId): { node: AnyNode; parentId: NodeId; index: number } {
  if ((page as any).root.id === id) {
    throw new Error(`removeNode: cannot remove root node`);
  }
  const loc = findParent((page as any).root, id);
  if (!loc) throw new Error(`removeNode: ${id} not found`);
  // Snapshot the node as a plain object before splicing (avoids revoked Immer proxy)
  const node = current(loc.parent.children![loc.index]);
  const parentId = loc.parent.id as string;
  const index = loc.index;
  loc.parent.children!.splice(loc.index, 1);
  return { node, parentId, index };
}

export function moveNode(page: Page, id: NodeId, toParentId: NodeId, toIndex: number): void {
  const snap = removeNode(page, id);
  insertNode(page, toParentId, toIndex, snap.node);
}

export function setNodeField(page: Page, id: NodeId, path: (string | number)[], value: unknown): void {
  const node = findNode((page as any).root, id);
  if (!node) throw new Error(`setNodeField: ${id} not found`);
  let cursor: any = node;
  for (let i = 0; i < path.length - 1; i++) {
    const seg = path[i];
    if (cursor[seg] === undefined) cursor[seg] = typeof path[i + 1] === "number" ? [] : {};
    cursor = cursor[seg];
  }
  const last = path[path.length - 1];
  if (value === undefined) {
    delete cursor[last];
  } else {
    cursor[last] = value;
  }
}

export function readNodeField(page: Page, id: NodeId, path: (string | number)[]): unknown {
  const node = findNode((page as any).root, id);
  if (!node) return undefined;
  let cursor: any = node;
  for (const seg of path) {
    if (cursor === undefined || cursor === null) return undefined;
    cursor = cursor[seg];
  }
  return cursor;
}
