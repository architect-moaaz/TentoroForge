"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  type OnConnect,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { SystemPromptNode } from "./nodes/SystemPromptNode";
import { ToolNode } from "./nodes/ToolNode";
import { GuardrailNode } from "./nodes/GuardrailNode";
import { MemoryNode } from "./nodes/MemoryNode";
import { HumanHandoffNode } from "./nodes/HumanHandoffNode";
import { RouterNode } from "./nodes/RouterNode";
import { useAgentBuilderStore } from "@/stores/agent-builder";
import type {
  AgentNodeData,
  AgentNodeType,
  AgentEdgeData,
  AgentEdgeType,
  AgentNodeSerialized,
  AgentEdgeSerialized,
} from "@/types/agent-builder";

const nodeTypes = {
  system_prompt: SystemPromptNode,
  tool: ToolNode,
  guardrail: GuardrailNode,
  memory: MemoryNode,
  human_handoff: HumanHandoffNode,
  router: RouterNode,
};

interface AgentCanvasProps {
  initialNodes?: AgentNodeSerialized[];
  initialEdges?: AgentEdgeSerialized[];
  onNodesChange?: (nodes: Node[]) => void;
  onEdgesChange?: (edges: Edge[]) => void;
  /** Boxes with something wrong, by node id: they are drawn with a red or amber ring. */
  problems?: Record<string, "error" | "warning">;
}

let nodeIdCounter = 1;
function generateNodeId() {
  return `agent_node_${Date.now()}_${nodeIdCounter++}`;
}

export function AgentCanvas({
  initialNodes = [],
  initialEdges = [],
  onNodesChange: onNodesChangeProp,
  onEdgesChange: onEdgesChangeProp,
  problems,
}: AgentCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const { setSelectedNodeId } = useAgentBuilderStore();

  const rfInitialNodes: Node[] = useMemo(
    () =>
      initialNodes.map((n) => ({
        id: n.id,
        type: n.data.nodeType,
        position: n.position,
        data: n.data,
        selected: false,
      })),
    [initialNodes],
  );

  const rfInitialEdges: Edge[] = useMemo(
    () =>
      initialEdges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle,
        data: e.data || { edgeType: "default" as AgentEdgeType },
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      })),
    [initialEdges],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(rfInitialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(rfInitialEdges);

  // Sync canvas → parent. React Flow's useNodesState/useEdgesState hold
  // internal state; without this bridge, drop / delete / connect / move
  // never reach the parent, so the parent's `nodes.find(selectedId)` always
  // returns undefined and the Properties panel never opens. Same for saves —
  // the parent would persist stale state.
  //
  // THE HANDLERS ARE READ THROUGH REFS, NOT LISTED AS DEPENDENCIES. The panel
  // passes them inline, so they are new functions on every render of the panel.
  // Listed here, every report re-rendered the panel, which made a new handler,
  // which re-ran the effect, which reported again — "Maximum update depth
  // exceeded" the moment an agent was opened. What should trigger a report is the
  // canvas's own state changing, and nothing else.
  const onNodesChangeRef = useRef(onNodesChangeProp);
  const onEdgesChangeRef = useRef(onEdgesChangeProp);
  onNodesChangeRef.current = onNodesChangeProp;
  onEdgesChangeRef.current = onEdgesChangeProp;
  useEffect(() => {
    onNodesChangeRef.current?.(nodes);
  }, [nodes]);
  useEffect(() => {
    onEdgesChangeRef.current?.(edges);
  }, [edges]);

  // Sync parent → canvas, for what the canvas does not own: a node's DATA. The
  // Properties side form edits the parent's copy (label, prompt, tool config);
  // React Flow seeded its own state once from `initialNodes` and never looks
  // again, so the card kept showing the old value — and the next drag reported
  // the canvas's stale copy back to the parent, silently undoing the edit.
  //
  // Only `data` of nodes present on BOTH sides is adopted, and only when it
  // differs. Positions, selection, and which nodes exist stay the canvas's: those
  // are what the report above sends the other way, and adopting them too would
  // have the two sides overwriting each other. After an adoption the canvas holds
  // the parent's object, so the report it triggers comes back equal and this
  // effect then finds nothing to change.
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  useEffect(() => {
    const fromParent = new Map(initialNodes.map((n) => [n.id, n.data]));
    let changed = false;
    const next = nodesRef.current.map((n) => {
      const data = fromParent.get(n.id);
      if (data && JSON.stringify(data) !== JSON.stringify(n.data)) {
        changed = true;
        return { ...n, data };
      }
      return n;
    });
    if (changed) setNodes(next);
  }, [initialNodes, setNodes]);

  const onConnect: OnConnect = useCallback(
    (params: Connection) => {
      let edgeType: AgentEdgeType = "default";

      // Router nodes may have named output handles for routes
      const sourceNode = nodes.find((n) => n.id === params.source);
      if (sourceNode?.type === "router" && params.sourceHandle) {
        edgeType = "route";
      }

      const newEdge: Edge = {
        ...params,
        id: `edge_${params.source}_${params.target}_${Date.now()}`,
        data: { edgeType } as AgentEdgeData,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      } as Edge;

      setEdges((eds) => addEdge(newEdge, eds));
    },
    [setEdges, nodes],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNodeId(node.id);
    },
    [setSelectedNodeId],
  );

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, [setSelectedNodeId]);

  // Drag-and-drop from palette
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const nodeType = event.dataTransfer.getData("application/agent-node-type") as AgentNodeType;
      const nodeLabel = event.dataTransfer.getData("application/agent-node-label");

      if (!nodeType) return;

      const reactFlowBounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!reactFlowBounds) return;

      const position = {
        x: event.clientX - reactFlowBounds.left - 80,
        y: event.clientY - reactFlowBounds.top - 20,
      };

      const newNode: Node = {
        id: generateNodeId(),
        type: nodeType,
        position,
        data: {
          label: nodeLabel || nodeType,
          nodeType,
          config: {},
        } satisfies AgentNodeData,
      };

      setNodes((nds) => [...nds, newNode]);
    },
    [setNodes],
  );

  // Drawn, not stored: a mark is derived from the latest checks each render, so it never goes into the
  // canvas's own state (which is reported back to the parent and saved).
  const shownNodes = useMemo(
    () =>
      problems && Object.keys(problems).length
        ? nodes.map((n) =>
            problems[n.id]
              ? {
                  ...n,
                  className:
                    problems[n.id] === "error"
                      ? "[&>div]:!ring-2 [&>div]:!ring-red-500 [&>div]:!ring-offset-1"
                      : "[&>div]:!ring-2 [&>div]:!ring-amber-400 [&>div]:!ring-offset-1",
                }
              : n,
          )
        : nodes,
    [nodes, problems],
  );

  return (
    <div ref={reactFlowWrapper} className="h-full w-full">
      <ReactFlow
        nodes={shownNodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onDragOver={onDragOver}
        onDrop={onDrop}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
        }}
      >
        <Background />
        <Controls showInteractive={false} />
        <MiniMap
          nodeStrokeWidth={2}
          style={{ height: 80, width: 120 }}
        />
      </ReactFlow>
    </div>
  );
}
