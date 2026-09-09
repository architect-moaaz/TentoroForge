"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  useNodesState,
  useEdgesState,
  type ReactFlowInstance,
  type Node,
  type Edge,
  type Connection,
  type OnConnect,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { WorkflowNode } from "./nodes/WorkflowNode";
import { isBranchingNode } from "./branching";
import { ConditionalEdge } from "./edges/ConditionalEdge";
import { useWorkflowStore } from "@/stores/workflow";
import type {
  WorkflowNodeData,
  WorkflowNodeType,
  WorkflowEdgeData,
  WorkflowEdgeType,
  WorkflowNodeSerialized,
  WorkflowEdgeSerialized,
} from "@/types/workflow";

const nodeTypes = {
  trigger: WorkflowNode,
  action: WorkflowNode,
  condition: WorkflowNode,
  decision: WorkflowNode,
  wait: WorkflowNode,
  end: WorkflowNode,
  end_event: WorkflowNode,
  exclusive_gateway: WorkflowNode,
  parallel_gateway: WorkflowNode,
  fork: WorkflowNode,
  join: WorkflowNode,
  assignment: WorkflowNode,
  approval: WorkflowNode,
  task_pool: WorkflowNode,
  escalation: WorkflowNode,
  user_task: WorkflowNode,
  ai_classify: WorkflowNode,
  ai_extract: WorkflowNode,
  ai_decide: WorkflowNode,
  ai_generate: WorkflowNode,
};

const edgeTypes = {
  conditional: ConditionalEdge,
};

interface WorkflowCanvasProps {
  initialNodes?: WorkflowNodeSerialized[];
  initialEdges?: WorkflowEdgeSerialized[];
  onNodesChange?: (nodes: Node[]) => void;
  onEdgesChange?: (edges: Edge[]) => void;
  onNodeAdded?: (node: WorkflowNodeSerialized) => void;
  onEdgeAdded?: (edge: WorkflowEdgeSerialized) => void;
  activeNodeId?: string | null;
  layoutVersion?: number;
  /** Simulator overlay: node id → visual status. When set, nodes render that status. */
  nodeStatuses?: Record<string, "pending" | "active" | "done" | "failed">;
  /** Simulator overlay: edge ids that have been traversed (highlighted). */
  takenEdgeIds?: string[];
  /** When true, disables editing interactions (simulator is read-only). */
  readOnly?: boolean;
}

let nodeIdCounter = 1;
function generateNodeId() {
  return `node_${Date.now()}_${nodeIdCounter++}`;
}

