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
  type Node,
  type Edge,
  type NodeChange,
  type EdgeChange,
  type Connection,
  type OnConnect,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { ScreenNode } from "./ScreenNode";
import { useNavigationStore } from "@/stores/navigation";
import type { ScreenNodeSerialized, NavEdgeSerialized, ScreenNodeData } from "@/types/navigation";

const nodeTypes = {
  screen: ScreenNode,
};

interface NavigationEditorProps {
  initialScreens?: ScreenNodeSerialized[];
  initialEdges?: NavEdgeSerialized[];
  // BUG-011/012: lift canvas state up so the toolbar's "Add Screen" reflects on
  // the canvas AND canvas edits reach the store that Save serializes. Without
  // these, ReactFlow's local state and the Zustand store silently diverged.
  onScreensChange?: (screens: ScreenNodeSerialized[]) => void;
  onEdgesChange?: (edges: NavEdgeSerialized[]) => void;
}

let nodeIdCounter = 1;
function generateScreenId() {
  return `screen_${Date.now()}_${nodeIdCounter++}`;
}

function nodesToScreens(nodes: Node[]): ScreenNodeSerialized[] {
  return nodes.map((n) => ({
    id: n.id,
    type: "screen",
    position: n.position,
    data: n.data as ScreenNodeData,
  }));
}

function rfEdgesToSerialized(edges: Edge[]): NavEdgeSerialized[] {
  return edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    data: (e.data || {}) as NavEdgeSerialized["data"],
  }));
}

function sameIdSet(a: { id: string }[], b: { id: string }[]): boolean {
  if (a.length !== b.length) return false;
  const bIds = new Set(b.map((x) => x.id));
  return a.every((x) => bIds.has(x.id));
}

export function NavigationEditor({
  initialScreens = [],
  initialEdges = [],
  onScreensChange,
  onEdgesChange: onEdgesChangeProp,
}: NavigationEditorProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const { setSelectedScreenId } = useNavigationStore();

  const rfNodes: Node[] = useMemo(
    () =>
      initialScreens.map((s) => ({
        id: s.id,
        type: "screen",
        position: s.position,
        data: s.data,
        selected: false,
      })),
    [initialScreens],
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      initialEdges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        data: e.data || {},
        label: e.data?.label || "",
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
        style: { stroke: "#94a3b8", strokeWidth: 1.5 },
      })),
    [initialEdges],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(rfNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(rfEdges);

  // BUG-011 (store → canvas): reconcile nodes when the store's screen SET
  // changes (e.g. the toolbar's "Add Screen" or a delete). Only re-seed on an
  // id-set change — existing nodes are reused as-is so live positions/selection
  // survive; nodes removed from the store drop off. This is why adding a screen
  // used to require a tab switch (which remounted and re-seeded).
  useEffect(() => {
    setNodes((cur) => {
      if (sameIdSet(cur, initialScreens)) return cur;
      const byId = new Map(cur.map((n) => [n.id, n]));
      return initialScreens.map(
        (s) =>
          byId.get(s.id) ?? {
            id: s.id,
            type: "screen",
            position: s.position,
            data: s.data,
            selected: false,
          },
      );
    });
  }, [initialScreens, setNodes]);

  useEffect(() => {
    setEdges((cur) => {
      if (sameIdSet(cur, initialEdges)) return cur;
      const byId = new Map(cur.map((e) => [e.id, e]));
      return initialEdges.map(
        (e) =>
          byId.get(e.id) ?? {
            id: e.id,
            source: e.source,
            target: e.target,
            data: e.data || {},
            label: e.data?.label || "",
            markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
            style: { stroke: "#94a3b8", strokeWidth: 1.5 },
          },
      );
    });
  }, [initialEdges, setEdges]);

  // BUG-012 (canvas → store): sync canvas edits back to the store ONLY on
  // discrete user events (drop-add, connect, drag-END, delete) — never from a
  // generic effect on `nodes`. A generic effect fires with the stale (pre-
  // reconcile) node list one render after the store→canvas reconcile schedules
  // its setNodes, clobbering the store back to empty and oscillating the canvas
  // to 0. Computing the next list from the change here keeps it in phase.
  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      onNodesChange(changes);
      if (!onScreensChange) return;
      const structural = changes.some(
        (c) =>
          c.type === "remove" ||
          (c.type === "position" && c.dragging === false),
      );
      if (structural) {
        onScreensChange(nodesToScreens(applyNodeChanges(changes, nodes)));
      }
    },
    [onNodesChange, nodes, onScreensChange],
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      onEdgesChange(changes);
      if (!onEdgesChangeProp) return;
      if (changes.some((c) => c.type === "remove")) {
        onEdgesChangeProp(rfEdgesToSerialized(applyEdgeChanges(changes, edges)));
      }
    },
    [onEdgesChange, edges, onEdgesChangeProp],
  );

  const onConnect: OnConnect = useCallback(
    (params: Connection) => {
      const newEdge: Edge = {
        ...params,
        id: `edge_${params.source}_${params.target}`,
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
        style: { stroke: "#94a3b8", strokeWidth: 1.5 },
      } as Edge;
      const next = addEdge(newEdge, edges);
      setEdges(next);
      onEdgesChangeProp?.(rfEdgesToSerialized(next));
    },
    [edges, setEdges, onEdgesChangeProp],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedScreenId(node.id);
    },
    [setSelectedScreenId],
  );

  const onPaneClick = useCallback(() => {
    setSelectedScreenId(null);
  }, [setSelectedScreenId]);

  // Drop new screen from palette
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const label = event.dataTransfer.getData("application/screen-label");
      if (!label) return;

      const bounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!bounds) return;

      const position = {
        x: event.clientX - bounds.left - 80,
        y: event.clientY - bounds.top - 20,
      };

      const newNode: Node = {
        id: generateScreenId(),
        type: "screen",
        position,
        data: {
          label,
          route: `/${label.toLowerCase().replace(/\s+/g, "-")}`,
          layout: "sidebar",
        } satisfies ScreenNodeData,
      };

      const next = [...nodes, newNode];
      setNodes(next);
      onScreensChange?.(nodesToScreens(next));
    },
    [nodes, setNodes, onScreensChange],
  );

  return (
    <div ref={reactFlowWrapper} className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        onDragOver={onDragOver}
        onDrop={onDrop}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
          style: { stroke: "#94a3b8", strokeWidth: 1.5 },
        }}
      >
        <Background />
        <Controls showInteractive={false} />
        <MiniMap nodeStrokeWidth={2} style={{ height: 60, width: 100 }} />
      </ReactFlow>
    </div>
  );
}
