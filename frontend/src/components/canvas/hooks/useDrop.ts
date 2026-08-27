"use client";
import * as React from "react";
import { starterRegistry } from "@forge/registry";
import { useEditorStore } from "@/lib/editor-store";
import { getDraggingComponent } from "@/lib/palette-drag";

function findNode(
  artifacts: any,
  nodeId: string,
): { pageId: string; node: any } | null {
  for (const [pageId, page] of Object.entries(
    artifacts?.pageSchemas ?? {},
  )) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      if (n.id === nodeId) return { pageId, node: n };
      if (Array.isArray(n.children)) stack.push(...n.children);
      if (n.slots && typeof n.slots === "object") {
        for (const arr of Object.values(n.slots) as any[]) {
          if (Array.isArray(arr)) stack.push(...arr);
        }
      }
    }
  }
  return null;
}

export function validateDrop(
  parentType: string,
  childType: string,
  /** Current child count of the parent — enables maxChildren / single caps. */
  childCount = 0,
): { ok: true } | { ok: false; reason: string } {
  const parent = (starterRegistry as any)[parentType];
  if (!parent)
    return { ok: false, reason: `parent ${parentType} not in registry` };
  const slots = parent.slots ?? {};
  if (slots.type === "leaf") {
    return { ok: false, reason: `${parentType} is a leaf — cannot accept children` };
  }
  // `single` slots hold exactly one child.
  if (slots.type === "single" && childCount >= 1) {
    return { ok: false, reason: `${parentType} accepts a single child` };
  }
  if (slots.type === "list") {
    if (slots.accepts) {
      // A `["*"]` accepts-list is a wildcard (e.g. Dialog) — take any child.
      const accepts: string[] = slots.accepts;
      if (!accepts.includes("*") && !accepts.includes(childType)) {
        return { ok: false, reason: `${parentType} does not accept ${childType}` };
      }
    }
    if (Array.isArray(slots.rejects) && slots.rejects.includes(childType)) {
      return { ok: false, reason: `${parentType} does not allow ${childType}` };
    }
    // Enforce the fixed-slot cap (Split/Sidebar are 2-panel by contract).
    if (typeof slots.maxChildren === "number" && childCount >= slots.maxChildren) {
      return { ok: false, reason: `${parentType} is full (max ${slots.maxChildren})` };
    }
  }
  return { ok: true };
}

export function defaultPropsFor(componentName: string): Record<string, unknown> {
  const entry = (starterRegistry as any)[componentName];
  if (!entry) return {};
  return Object.fromEntries(
    Object.entries(entry.props as Record<string, any>)
      .map(([n, d]) => [n, d.default])
      .filter(([, v]) => v !== undefined),
  );
}

export function generateNodeId(componentName: string): string {
  const slug = componentName.toLowerCase();
  const rand = Math.random().toString(36).slice(2, 8);
  return `${slug}-${rand}`;
}

/**
 * The single source of truth for a freshly-dropped node. Materialises the
 * registry's default props and gives containers an empty children array so the
 * canvas can accept nested drops immediately. Exported so tests can exercise
 * the exact factory the palette drop uses (no drifting copy).
 */
export function buildDroppedNode(componentName: string): {
  id: string;
  type: string;
  props: Record<string, unknown>;
  children?: unknown[];
} {
  const isContainer =
    (starterRegistry as any)[componentName]?.slots?.type !== "leaf";
  return {
    id: generateNodeId(componentName),
    type: componentName,
    props: defaultPropsFor(componentName),
    ...(isContainer ? { children: [] } : {}),
  };
}

/** Every node id currently in the tree (children + slots, all pages). */
function collectNodeIds(artifacts: any): Set<string> {
  const ids = new Set<string>();
  for (const page of Object.values(artifacts?.pageSchemas ?? {})) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      if (n.id) ids.add(n.id);
      if (Array.isArray(n.children)) stack.push(...n.children);
      if (n.slots) for (const arr of Object.values(n.slots) as any[]) if (Array.isArray(arr)) stack.push(...arr);
    }
  }
  return ids;
}

/**
 * Resolve the nearest ancestor of `targetEl` that ACCEPTS the component
 * (honoring accepts/rejects/maxChildren), falling back to a page root that
 * accepts it. Shared by onDragOver (so the indicator marks the real drop target,
 * not a leaf it would actually skip) and onDrop.
 */
function resolveAcceptingParent(
  artifacts: any,
  componentName: string,
  targetEl: HTMLElement | null,
): { pageId: string; node: any } | null {
  const ids: string[] = [];
  let el = targetEl?.closest("[data-node-id]") as HTMLElement | null;
  while (el) {
    const id = el.getAttribute("data-node-id");
    if (id && !ids.includes(id)) ids.push(id);
    const parent = el.parentElement;
    el = parent ? (parent.closest("[data-node-id]") as HTMLElement | null) : null;
  }
  for (const id of ids) {
    const hit = findNode(artifacts, id);
    if (hit && validateDrop(hit.node.type, componentName, hit.node.children?.length ?? 0).ok) return hit;
  }
  for (const [pageId, page] of Object.entries(artifacts.pageSchemas ?? {})) {
    const root = (page as any).root;
    if (root && validateDrop(root.type, componentName, root.children?.length ?? 0).ok) {
      return { pageId, node: root };
    }
  }
  return null;
}

export function useCanvasDrop() {
  const dispatch = useEditorStore((s) => s.dispatch);
  const [hoverParent, setHoverParent] = React.useState<string | null>(null);

  const onDragOver = (e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes("text/x-forge-component")) return;
    e.preventDefault();
    const componentName = getDraggingComponent();
    const store = useEditorStore.getState();
    if (!componentName || !store.artifacts) {
      setHoverParent(null);
      e.dataTransfer.dropEffect = "copy";
      return;
    }
    // Highlight the REAL accepting target (or nothing → cursor shows no-drop),
    // instead of the innermost hovered node the drop would actually skip.
    const chosen = resolveAcceptingParent(store.artifacts, componentName, e.target as HTMLElement);
    setHoverParent(chosen ? chosen.node.id : null);
    e.dataTransfer.dropEffect = chosen ? "copy" : "none";
  };

  const onDragLeave = () => setHoverParent(null);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const componentName = e.dataTransfer.getData("text/x-forge-component");
    setHoverParent(null);
    if (!componentName) return;

    const store = useEditorStore.getState();
    if (!store.artifacts) return;

    const chosen = resolveAcceptingParent(store.artifacts, componentName, e.target as HTMLElement);
    if (!chosen) {
      // Surface the rejection instead of a silent console.warn.
      useEditorStore.setState({
        lastError: `${componentName} can't be placed here — no container on this page accepts it.`,
      });
      return;
    }

    const newNode = buildDroppedNode(componentName);
    // Guarantee a unique id — a collision would make validateForCommit reject
    // the whole insert and the drop would silently vanish.
    const existing = collectNodeIds(store.artifacts);
    while (existing.has(newNode.id)) newNode.id = generateNodeId(componentName);

    const childIndex = chosen.node.children?.length ?? 0;
    dispatch({
      type: "insertNode",
      pageId: chosen.pageId,
      parentId: chosen.node.id,
      index: childIndex,
      node: newNode as any,
    });

    // Auto-select the new node so the user sees its props immediately
    store.setSelection(newNode.id);
  };

  return { onDragOver, onDragLeave, onDrop, hoverParent };
}