export function WorkflowCanvas({
  initialNodes = [],
  initialEdges = [],
  onNodesChange: onNodesChangeProp,
  onEdgesChange: onEdgesChangeProp,
  onNodeAdded,
  onEdgeAdded,
  activeNodeId,
  layoutVersion,
  nodeStatuses,
  takenEdgeIds,
  readOnly,
}: WorkflowCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const reactFlowInstance = useRef<ReactFlowInstance | null>(null);
  const { setSelectedNodeId } = useWorkflowStore();

  // Convert serialized nodes to React Flow nodes
  const rfInitialNodes: Node[] = useMemo(
    () =>
      initialNodes.map((n) => ({
        id: n.id,
        type: n.data.nodeType,
        position: n.position,
        data: {
          ...n.data,
          status: activeNodeId === n.id ? "running" : n.data.status || "idle",
          // I1: only inject simStatus key in simulator mode; editor nodes get no simStatus key
          ...(nodeStatuses ? { simStatus: nodeStatuses[n.id] } : {}),
        },
        selected: false,
      })),
    [initialNodes, activeNodeId, nodeStatuses],
  );

  const rfInitialEdges: Edge[] = useMemo(
    () =>
      initialEdges.map((e) => {
        const taken = takenEdgeIds?.includes(e.id) ?? false;
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          ...(e.sourceHandle ? { sourceHandle: e.sourceHandle } : {}),
          ...(e.targetHandle ? { targetHandle: e.targetHandle } : {}),
          type: "conditional",
          data: e.data || { edgeType: "default" as WorkflowEdgeType },
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
          ...(taken ? { animated: true, style: { stroke: "#f59e0b", strokeWidth: 2 } } : {}),
        };
      }),
    [initialEdges, takenEdgeIds],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(rfInitialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(rfInitialEdges);

  // Re-apply positions when layout version changes (auto-layout triggered)
  useEffect(() => {
    if (layoutVersion && layoutVersion > 0) {
      setNodes(rfInitialNodes);
      setTimeout(() => reactFlowInstance.current?.fitView({ padding: 0.2 }), 50);
    }
  }, [layoutVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  // Adopt node DATA edits made in the Properties panel (label / config /
  // nodeType) onto the live canvas nodes. useNodesState seeds from
  // rfInitialNodes only ONCE, and no other effect re-synced it, so a panel
  // edit updated the parent (and thus Save) but the node on the canvas kept
  // its old label until a full remount. We merge by id, overlaying the parent
  // data while preserving the LIVE position/selection/status the canvas owns —
  // and return the same array reference when nothing changed so this never
  // fights an in-progress drag (position-only parent updates are a no-op here).
  useEffect(() => {
    if (nodeStatuses) return; // simulator mode manages node data via the status effect
    setNodes((cur) => {
      const byId = new Map(initialNodes.map((n) => [n.id, n]));
      let changed = false;
      const next = cur.map((n) => {
        const src = byId.get(n.id);
        if (!src) return n;
        const dataDiffers =
          n.type !== src.type ||
          n.data.label !== src.data.label ||
          JSON.stringify(n.data.config) !== JSON.stringify(src.data.config);
        if (!dataDiffers) return n;
        changed = true;
        return { ...n, type: src.type, data: { ...n.data, ...src.data, status: n.data.status } };
      });
      return changed ? next : cur;
    });
  }, [initialNodes, nodeStatuses, setNodes]);

  // C1: Sync simulator node statuses onto live nodes without disturbing positions.
  // Early-returns when nodeStatuses is undefined (editor mode) → zero effect on drag state.
  useEffect(() => {
    if (!nodeStatuses) return;
    setNodes((cur) =>
      cur.map((n) => ({ ...n, data: { ...n.data, simStatus: nodeStatuses[n.id] } })),
    );
  }, [nodeStatuses, setNodes]);

  // C1: Sync taken-edge highlight onto live edges.
  // Early-returns when takenEdgeIds is undefined (editor mode) → zero effect on editor edges.
  useEffect(() => {
    if (!takenEdgeIds) return;
    const taken = new Set(takenEdgeIds);
    setEdges((cur) =>
      cur.map((e) =>
        taken.has(e.id)
          ? { ...e, animated: true, style: { ...(e.style ?? {}), stroke: "#f59e0b", strokeWidth: 2 } }
          : { ...e, animated: false },
      ),
    );
  }, [takenEdgeIds, setEdges]);

  const onConnect: OnConnect = useCallback(
    (params: Connection) => {
      // Determine edge type based on source handle
      let edgeType: WorkflowEdgeType = "default";
      if (params.sourceHandle === "else") {
        edgeType = "else";
      } else {
        // Check if source is a condition/ai_decide node and this is the "then" path
        const sourceNode = nodes.find((n) => n.id === params.source);
        // A14-2: was a hardcoded three-type list that omitted exclusive_gateway.
        if (isBranchingNode(sourceNode?.type) && params.sourceHandle !== "else") {
          edgeType = "then";
        }
      }

      const newEdge: Edge = {
        ...params,
        id: `edge_${params.source}_${params.sourceHandle ?? "out"}_${params.target}`,
        type: "conditional",
        data: { edgeType } as WorkflowEdgeData,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      } as Edge;

      setEdges((eds) => addEdge(newEdge, eds));

      // Sync new edge to parent for save
      onEdgeAdded?.({
        id: newEdge.id!,
        source: params.source!,
        target: params.target!,
        sourceHandle: params.sourceHandle || undefined,
        targetHandle: params.targetHandle || undefined,
        data: { edgeType } as WorkflowEdgeData,
      });
    },
    [setEdges, nodes, onEdgeAdded],
  );

  // A user can drag from any handle to any handle — reject the connections that
  // produce an invalid graph so the editor never persists a misconfiguration:
  //   • self-loops (a node wired to itself)
  //   • edges INTO a trigger (a trigger is the entry point; it takes no input)
  //   • edges OUT of an `end`/terminal node (a terminal has no outgoing flow)
  //   • duplicate edges from the same source handle to the same target
  const isValidConnection = useCallback(
    (conn: Connection | Edge): boolean => {
      const source = (conn as Connection).source;
      const target = (conn as Connection).target;
      const sourceHandle = (conn as Connection).sourceHandle ?? null;
      if (!source || !target || source === target) return false;
      const src = nodes.find((n) => n.id === source);
      const tgt = nodes.find((n) => n.id === target);
      if (tgt?.type === "trigger") return false;
      if (src?.type === "end") return false;
      const dup = edges.some(
        (e) =>
          e.source === source &&
          e.target === target &&
          (e.sourceHandle ?? null) === sourceHandle,
      );
      if (dup) return false;
      return true;
    },
    [nodes, edges],
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

      const nodeType = event.dataTransfer.getData("application/workflow-node-type") as WorkflowNodeType;
      const nodeLabel = event.dataTransfer.getData("application/workflow-node-label");
      const configRaw = event.dataTransfer.getData("application/workflow-node-config");

      if (!nodeType) return;

      // Parse pre-configured settings from palette (e.g. actionType, trigger type)
      let defaultConfig: Record<string, unknown> = {};
      if (configRaw) {
        try {
          defaultConfig = JSON.parse(configRaw);
        } catch {
          // ignore parse errors
        }
      }

      // Use React Flow instance for proper zoom/pan handling
      const position = reactFlowInstance.current
        ? reactFlowInstance.current.screenToFlowPosition({
            x: event.clientX,
            y: event.clientY,
          })
        : { x: event.clientX - 80, y: event.clientY - 20 };

      const newNode: Node = {
        id: generateNodeId(),
        type: nodeType,
        position,
        data: {
          label: nodeLabel || nodeType,
          nodeType,
          config: { ...defaultConfig, nodeType },
          status: "idle",
        } satisfies WorkflowNodeData,
      };

      setNodes((nds) => [...nds, newNode]);

      // Sync new node to parent so properties panel can find it
      onNodeAdded?.({
        id: newNode.id,
        type: nodeType,
        position,
        data: newNode.data as WorkflowNodeData,
      });
    },
    [setNodes, onNodeAdded],
  );

  // Sync changes back to parent.
  //
  // A13-1/A13-2: these used to call ONLY React Flow's own state setter, so a
  // delete, drag or reconnect lived entirely inside the canvas and never
  // reached the object WorkflowPanel serialises. The node came back on reload
  // and `isDirty` was never set, so the button still read "Saved" — the user
  // was told their work was safe while it was being discarded. Adds were
  // already synced (onNodeAdded/onEdgeAdded), which is what made this a bug
  // rather than a design choice.
  //
  // The changes are applied to the CURRENT arrays here rather than read from
  // state afterwards: React state updates are async, so `nodes` inside this
  // callback is the pre-change value and would hand the parent a stale graph.
  const handleNodesChange = useCallback(
    (changes: Parameters<typeof onNodesChange>[0]) => {
      onNodesChange(changes);
      onNodesChangeProp?.(applyNodeChanges(changes, nodes));
    },
    [onNodesChange, onNodesChangeProp, nodes],
  );

  const handleEdgesChange = useCallback(
    (changes: Parameters<typeof onEdgesChange>[0]) => {
      onEdgesChange(changes);
      onEdgesChangeProp?.(applyEdgeChanges(changes, edges));
    },
    [onEdgesChange, onEdgesChangeProp, edges],
  );

  return (
    <div ref={reactFlowWrapper} className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={readOnly ? undefined : onConnect}
        isValidConnection={readOnly ? undefined : isValidConnection}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onDragOver={readOnly ? undefined : onDragOver}
        onDrop={readOnly ? undefined : onDrop}
        onInit={(instance) => { reactFlowInstance.current = instance; }}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          type: "conditional",
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
        }}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        elementsSelectable={true}
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
