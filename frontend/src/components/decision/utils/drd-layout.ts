import type { DRDNode, DRDEdge } from "@/types/decision";

const NODE_WIDTH = 160;
const NODE_HEIGHT = 60;

export type LayoutDirection = "TB" | "LR";

/** Auto-layout DRD nodes using dagre. */
export async function layoutDRD(
  nodes: DRDNode[],
  edges: DRDEdge[],
  direction: LayoutDirection = "TB",
): Promise<DRDNode[]> {
  // Dynamic import to avoid CJS/ESM interop issues with Turbopack
  const dagreModule = await import("dagre");
  const dagre = dagreModule.default ?? dagreModule;

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: direction,
    nodesep: 80,
    ranksep: 120,
    marginx: 40,
    marginy: 40,
  });

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  return nodes.map((node) => {
    const pos = g.node(node.id);
    return {
      ...node,
      position: {
        x: pos.x - NODE_WIDTH / 2,
        y: pos.y - NODE_HEIGHT / 2,
      },
    };
  });
}
