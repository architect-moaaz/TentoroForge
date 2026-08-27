import type { Page } from "@tentoroforge/schema";
import type { Registry } from "@tentoroforge/library";
import type { NodeId } from "../state/types";
import type { DragPayload } from "./types";

const RESERVED_LIBRARY_NAMES = new Set([
  "Stack", "Row", "Grid", "Container", "Spacer",
  "Box", "Text", "Image",
  "Repeat", "Conditional", "DataBoundary",
  "Slot",
]);

function findNode(root: any, id: NodeId): any | null {
  if (root.id === id) return root;
  for (const c of root.children ?? []) {
    const f = findNode(c, id);
    if (f) return f;
  }
  return null;
}

function isDescendant(root: any, ancestorId: NodeId, candidateId: NodeId): boolean {
  const ancestor = findNode(root, ancestorId);
  if (!ancestor) return false;
  return findNode(ancestor, candidateId) !== null && ancestorId !== candidateId;
}

export function canDrop(payload: DragPayload, targetId: NodeId, page: Page, registry: Registry): boolean {
  const target = findNode((page as any).root, targetId);
  if (!target) return false;

  // Layout/primitive node accept-children rules.
  // v2 structural nodes (Split, Sidebar, Tabs) also accept children but are
  // not in the library registry — include them here so the gate doesn't
  // reject them before we can apply child-count contracts below.
  const layoutAcceptsChildren = [
    "Stack", "Row", "Grid", "Container", "Box",
    // v2 layout nodes — accept children but enforce count limits (see below)
    "Split", "Sidebar", "Tabs",
  ].includes(target.type);
  const isLibrary = !RESERVED_LIBRARY_NAMES.has(target.type);
  const libraryEntry = isLibrary ? registry.get(target.type) : undefined;
  const targetAccepts = layoutAcceptsChildren || (libraryEntry?.acceptsChildren ?? false);

  if (!targetAccepts) return false;

  // -------------------------------------------------------------------------
  // Task 33: v2 schema child-count contracts.
  // Applied after the acceptsChildren gate, before self/descendant checks.
  // Each rule mirrors the invariant enforced by layout-v2.ts at parse time so
  // the editor prevents invalid states rather than surfacing parse errors later.
  //
  // Note: Form and Custom never reach this switch — they are caught earlier by
  // the !targetAccepts gate above (Form: registry says acceptsChildren=false;
  // Custom: not in the library registry so libraryEntry is undefined and
  // targetAccepts evaluates to false).  The cases below cover layout-v2 nodes
  // that DO accept children but cap their count.
  // -------------------------------------------------------------------------
  const currentCount = (target.children ?? []).length;

  switch (target.type) {
    case "Tabs": {
      // TabsNode.refine: children.length must equal props.tabs.length.
      // Block any drop that would push children beyond the tab-header count.
      const tabsCount = (target.props?.tabs ?? []).length;
      if (currentCount >= tabsCount) return false;
      break;
    }
    case "Split":
    // SplitNode: children is z.array(NodeV2Ref).length(2) — exactly 2.
    case "Sidebar":
      // SidebarNode: same exact-2 constraint.
      if (currentCount >= 2) return false;
      break;
    default:
      break;
  }

  if (payload.kind === "palette") {
    if (RESERVED_LIBRARY_NAMES.has(payload.libraryName)) return false;
    return registry.has(payload.libraryName);
  }

  // node payload — forbid self / descendant
  if (payload.id === targetId) return false;
  if (isDescendant((page as any).root, payload.id, targetId)) return false;
  return true;
}
