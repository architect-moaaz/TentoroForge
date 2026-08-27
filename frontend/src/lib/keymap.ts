"use client";
import * as React from "react";
import { useEditorStore } from "./editor-store";

/** Locate a node's page and its chain of ancestor ids (children + slots). */
function locate(
  artifacts: any,
  nodeId: string,
): { pageId: string; ancestors: string[] } | null {
  for (const [pageId, page] of Object.entries(artifacts?.pageSchemas ?? {})) {
    const stack: Array<{ node: any; ancestors: string[] }> = [
      { node: (page as any).root, ancestors: [] },
    ];
    while (stack.length) {
      const { node, ancestors } = stack.pop()!;
      if (!node) continue;
      if (node.id === nodeId) return { pageId, ancestors };
      const childAnc = [...ancestors, node.id];
      if (Array.isArray(node.children)) {
        for (const c of node.children) stack.push({ node: c, ancestors: childAnc });
      }
      if (node.slots) {
        for (const arr of Object.values(node.slots) as any[]) {
          if (Array.isArray(arr)) for (const c of arr) stack.push({ node: c, ancestors: childAnc });
        }
      }
    }
  }
  return null;
}

/**
 * Reduce a selection to its TOP-LEVEL nodes — dropping any id that is a
 * descendant of another selected id. Removing/duplicating a parent already
 * covers its selected children, so keeping the descendants would make the
 * second action target an already-removed node (spurious "unknown node" error).
 */
function topLevelSelection(
  artifacts: any,
  ids: string[],
): Array<{ pageId: string; nodeId: string }> {
  const idSet = new Set(ids);
  const out: Array<{ pageId: string; nodeId: string }> = [];
  for (const id of ids) {
    const loc = locate(artifacts, id);
    if (!loc) continue;
    if (loc.ancestors.some((a) => idSet.has(a))) continue; // covered by an ancestor
    out.push({ pageId: loc.pageId, nodeId: id });
  }
  return out;
}

export function useKeymap() {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      // Don't hijack typing in inputs/textareas
      const tag = target?.tagName;
      if (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        (target as any)?.isContentEditable
      )
        return;

      const mod = e.metaKey || e.ctrlKey;
      const s = useEditorStore.getState();

      if (mod && !e.shiftKey && e.key.toLowerCase() === "z") {
        e.preventDefault();
        s.undo();
        return;
      }
      if (
        mod &&
        ((e.shiftKey && e.key.toLowerCase() === "z") ||
          e.key === "y")
      ) {
        e.preventDefault();
        s.redo();
        return;
      }

      if (mod && e.key.toLowerCase() === "d") {
        e.preventDefault();
        if (s.selectedNodeIds.length === 0 || !s.artifacts) return;
        const targets = topLevelSelection(s.artifacts, s.selectedNodeIds);
        // ONE transaction so a single Cmd+Z reverts the whole multi-duplicate.
        s.dispatchBatch(
          targets.map((t) => ({ type: "duplicateNode", pageId: t.pageId, nodeId: t.nodeId })),
        );
        return;
      }

      if (e.key === "Delete" || e.key === "Backspace") {
        if (s.selectedNodeIds.length === 0 || !s.artifacts) return;
        e.preventDefault();
        // Prune descendants (removing a parent already removes its selected
        // children — keeping them would target an already-gone node) and delete
        // as ONE transaction so a single Cmd+Z restores everything.
        const targets = topLevelSelection(s.artifacts, s.selectedNodeIds);
        s.dispatchBatch(
          targets.map((t) => ({ type: "removeNode", pageId: t.pageId, nodeId: t.nodeId })),
        );
        s.clearSelection();
        return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
