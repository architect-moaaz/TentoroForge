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
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { DRDNode } from "./DRDNode";
import { useDecisionStore } from "@/stores/decision";
import type {
  DRDEdge,
  DRDEdgeType,
  DRDNodeType,
} from "@/types/decision";

const nodeTypes = {
  inputData: DRDNode,
  decision: DRDNode,
  knowledgeSource: DRDNode,
};

interface DRDCanvasProps {
  layoutVersion?: number;
}

export function DRDCanvas({ layoutVersion }: DRDCanvasProps) {
  const rfInstance = useRef<ReactFlowInstance | null>(null);
  const graph = useDecisionStore((s) => s.currentGraph);
  const setSelectedDRDNodeId = useDecisionStore((s) => s.setSelectedDRDNodeId);
  const addDRDEdge = useDecisionStore((s) => s.addDRDEdge);
  const updateDRDNode = useDecisionStore((s) => s.updateDRDNode);

  const rfNodes: Node[] = useMemo(
    () =>
      (graph?.nodes ?? []).map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: {
          label: n.label,
          drdType: n.type,
          decisionTableId: n.decisionTableId,
          variableName: n.variableName,
          variableType: n.variableType,
          url: n.url,
          description: n.description,
        },
      })),
    [graph?.nodes],
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      (graph?.edges ?? []).map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        style: e.type === "knowledge" ? { strokeDasharray: "5,5" } : {},
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
      })),
    [graph?.edges],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(rfNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(rfEdges);

  // Sync when graph changes externally (e.g. adding nodes from toolbar)
  useEffect(() => {
    setNodes(rfNodes);
  }, [rfNodes, setNodes]);

  useEffect(() => {
    setEdges(rfEdges);
  }, [rfEdges, setEdges]);

  // Re-fit view on layout version change (auto-layout triggered)
  useEffect(() => {
    if (layoutVersion && layoutVersion > 0) {
      setNodes(rfNodes);
      setTimeout(() => rfInstance.current?.fitView({ padding: 0.2 }), 50);
    }
  }, [layoutVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  // Determine edge type based on source node type
  const getEdgeType = useCallback(
    (sourceId: string): DRDEdgeType => {
      const sourceNode = graph?.nodes.find((n) => n.id === sourceId);
      if (sourceNode?.type === "knowledgeSource") return "knowledge";
      return "information";
    },
    [graph?.nodes],
  );

  const onConnect: OnConnect = useCallback(
    (params: Connection) => {
      const edgeType = getEdgeType(params.source!);
      const edgeId = `drd_edge_${params.source}_${params.target}`;

      const newEdge: Edge = {
        ...params,
        id: edgeId,
        style: edgeType === "knowledge" ? { strokeDasharray: "5,5" } : {},
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
      } as Edge;

      setEdges((eds) => addEdge(newEdge, eds));

      // Sync to store
      const newDRDEdge: DRDEdge = {
        id: edgeId,
        source: params.source!,
        target: params.target!,
        type: edgeType,
      };
      addDRDEdge(newDRDEdge);
    },
    [setEdges, getEdgeType, addDRDEdge],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedDRDNodeId(node.id);
    },
    [setSelectedDRDNodeId],
  );

  const onPaneClick = useCallback(() => {
    setSelectedDRDNodeId(null);
  }, [setSelectedDRDNodeId]);

  // Sync position changes back to store
  const onNodeDragStop = useCallback(
    (_: React.MouseEvent, node: Node) => {
      updateDRDNode(node.id, {
        position: { x: node.position.x, y: node.position.y },
      });
    },
    [updateDRDNode],
  );

  // Drag-and-drop from toolbar
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const nodeType = event.dataTransfer.getData(
        "application/drd-node-type",
      ) as DRDNodeType;
      if (!nodeType) return;

      const position = rfInstance.current
        ? rfInstance.current.screenToFlowPosition({
            x: event.clientX,
            y: event.clientY,
          })
        : { x: event.clientX - 80, y: event.clientY - 20 };

      const store = useDecisionStore.getState();
      const defaultLabel =
        nodeType === "inputData"
          ? "Input Data"
          : nodeType === "knowledgeSource"
            ? "Knowledge Source"
            : "Decision";

      store.addDRDNode({
        id: `drd_${nodeType}_${Date.now()}`,
        type: nodeType,
        label: defaultLabel,
        position,
      });
    },
    [],
  );

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onNodeDragStop={onNodeDragStop}
        onDragOver={onDragOver}
        onDrop={onDrop}
        onInit={(instance) => {
          rfInstance.current = instance;
        }}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
        }}
        deleteKeyCode={["Backspace", "Delete"]}
      >
        <Background />
        <Controls showInteractive={false} />
        <MiniMap
          nodeStrokeWidth={2}
          style={{ height: 80, width: 120 }}
          nodeColor={(node) => {
            switch (node.type) {
              case "inputData":
                return "#e0f2fe";
              case "decision":
                return "#e0e7ff";
              case "knowledgeSource":
                return "#fef3c7";
              default:
                return "#f1f5f9";
            }
          }}
        />
      </ReactFlow>
    </div>
  );
}
