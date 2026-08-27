import type { TableModel, RelationModel } from "@/types/app-model";

interface LayoutNode {
  id: string;
  x: number;
  y: number;
}

const NODE_WIDTH = 280;
const NODE_GAP_X = 320;
const NODE_GAP_Y = 280;

/**
 * Build an adjacency list from table relations.
 */
function buildAdjacency(tables: TableModel[]): Map<string, Set<string>> {
  const adj = new Map<string, Set<string>>();
  for (const t of tables) {
    adj.set(t.name, new Set());
  }
  for (const t of tables) {
    for (const rel of t.relations ?? []) {
      adj.get(t.name)?.add(rel.target);
    }
    // Also check foreign key references in columns
    for (const col of t.columns) {
      if (col.references) {
        adj.get(t.name)?.add(col.references.table);
      }
    }
  }
  return adj;
}

/**
 * Topological sort with cycle handling.
 * Returns layers of table names for left-to-right layout.
 */
function topologicalLayers(
  tables: TableModel[],
  adj: Map<string, Set<string>>,
): string[][] {
  const inDegree = new Map<string, number>();
  const tableNames = tables.map((t) => t.name);

  for (const name of tableNames) {
    inDegree.set(name, 0);
  }

  for (const [, targets] of adj) {
    for (const target of targets) {
      if (inDegree.has(target)) {
        inDegree.set(target, (inDegree.get(target) || 0) + 1);
      }
    }
  }

  const layers: string[][] = [];
  const remaining = new Set(tableNames);

  while (remaining.size > 0) {
    // Find nodes with in-degree 0 (among remaining)
    const layer: string[] = [];
    for (const name of remaining) {
      if ((inDegree.get(name) || 0) <= 0) {
        layer.push(name);
      }
    }

    // If no zero-in-degree nodes, break cycle by taking one arbitrarily
    if (layer.length === 0) {
      const first = remaining.values().next().value;
      if (first) layer.push(first);
    }

    for (const name of layer) {
      remaining.delete(name);
      for (const target of adj.get(name) ?? []) {
        if (inDegree.has(target)) {
          inDegree.set(target, (inDegree.get(target) || 0) - 1);
        }
      }
    }

    layers.push(layer);
  }

  return layers;
}

/**
 * Compute positions for all tables using topological layering.
 */
export function layoutTables(tables: TableModel[]): LayoutNode[] {
  if (tables.length === 0) return [];

  const adj = buildAdjacency(tables);
  const layers = topologicalLayers(tables, adj);
  const nodes: LayoutNode[] = [];

  for (let layerIdx = 0; layerIdx < layers.length; layerIdx++) {
    const layer = layers[layerIdx];
    for (let nodeIdx = 0; nodeIdx < layer.length; nodeIdx++) {
      nodes.push({
        id: layer[nodeIdx],
        x: layerIdx * NODE_GAP_X,
        y: nodeIdx * NODE_GAP_Y,
      });
    }
  }

  return nodes;
}
