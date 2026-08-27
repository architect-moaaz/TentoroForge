// packages/patches/src/apply.ts
import type { Artifacts, EditorAction, ApplyResult, SchemaNode, PageId } from "./types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x)) as T;
}

interface NodeLocation {
  node: SchemaNode;
  parent: SchemaNode | null;
  index: number;
  /** The array the node actually lives in — either parent.children or one of
   * parent.slots[slotKey]. Splice THIS, never parent.children directly, or a
   * slot-resident node's operation corrupts an unrelated child array. */
  container: SchemaNode[] | null;
  /** Set when the node lives in a named slot rather than children. */
  slotKey?: string;
}

function findNode(root: SchemaNode, nodeId: string): NodeLocation | null {
  if (root.id === nodeId) {
    return { node: root, parent: null, index: -1, container: null };
  }

  // Search children array
  if (root.children) {
    for (let i = 0; i < root.children.length; i++) {
      if (root.children[i].id === nodeId) {
        return { node: root.children[i], parent: root, index: i, container: root.children };
      }
      const found = findNode(root.children[i], nodeId);
      if (found) return found;
    }
  }

  // Search slots — return the containing slot array + its key so mutations hit
  // the right array (not parent.children).
  if (root.slots) {
    for (const slotKey of Object.keys(root.slots)) {
      const slotNodes = root.slots[slotKey];
      for (let i = 0; i < slotNodes.length; i++) {
        if (slotNodes[i].id === nodeId) {
          return { node: slotNodes[i], parent: root, index: i, container: slotNodes, slotKey };
        }
        const found = findNode(slotNodes[i], nodeId);
        if (found) return found;
      }
    }
  }

  return null;
}

/**
 * Recursively rewrite token path references in all string prop values.
 * A prop value of "color.brand.primary" is a token ref.
 */
function rewriteTokenRefs(node: SchemaNode, from: string, to: string): void {
  if (node.props) {
    for (const key of Object.keys(node.props)) {
      const v = node.props[key];
      if (typeof v === "string" && v === from) {
        node.props[key] = to;
      }
    }
  }
  if (node.children) {
    for (const child of node.children) {
      rewriteTokenRefs(child, from, to);
    }
  }
  if (node.slots) {
    for (const slotNodes of Object.values(node.slots)) {
      for (const child of slotNodes) {
        rewriteTokenRefs(child, from, to);
      }
    }
  }
}

function getNestedValue(obj: any, path: string[]): unknown {
  return path.reduce((cur: any, key) => cur?.[key], obj);
}

function setNestedValue(obj: any, path: string[], value: unknown): void {
  let cur = obj;
  for (let i = 0; i < path.length - 1; i++) {
    if (cur[path[i]] === undefined || cur[path[i]] === null) {
      cur[path[i]] = {};
    }
    cur = cur[path[i]];
  }
  cur[path[path.length - 1]] = value;
}

function deleteNestedValue(obj: any, path: string[]): void {
  const parent = path.slice(0, -1).reduce((cur: any, key) => cur?.[key], obj);
  if (parent !== undefined && parent !== null) {
    delete parent[path[path.length - 1]];
  }
}

// ---------------------------------------------------------------------------
// applyAction — main entry point
// ---------------------------------------------------------------------------

