import { produce } from "immer";
import type { Page } from "@tentoroforge/schema";
import type { Mutation, NodeId } from "./types";
import { insertNode, removeNode, moveNode, setNodeField, readNodeField } from "./apply";

export function dispatchApply(page: Page, m: Mutation): void {
  switch (m.kind) {
    case "insert-node":
      insertNode(page, m.parentId, m.index, m.node);
      break;
    case "remove-node":
      removeNode(page, m.id);
      break;
    case "move-node":
      moveNode(page, m.id, m.toParentId, m.toIndex);
      break;
    case "set-prop":
      setNodeField(page, m.id, ["props", m.key], m.value);
      break;
    case "set-style":
      setNodeField(page, m.id, ["style", m.key], m.value);
      break;
    case "set-bind":
      setNodeField(page, m.id, ["bind"], m.bind);
      break;
    case "set-visible-if":
      setNodeField(page, m.id, ["visibleIf"], m.expr);
      break;
    case "set-event":
      setNodeField(page, m.id, ["on", m.eventName], m.handler);
      break;
    case "rename-node-id": {
      throw new Error("rename-node-id not implemented in 2A");
    }
    case "composite":
      for (const sub of m.mutations) dispatchApply(page, sub);
      break;
  }
}

export function invert(m: Mutation): Mutation {
  switch (m.kind) {
    case "insert-node":
      return { kind: "remove-node", id: m.node.id, removed: { node: m.node, parentId: m.parentId, index: m.index } };
    case "remove-node":
      return { kind: "insert-node", parentId: m.removed.parentId, index: m.removed.index, node: m.removed.node };
    case "move-node":
      return { kind: "move-node", id: m.id, fromParentId: m.toParentId, fromIndex: m.toIndex, toParentId: m.fromParentId, toIndex: m.fromIndex };
    case "set-prop":
      return { kind: "set-prop", id: m.id, key: m.key, value: m.prevValue, prevValue: m.value };
    case "set-style":
      return { kind: "set-style", id: m.id, key: m.key, value: m.prevValue, prevValue: m.value };
    case "set-bind":
      return { kind: "set-bind", id: m.id, bind: m.prevBind, prevBind: m.bind };
    case "set-visible-if":
      return { kind: "set-visible-if", id: m.id, expr: m.prevExpr, prevExpr: m.expr };
    case "set-event":
      return { kind: "set-event", id: m.id, eventName: m.eventName, handler: m.prevHandler, prevHandler: m.handler };
    case "rename-node-id":
      return { kind: "rename-node-id", oldId: m.newId, newId: m.oldId };
    case "composite":
      return { kind: "composite", mutations: m.mutations.map(invert).reverse() };
  }
}

// Builders
let _idCounter = 0;
export function generateNodeId(): NodeId {
  _idCounter++;
  return `n${_idCounter.toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export function buildInsertNode(parentId: NodeId, index: number, node: any): Mutation {
  return { kind: "insert-node", parentId, index, node };
}

export function buildRemoveNode(id: NodeId, page: Page): Mutation {
  // Find snapshot before removal (read-only traversal)
  function find(root: any, parent: any, idx: number): { node: any; parentId: string; index: number } | null {
    if (root.id === id) return { node: root, parentId: parent?.id ?? "", index: idx };
    for (const [i, c] of (root.children ?? []).entries()) {
      const f = find(c, root, i);
      if (f) return f;
    }
    return null;
  }
  const snap = find((page as any).root, null, 0);
  if (!snap) throw new Error(`buildRemoveNode: ${id} not found`);
  return { kind: "remove-node", id, removed: snap };
}

export function buildMoveNode(id: NodeId, toParentId: NodeId, toIndex: number, page: Page): Mutation {
  const removed = (buildRemoveNode(id, page) as Extract<Mutation, { kind: "remove-node" }>).removed;
  return { kind: "move-node", id, fromParentId: removed.parentId, fromIndex: removed.index, toParentId, toIndex };
}

export function buildSetProp(id: NodeId, key: string, value: unknown, page: Page): Mutation {
  const prevValue = readNodeField(page, id, ["props", key]);
  return { kind: "set-prop", id, key, value, prevValue };
}

export function buildSetStyle(id: NodeId, key: any, value: any, page: Page): Mutation {
  const prevValue = readNodeField(page, id, ["style", key]) as any;
  return { kind: "set-style", id, key, value, prevValue };
}

export function buildSetBind(id: NodeId, bind: any, page: Page): Mutation {
  const prevBind = readNodeField(page, id, ["bind"]) as any;
  return { kind: "set-bind", id, bind, prevBind };
}

export function buildSetVisibleIf(id: NodeId, expr: any, page: Page): Mutation {
  const prevExpr = readNodeField(page, id, ["visibleIf"]) as any;
  return { kind: "set-visible-if", id, expr, prevExpr };
}

export function buildSetEvent(id: NodeId, eventName: any, handler: any, page: Page): Mutation {
  const prevHandler = readNodeField(page, id, ["on", eventName]) as any;
  return { kind: "set-event", id, eventName, handler, prevHandler };
}

// Deep-search helpers (read-only, operates on plain objects)
export function findNodeDeep(root: any, id: NodeId): any | null {
  if (root.id === id) return root;
  for (const c of root.children ?? []) {
    const f = findNodeDeep(c, id);
    if (f) return f;
  }
  return null;
}

export function findParentId(root: any, id: NodeId): NodeId | null {
  for (const c of root.children ?? []) {
    if (c.id === id) return root.id;
    const f = findParentId(c, id);
    if (f) return f;
  }
  return null;
}

export function findIndexInParent(root: any, id: NodeId): number {
  for (const [i, c] of (root.children ?? []).entries()) {
    if (c.id === id) return i;
    const f = findIndexInParent(c, id);
    if (f !== -1) return f;
  }
  return -1;
}

export function cloneNodeWithFreshIds(node: any): any {
  const fresh: any = {
    ...node,
    id: generateNodeId(),
  };
  if (Array.isArray(node.children)) {
    fresh.children = node.children.map(cloneNodeWithFreshIds);
  }
  return fresh;
}

export function buildBulkRemove(ids: NodeId[], page: Page): Mutation {
  const subs: Mutation[] = [];
  let working: any = JSON.parse(JSON.stringify(page));
  for (const id of ids) {
    const m = buildRemoveNode(id, working);
    subs.push(m);
    working = produce(working, (d: any) => { dispatchApply(d, m); });
  }
  return { kind: "composite", mutations: subs };
}
