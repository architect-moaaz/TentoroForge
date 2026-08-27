import type { WorkflowNodeSerialized, WorkflowEdgeSerialized } from "@/types/workflow";

const NODE_WIDTH = 280;
const NODE_HEIGHT = 100;

export type LayoutDirection = "TB" | "LR";

export async function layoutWorkflow(
  nodes: WorkflowNodeSerialized[],
  edges: WorkflowEdgeSerialized[],
  direction: LayoutDirection = "TB",
): Promise<WorkflowNodeSerialized[]> {
  // Dynamic import to avoid CJS/ESM interop issues with Turbopack
  const dagreModule = await import("dagre");
  const dagre = dagreModule.default ?? dagreModule;

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 80, ranksep: 140, marginx: 40, marginy: 40 });

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