export function applyAction(artifacts: Artifacts, action: EditorAction): ApplyResult {
  const next = clone(artifacts);

  switch (action.type) {
    // -----------------------------------------------------------------------
    case "updateProp": {
      const page = next.pageSchemas[action.pageId];
      if (!page) throw new Error(`applyAction: unknown page "${action.pageId}"`);
      const loc = findNode(page.root, action.nodeId);
      if (!loc) throw new Error(`applyAction: unknown node "${action.nodeId}" in page "${action.pageId}"`);
      const node = loc.node;
      if (!node.props) node.props = {};
      const prev = node.props[action.propName];
      node.props[action.propName] = action.value;
      return {
        next,
        inverse: {
          type: "updateProp",
          pageId: action.pageId,
          nodeId: action.nodeId,
          propName: action.propName,
          value: prev,
        },
      };
    }

    // -----------------------------------------------------------------------
    // Writes the node's top-level StyleSlot envelope (`node.style`), the field
    // the renderer actually resolves (applyStyleSlot for structural nodes,
    // the `style` prop for library nodes). Distinct from updateProp, which
    // writes node.props. Removing a key (value === undefined) keeps the
    // envelope tidy so an unset control doesn't leave a dangling entry.
    case "updateStyle": {
      const page = next.pageSchemas[action.pageId];
      if (!page) throw new Error(`applyAction: unknown page "${action.pageId}"`);
      const loc = findNode(page.root, action.nodeId);
      if (!loc) throw new Error(`applyAction: unknown node "${action.nodeId}" in page "${action.pageId}"`);
      const node = loc.node as { style?: Record<string, unknown>; props?: Record<string, unknown> };
      const prevStyle = node.style;
      const prev = prevStyle ? prevStyle[action.styleKey] : undefined;
      const nextStyle: Record<string, unknown> = { ...(prevStyle ?? {}) };
      if (action.value === undefined || action.value === "" || action.value === null) {
        delete nextStyle[action.styleKey];
      } else {
        nextStyle[action.styleKey] = action.value;
      }
      if (Object.keys(nextStyle).length > 0) node.style = nextStyle;
      else delete (node as { style?: unknown }).style;
      // Clear any stale legacy node.props.style[key]. Structural nodes spread
      // node.props.style LAST (as callerStyle for the Figma/MCP pipeline), so a
      // leftover value there — e.g. from the old Style panel that wrote
      // props.style — would override the StyleSlot we just set. Clear only the
      // SAME key so unrelated Figma-imported inline styles are untouched.
      const legacy = node.props && (node.props.style as Record<string, unknown> | undefined);
      if (legacy && typeof legacy === "object" && action.styleKey in legacy) {
        delete legacy[action.styleKey];
        if (Object.keys(legacy).length === 0) delete (node.props as Record<string, unknown>).style;
      }
      return {
        next,
        inverse: {
          type: "updateStyle",
          pageId: action.pageId,
          nodeId: action.nodeId,
          styleKey: action.styleKey,
          value: prev,
        },
      };
    }

    // -----------------------------------------------------------------------
    case "insertNode": {
      const page = next.pageSchemas[action.pageId];
      if (!page) throw new Error(`applyAction: unknown page "${action.pageId}"`);
      const loc = findNode(page.root, action.parentId);
      if (!loc) throw new Error(`applyAction: unknown parent node "${action.parentId}" in page "${action.pageId}"`);
      const parent = loc.node;
      if (action.slotKey) {
        // Insert into a named slot (used by the removeNode inverse to restore a
        // slot-resident node to the array it actually came from).
        if (!parent.slots) parent.slots = {};
        if (!parent.slots[action.slotKey]) parent.slots[action.slotKey] = [];
        parent.slots[action.slotKey].splice(action.index, 0, clone(action.node));
      } else {
        if (!parent.children) parent.children = [];
        parent.children.splice(action.index, 0, clone(action.node));
      }
      return {
        next,
        inverse: {
          type: "removeNode",
          pageId: action.pageId,
          nodeId: action.node.id,
        },
      };
    }

    // -----------------------------------------------------------------------
    case "removeNode": {
      const page = next.pageSchemas[action.pageId];
      if (!page) throw new Error(`applyAction: unknown page "${action.pageId}"`);
      const loc = findNode(page.root, action.nodeId);
      if (!loc) throw new Error(`applyAction: unknown node "${action.nodeId}" in page "${action.pageId}"`);
      if (!loc.parent) throw new Error(`applyAction: cannot remove root node "${action.nodeId}"`);
      const removedNode = clone(loc.node);
      const removedIndex = loc.index;
      const parentNode = loc.parent;
      // Splice the ACTUAL containing array (children OR the slot array), not
      // parent.children — otherwise a slot-resident node removes the wrong
      // sibling (or crashes when parent.children is undefined).
      loc.container!.splice(removedIndex, 1);
      return {
        next,
        inverse: {
          type: "insertNode",
          pageId: action.pageId,
          parentId: parentNode.id,
          index: removedIndex,
          node: removedNode,
          slotKey: loc.slotKey, // restore into the same slot it came from
        },
      };
    }

    // -----------------------------------------------------------------------
    case "moveNode": {
      const page = next.pageSchemas[action.pageId];
      if (!page) throw new Error(`applyAction: unknown page "${action.pageId}"`);
      const loc = findNode(page.root, action.nodeId);
      if (!loc) throw new Error(`applyAction: unknown node "${action.nodeId}" in page "${action.pageId}"`);
      if (!loc.parent) throw new Error(`applyAction: cannot move root node "${action.nodeId}"`);

      const oldParentId = loc.parent.id;
      const oldIndex = loc.index;

      // Remove from current parent's ACTUAL array (children or slot).
      const movedNode = clone(loc.node);
      loc.container!.splice(loc.index, 1);

      // Find new parent in the updated tree
      const newParentLoc = findNode(page.root, action.newParentId);
      if (!newParentLoc) throw new Error(`applyAction: unknown new parent "${action.newParentId}" in page "${action.pageId}"`);
      const newParent = newParentLoc.node;
      if (!newParent.children) newParent.children = [];
      newParent.children.splice(action.newIndex, 0, movedNode);

      return {
        next,
        inverse: {
          type: "moveNode",
          pageId: action.pageId,
          nodeId: action.nodeId,
          newParentId: oldParentId,
          newIndex: oldIndex,
        },
      };
    }

    // -----------------------------------------------------------------------
    case "duplicateNode": {
      const page = next.pageSchemas[action.pageId];
      if (!page) throw new Error(`applyAction: unknown page "${action.pageId}"`);
      const loc = findNode(page.root, action.nodeId);
      if (!loc) throw new Error(`applyAction: unknown node "${action.nodeId}" in page "${action.pageId}"`);
      if (!loc.parent) throw new Error(`applyAction: cannot duplicate root node "${action.nodeId}"`);

      const dup = clone(loc.node);
      // Re-id the ENTIRE duplicated subtree, not just the top node. Node ids
      // must be globally unique (validateForCommit rejects duplicates), so
      // copying a container without re-iding its children/slots would trip the
      // commit gate and the duplicate would be silently dropped. A per-node
      // counter off one timestamp keeps every new id distinct.
      const stamp = Date.now();
      let counter = 0;
      const reid = (n: SchemaNode) => {
        n.id = `${n.id}_dup_${stamp}_${counter++}`;
        if (Array.isArray(n.children)) n.children.forEach(reid);
        if (n.slots) {
          for (const arr of Object.values(n.slots)) {
            if (Array.isArray(arr)) arr.forEach(reid);
          }
        }
      };
      reid(dup);
      // Insert the copy into the SAME array as the original (children or slot).
      const insertIndex = loc.index + 1;
      loc.container!.splice(insertIndex, 0, dup);

      return {
        next,
        inverse: {
          type: "removeNode",
          pageId: action.pageId,
          nodeId: dup.id,
        },
      };
    }

    // -----------------------------------------------------------------------
    case "bindProp": {
      const page = next.pageSchemas[action.pageId];
      if (!page) throw new Error(`applyAction: unknown page "${action.pageId}"`);
      const loc = findNode(page.root, action.nodeId);
      if (!loc) throw new Error(`applyAction: unknown node "${action.nodeId}" in page "${action.pageId}"`);
      const node = loc.node;
      if (!node.props) node.props = {};
      const prev = node.props[action.propName];
      node.props[action.propName] = { $binding: action.binding };

      // Inverse: if previous value was a literal, unbind back to it
      if (prev !== undefined && (typeof prev !== "object" || !(prev as any).$binding)) {
        return {
          next,
          inverse: {
            type: "unbindProp",
            pageId: action.pageId,
            nodeId: action.nodeId,
            propName: action.propName,
            literalValue: prev,
          },
        };
      }
      // Previous was also a binding or undefined — restore via updateProp
      return {
        next,
        inverse: {
          type: "updateProp",
          pageId: action.pageId,
          nodeId: action.nodeId,
          propName: action.propName,
          value: prev,
        },
      };
    }

    // -----------------------------------------------------------------------
    case "unbindProp": {
      const page = next.pageSchemas[action.pageId];
      if (!page) throw new Error(`applyAction: unknown page "${action.pageId}"`);
      const loc = findNode(page.root, action.nodeId);
      if (!loc) throw new Error(`applyAction: unknown node "${action.nodeId}" in page "${action.pageId}"`);
      const node = loc.node;
      if (!node.props) node.props = {};
      const prev = node.props[action.propName];
      node.props[action.propName] = action.literalValue;

      // Inverse: re-bind if previous was a $binding
      if (prev && typeof prev === "object" && (prev as any).$binding) {
        return {
          next,
          inverse: {
            type: "bindProp",
            pageId: action.pageId,
            nodeId: action.nodeId,
            propName: action.propName,
            binding: (prev as any).$binding as string,
          },
        };
      }
      return {
        next,
        inverse: {
          type: "updateProp",
          pageId: action.pageId,
          nodeId: action.nodeId,
          propName: action.propName,
          value: prev,
        },
      };
    }

    // -----------------------------------------------------------------------
    case "addPage": {
      next.pageSchemas[action.pageId] = {
        schemaVersion: "2",
        id: action.pageId,
        route: action.route,
        root: clone(action.root),
      };
      next.navFlow.pages.push({
        id: action.pageId,
        route: action.route,
        title: action.title,
        schemaFile: `src/schemas/${action.pageId}.json`,
        params: [],
        // Editor-created pages are real shell pages by default so they render
        // inside the app frame AND surface in the generated app's sidebar (the
        // runtime nav merges shell:true nav-flow pages into the SideNav). A
        // caller can opt a standalone/public page out via `shell: false`.
        shell: action.shell ?? true,
      });
      return {
        next,
        inverse: { type: "removePage", pageId: action.pageId },
      };
    }

    // -----------------------------------------------------------------------
    case "removePage": {
      const pageSchema = next.pageSchemas[action.pageId];
      if (!pageSchema) throw new Error(`applyAction: unknown page "${action.pageId}"`);
      const navPage = next.navFlow.pages.find(p => p.id === action.pageId);
      const title = navPage?.title ?? action.pageId;
      const route = navPage?.route ?? pageSchema.route ?? `/${action.pageId}`;
      // Capture the shell flag so undo of a delete restores it (otherwise a
      // shell:true page comes back as the addPage default and could change its
      // sidebar/chrome membership).
      const shell = (navPage as { shell?: boolean } | undefined)?.shell;
      const root = clone(pageSchema.root);

      // Remove from pageSchemas
      delete next.pageSchemas[action.pageId];

      // Remove from navFlow.pages
      next.navFlow.pages = next.navFlow.pages.filter(p => p.id !== action.pageId);

      // Scrub referencing transitions
      next.navFlow.transitions = next.navFlow.transitions.filter(
        t => t.from !== action.pageId && t.to !== action.pageId,
      );

      return {
        next,
        inverse: {
          type: "addPage",
          pageId: action.pageId,
          route,
          title,
          root,
          ...(shell === undefined ? {} : { shell }),
        },
      };
    }

    // -----------------------------------------------------------------------
    case "renamePage": {
      const navPage = next.navFlow.pages.find(p => p.id === action.pageId);
      if (!navPage) throw new Error(`applyAction: unknown page "${action.pageId}" in navFlow`);
      const prevTitle = navPage.title;
      navPage.title = action.title;
      return {
        next,
        inverse: { type: "renamePage", pageId: action.pageId, title: prevTitle },
      };
    }

    // -----------------------------------------------------------------------
    case "updateRoute": {
      const navPage = next.navFlow.pages.find(p => p.id === action.pageId);
      if (!navPage) throw new Error(`applyAction: unknown page "${action.pageId}" in navFlow`);
      const prevRoute = navPage.route;
      navPage.route = action.route;
      if (next.pageSchemas[action.pageId]) {
        next.pageSchemas[action.pageId].route = action.route;
      }
      return {
        next,
        inverse: { type: "updateRoute", pageId: action.pageId, route: prevRoute },
      };
    }

    // -----------------------------------------------------------------------
    case "addDataSource": {
      const page = next.pageSchemas[action.pageId];
      if (!page) throw new Error(`applyAction: unknown page "${action.pageId}"`);
      if (!Array.isArray(page.dataSources)) page.dataSources = [];
      if (page.dataSources.some(d => d.name === action.source.name)) {
        throw new Error(`applyAction: dataSource "${action.source.name}" already exists`);
      }
      page.dataSources.push(clone(action.source));
      return {
        next,
        inverse: { type: "removeDataSource", pageId: action.pageId, name: action.source.name },
      };
    }

    // -----------------------------------------------------------------------
    case "removeDataSource": {
      const page = next.pageSchemas[action.pageId];
      if (!page || !Array.isArray(page.dataSources)) {
        throw new Error(`applyAction: unknown page "${action.pageId}"`);
      }
      const dsIdx = page.dataSources.findIndex(d => d.name === action.name);
      if (dsIdx === -1) throw new Error(`applyAction: unknown dataSource "${action.name}"`);
      const removedDs = clone(page.dataSources[dsIdx]);
      page.dataSources.splice(dsIdx, 1);
      return {
        next,
        inverse: { type: "addDataSource", pageId: action.pageId, source: removedDs },
      };
    }

    // -----------------------------------------------------------------------
    case "setInitialPage": {
      const prev = next.navFlow.initialPage;
      next.navFlow.initialPage = action.pageId;
      return {
        next,
        inverse: { type: "setInitialPage", pageId: prev },
      };
    }

    // -----------------------------------------------------------------------
    case "addTransition": {
      next.navFlow.transitions.push(clone(action.transition));
      return {
        next,
        inverse: { type: "removeTransition", transitionId: action.transition.id },
      };
    }

    // -----------------------------------------------------------------------
    case "removeTransition": {
      const tIdx = next.navFlow.transitions.findIndex(t => t.id === action.transitionId);
      if (tIdx === -1) throw new Error(`applyAction: unknown transition "${action.transitionId}"`);
      const removed = clone(next.navFlow.transitions[tIdx]);
      next.navFlow.transitions.splice(tIdx, 1);
      return {
        next,
        inverse: { type: "addTransition", transition: removed },
      };
    }

    // -----------------------------------------------------------------------
    case "setGuard": {
      const navPage = next.navFlow.pages.find(p => p.id === action.pageId);
      if (!navPage) throw new Error(`applyAction: unknown page "${action.pageId}" in navFlow`);
      const prevGuard = navPage.guard ?? null;
      if (action.guard === null) {
        delete navPage.guard;
      } else {
        navPage.guard = action.guard;
      }
      return {
        next,
        inverse: { type: "setGuard", pageId: action.pageId, guard: prevGuard },
      };
    }

    // -----------------------------------------------------------------------
    case "updateToken": {
      const prev = getNestedValue(next.tokens, action.path);
      setNestedValue(next.tokens, action.path, action.value);
      return {
        next,
        inverse: { type: "updateToken", path: action.path, value: prev },
      };
    }

    // -----------------------------------------------------------------------
    case "addToken": {
      setNestedValue(next.tokens, action.path, action.value);
      return {
        next,
        inverse: { type: "removeToken", path: action.path },
      };
    }

    // -----------------------------------------------------------------------
    case "removeToken": {
      const prev = getNestedValue(next.tokens, action.path);
      deleteNestedValue(next.tokens, action.path);
      return {
        next,
        inverse: { type: "addToken", path: action.path, value: prev },
      };
    }

    // -----------------------------------------------------------------------
    case "renameToken": {
      const oldKey = action.oldPath.join(".");
      const newKey = action.newPath.join(".");

      // Move the token value
      const tokenValue = getNestedValue(next.tokens, action.oldPath);
      deleteNestedValue(next.tokens, action.oldPath);
      setNestedValue(next.tokens, action.newPath, tokenValue);

      // Cascade: rewrite all prop references in all page schemas
      for (const pageId of Object.keys(next.pageSchemas)) {
        rewriteTokenRefs(next.pageSchemas[pageId].root, oldKey, newKey);
      }

      return {
        next,
        inverse: {
          type: "renameToken",
          oldPath: action.newPath,
          newPath: action.oldPath,
        },
      };
    }

    // -----------------------------------------------------------------------
    case "replaceArtifacts": {
      const prior = clone(artifacts);
      return {
        next: clone(action.artifacts),
        inverse: { type: "replaceArtifacts", artifacts: prior },
      };
    }

    // -----------------------------------------------------------------------
    default: {
      const exhaustive: never = action;
      throw new Error(`applyAction: unknown action type "${(exhaustive as any).type}"`);
    }
  }
}
