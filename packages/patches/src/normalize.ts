import type { Artifacts, SchemaNode, PageSchema } from "./types";

/**
 * Deep alphabetical sort of keys at every dict layer.
 * Preserves array order — only objects get key-sorted.
 */
function sortKeys<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map(sortKeys) as unknown as T;
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      out[key] = sortKeys((value as Record<string, unknown>)[key]);
    }
    return out as unknown as T;
  }
  return value;
}

/**
 * Normalise a single schema node. Order is:
 *   id, type, visibleIf, props, slots, children
 * children stays in source order. props + slots get key-sorted.
 */
function normalizeNode(n: SchemaNode): SchemaNode {
  const out: SchemaNode = { id: n.id, type: n.type };
  if (n.visibleIf !== undefined) (out as any).visibleIf = n.visibleIf;
  if (n.props) (out as any).props = sortKeys(n.props);
  if (n.slots) {
    const sorted: Record<string, SchemaNode[]> = {};
    for (const k of Object.keys(n.slots).sort()) {
      sorted[k] = n.slots[k].map(normalizeNode);
    }
    (out as any).slots = sorted;
  }
  if (n.children) (out as any).children = n.children.map(normalizeNode);
  return out;
}

function normalizePage(p: PageSchema): PageSchema {
  const out: PageSchema = {
    schemaVersion: p.schemaVersion,
    id: p.id,
    root: normalizeNode(p.root),
  };
  if (p.route !== undefined) (out as any).route = p.route;
  if (p.layout !== undefined) (out as any).layout = p.layout;
  if (p.meta !== undefined) (out as any).meta = sortKeys(p.meta);
  if (p.dataSources !== undefined && p.dataSources.length > 0) {
    (out as any).dataSources = p.dataSources;  // order is semantic — preserve
  }
  return out;
}

/**
 * Canonical normalisation for the three artifacts.
 * Two patchers producing the same logical state emit byte-identical
 * JSON after going through this function.
 */
export function normalize(a: Artifacts): Artifacts {
  const sortedPageIds = Object.keys(a.pageSchemas).sort();
  const pageSchemas: Record<string, PageSchema> = {};
  for (const id of sortedPageIds) {
    pageSchemas[id] = normalizePage(a.pageSchemas[id]);
  }

  const sortedNavPages = [...(a.navFlow?.pages ?? [])]
    .sort((x: any, y: any) => x.id.localeCompare(y.id));
  const sortedTransitions = [...(a.navFlow?.transitions ?? [])]
    .sort((x: any, y: any) => x.id.localeCompare(y.id));

  const navFlow = {
    ...(a.navFlow ?? { version: "1.0" as const, initialPage: "" }),
    pages: sortedNavPages,
    transitions: sortedTransitions,
    guards: sortKeys((a.navFlow as any)?.guards ?? {}),
  };

  const tokens = sortKeys(a.tokens ?? {} as any);

  return { pageSchemas, navFlow: navFlow as any, tokens };
}
