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
  type ReactFlowInstance,
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
import { edgeLook, nodeRing, type NodeState } from "@/lib/agent-watch";
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

// Settings handed to React Flow are constants, not objects made again on every render: React Flow compares them by
// identity, so a fresh object each time made it redo its internal work (and the minimap redraw) on every mouse move
// of a drag.
const PRO_OPTIONS = { hideAttribution: true } as const;
const DEFAULT_EDGE_OPTIONS = { markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 } };
const MINIMAP_STYLE = { height: 80, width: 120 } as const;

interface AgentCanvasProps {
  initialNodes?: AgentNodeSerialized[];
  initialEdges?: AgentEdgeSerialized[];
  onNodesChange?: (nodes: Node[]) => void;
  onEdgesChange?: (edges: Edge[]) => void;
  /** Boxes with something wrong, by node id: they are drawn with a red or amber ring. */
  problems?: Record<string, "error" | "warning">;
  /** While watching a live chat: which boxes are working (pulsing), done (green), failed (red) or holding (amber).
   *  The arrows between them move while either end is working. Drawn, never stored. */
  liveStates?: Record<string, NodeState>;
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
  liveStates,
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
    // A box that is being dragged moves on the canvas alone. Reporting every move made the whole page render several
    // times for each mouse move (it re-read every box's settings each time), so dragging crawled on a real agent. The
    // drop is reported: when the drag ends the box's `dragging` goes off, and this runs once with the final position.
    if (nodes.some((n) => n.dragging)) return;
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
      // The same object is the same settings (the canvas reports a box's `data` as it holds it): only two different
      // objects are worth the cost of comparing as text.
      if (data && data !== n.data && JSON.stringify(data) !== JSON.stringify(n.data)) {
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
      const sourceNode = nodesRef.current.find((n) => n.id === params.source);
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
    // read through a ref, not listed: listed, `onConnect` was a new function for every mouse move of a drag
    [setEdges],
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

  // The canvas's own handle on the drawing (zoom, pan), given once it is ready.
  const flowRef = useRef<ReactFlowInstance | null>(null);
  const onInit = useCallback((instance: ReactFlowInstance) => {
    flowRef.current = instance;
  }, []);

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

      // Where the pointer is in the DRAWING, not on the screen: once the diagram is zoomed or moved, screen and drawing
      // differ, and the box landed far from where it was dropped. A box is about 160 by 40, centred on the pointer.
      const flow = flowRef.current;
      let position: { x: number; y: number };
      if (flow) {
        const at = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
        position = { x: at.x - 80, y: at.y - 20 };
      } else {
        const reactFlowBounds = reactFlowWrapper.current?.getBoundingClientRect();
        if (!reactFlowBounds) return;
        position = { x: event.clientX - reactFlowBounds.left - 80, y: event.clientY - reactFlowBounds.top - 20 };
      }

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
  const shownNodes = useMemo(() => {
    const live = liveStates && Object.keys(liveStates).length > 0;
    if (!live && !(problems && Object.keys(problems).length)) return nodes;
    return nodes.map((n) => {
      // What a chat is doing to a box outranks a warning about it.
      const ring = nodeRing(liveStates?.[n.id]);
      if (ring) return { ...n, className: ring };
      if (problems?.[n.id]) {
        return {
          ...n,
          className:
            problems[n.id] === "error"
              ? "[&>div]:!ring-2 [&>div]:!ring-red-500 [&>div]:!ring-offset-1"
              : "[&>div]:!ring-2 [&>div]:!ring-amber-400 [&>div]:!ring-offset-1",
        };
      }
      return n;
    });
  }, [nodes, problems, liveStates]);

  const shownEdges = useMemo(() => {
    if (!liveStates || Object.keys(liveStates).length === 0) return edges;
    return edges.map((e) => {
      const look = edgeLook(liveStates[e.source], liveStates[e.target]);
      if (!look.animated && !look.stroke) return e;
      return { ...e, animated: look.animated, style: { ...(e.style ?? {}), stroke: look.stroke, strokeWidth: look.width } };
    });
  }, [edges, liveStates]);

  return (
    <div ref={reactFlowWrapper} className="h-full w-full">
      <ReactFlow
        nodes={shownNodes}
        edges={shownEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onDragOver={onDragOver}
        onDrop={onDrop}
        onInit={onInit}
        nodeTypes={nodeTypes}
        fitView
        proOptions={PRO_OPTIONS}
        defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
      >
        <Background />
        <Controls showInteractive={false} />
        <MiniMap nodeStrokeWidth={2} style={MINIMAP_STYLE} />
      </ReactFlow>
    </div>
  );
}
