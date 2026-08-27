"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  MarkerType,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  type NodeMouseHandler,
  type OnConnect,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Plus, LayoutDashboard, FileText, ArrowRight, Trash2, GripVertical,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScreenNode } from "./ScreenNode";
import { useNavigationStore } from "@/stores/navigation";
import { useIREditorStore } from "@/stores/ir-editor";
import { generateFlowFromIR, flowToIRActions } from "@/lib/flow-generator";
import type { ScreenNodeSerialized, NavEdgeSerialized, NavLink } from "@/types/navigation";

const nodeTypes = { screen: ScreenNode };

interface FlowEditorProps {
  projectId: string;
}

export function FlowEditor({ projectId }: FlowEditorProps) {
  const ir = useIREditorStore((s) => s.ir);
  const {
    screens, edges: storeEdges, sidebarLinks,
    setScreens, setEdges, setSidebarLinks,
    selectedScreenId, setSelectedScreenId,
    setDefaultScreen,
  } = useNavigationStore();

  // Convert store data to React Flow format
  const rfNodes: Node[] = useMemo(
    () =>
      screens.map((s) => ({
        id: s.id,
        type: "screen",
        position: s.position,
        data: s.data,
        selected: s.id === selectedScreenId,
      })),
    [screens, selectedScreenId],
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      storeEdges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.data?.label || "",
        data: e.data || {},
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
        style: {
          stroke: e.data?.navType === "redirect" ? "#f59e0b" : "#94a3b8",
          strokeWidth: 1.5,
          strokeDasharray: e.data?.navType === "redirect" ? "6 3" : undefined,
        },
        animated: e.data?.navType === "redirect",
      })),
    [storeEdges],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(rfNodes);
  const [edges, setEdgesState, onEdgesChange] = useEdgesState(rfEdges);

  // Sync when store changes
  useEffect(() => { setNodes(rfNodes); }, [rfNodes, setNodes]);
  useEffect(() => { setEdgesState(rfEdges); }, [rfEdges, setEdgesState]);

  // --- Auto-generate flow from IR ---
  const handleAutoGenerate = useCallback(() => {
    if (!ir) return;
    const flow = generateFlowFromIR(ir as never);
    setScreens(flow.screens);
    setEdges(flow.edges);
    setSidebarLinks(flow.sidebarLinks);
    if (flow.defaultScreen) setDefaultScreen(flow.defaultScreen);
  }, [ir, setScreens, setEdges, setSidebarLinks, setDefaultScreen]);

  // Auto-generate on first load if no screens exist
  useEffect(() => {
    if (screens.length === 0 && ir && (ir as unknown as Record<string, unknown>).pages) {
      handleAutoGenerate();
    }
  }, [screens.length, ir, handleAutoGenerate]);

  // --- Connection creation ---
  const onConnect: OnConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const newEdge: NavEdgeSerialized = {
        id: `e-${Date.now()}`,
        source: connection.source,
        target: connection.target,
        data: { label: "navigate", navType: "link" },
      };
      setEdges([...storeEdges, newEdge]);
    },
    [storeEdges, setEdges],
  );

  // --- Node click ---
  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      setSelectedScreenId(node.id);
    },
    [setSelectedScreenId],
  );

  const onPaneClick = useCallback(() => {
    setSelectedScreenId(null);
  }, [setSelectedScreenId]);

  // --- Node position changes ---
  const onNodesChangeHandler = useCallback(
    (changes: Parameters<typeof onNodesChange>[0]) => {
      onNodesChange(changes);
      // Sync positions back to store
      const posChanges = changes.filter((c) => c.type === "position" && "position" in c && c.position);
      if (posChanges.length > 0) {
        const updated = screens.map((s) => {
          const change = posChanges.find((c) => "id" in c && c.id === s.id);
          if (change && "position" in change && change.position) {
            return { ...s, position: change.position };
          }
          return s;
        });
        setScreens(updated);
      }
    },
    [onNodesChange, screens, setScreens],
  );

  // --- DnD: Drop IR page onto canvas ---
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData("application/flow-page");
      if (!raw) return;

      let data: { pageId: string; route: string; title: string };
      try {
        data = JSON.parse(raw);
      } catch {
        return;
      }

      // Check if already exists
      if (screens.some((s) => s.id === data.pageId)) return;

      const reactFlowBounds = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - reactFlowBounds.left;
      const y = e.clientY - reactFlowBounds.top;

      const newScreen: ScreenNodeSerialized = {
        id: data.pageId,
        type: "screen",
        position: { x, y },
        data: {
          label: data.title,
          route: data.route,
          pageId: data.pageId,
          layout: "sidebar",
        },
      };

      setScreens([...screens, newScreen]);
    },
    [screens, setScreens],
  );

  // --- Delete selected edge ---
  const onEdgeClick = useCallback(
    (_event: React.MouseEvent, edge: Edge) => {
      // Double-click or click to select for deletion
      setEdges(storeEdges.filter((e) => e.id !== edge.id));
    },
    [storeEdges, setEdges],
  );

  // --- Get IR pages not yet on canvas ---
  const irPages = useMemo(() => {
    if (!ir) return [];
    const pageList = (ir as unknown as Record<string, unknown>).pages as Array<{ $id: string; route: string; title?: string }> | undefined;
    if (!pageList) return [];
    const onCanvas = new Set(screens.map((s) => s.id));
    return pageList.filter((p) => !onCanvas.has(p.$id));
  }, [ir, screens]);

  return (
    <div className="flex h-full">
      {/* Left: Page list for DnD */}
      <div className="w-52 shrink-0 border-r bg-background overflow-y-auto">
        <div className="p-2 border-b">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-muted-foreground">Pages</span>
            <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={handleAutoGenerate}>
              Auto Layout
            </Button>
          </div>
        </div>

        {/* Pages not yet on canvas — draggable */}
        {irPages.length > 0 && (
          <div className="p-2 space-y-1">
            <span className="text-[10px] font-medium text-muted-foreground uppercase">Drag to canvas</span>
            {irPages.map((page) => (
              <div
                key={page.$id}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData(
                    "application/flow-page",
                    JSON.stringify({ pageId: page.$id, route: page.route, title: page.title || page.$id }),
                  );
                  e.dataTransfer.effectAllowed = "copy";
                }}
                className="flex items-center gap-2 px-2 py-1.5 rounded text-xs cursor-grab hover:bg-accent border border-dashed border-muted"
              >
                <GripVertical className="h-3 w-3 text-muted-foreground" />
                <FileText className="h-3 w-3 text-muted-foreground" />
                <span className="truncate">{page.title || page.$id}</span>
              </div>
            ))}
          </div>
        )}

        {/* Sidebar menu — drag to reorder */}
        <div className="p-2 space-y-1 border-t">
          <span className="text-[10px] font-medium text-muted-foreground uppercase">Sidebar Menu</span>
          {sidebarLinks.map((link, i) => (
            <div
              key={link.id}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData("application/nav-reorder", JSON.stringify({ index: i }));
                e.dataTransfer.effectAllowed = "move";
              }}
              onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}
              onDrop={(e) => {
                e.preventDefault();
                const raw = e.dataTransfer.getData("application/nav-reorder");
                if (!raw) {
                  // Dropping a page onto the sidebar
                  const pageRaw = e.dataTransfer.getData("application/flow-page");
                  if (pageRaw) {
                    const page = JSON.parse(pageRaw);
                    const newLink: NavLink = {
                      id: `nav-${page.pageId}`,
                      label: page.title,
                      route: page.route,
                      icon: "file",
                      order: sidebarLinks.length,
                    };
                    setSidebarLinks([...sidebarLinks, newLink]);
                  }
                  return;
                }
                const { index: fromIndex } = JSON.parse(raw);
                const updated = [...sidebarLinks];
                const [moved] = updated.splice(fromIndex, 1);
                updated.splice(i, 0, moved);
                setSidebarLinks(updated.map((l, idx) => ({ ...l, order: idx })));
              }}
              className="flex items-center gap-2 px-2 py-1.5 rounded text-xs cursor-grab hover:bg-accent bg-muted/50"
            >
              <GripVertical className="h-3 w-3 text-muted-foreground" />
              <LayoutDashboard className="h-3 w-3 text-muted-foreground" />
              <span className="truncate flex-1">{link.label}</span>
              <button
                className="text-muted-foreground hover:text-destructive"
                onClick={() => setSidebarLinks(sidebarLinks.filter((l) => l.id !== link.id))}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}

          {/* Drop zone for adding pages to sidebar */}
          <div
            onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; }}
            onDrop={(e) => {
              e.preventDefault();
              const raw = e.dataTransfer.getData("application/flow-page");
              if (!raw) return;
              const page = JSON.parse(raw);
              if (sidebarLinks.some((l) => l.route === page.route)) return;
              const newLink: NavLink = {
                id: `nav-${page.pageId}`,
                label: page.title,
                route: page.route,
                icon: "file",
                order: sidebarLinks.length,
              };
              setSidebarLinks([...sidebarLinks, newLink]);
            }}
            className="flex items-center justify-center h-8 border-2 border-dashed border-muted rounded text-[10px] text-muted-foreground"
          >
            Drop page here to add
          </div>
        </div>
      </div>

      {/* Center: React Flow canvas */}
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChangeHandler}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onEdgeClick={onEdgeClick}
          onDragOver={onDragOver}
          onDrop={onDrop}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          defaultEdgeOptions={{
            markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
            style: { stroke: "#94a3b8", strokeWidth: 1.5 },
          }}
        >
          <Background gap={16} size={1} />
          <Controls />
          <MiniMap
            nodeStrokeWidth={3}
            pannable
            zoomable
            className="!bg-background"
          />
          <Panel position="top-right">
            <div className="flex gap-1">
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={handleAutoGenerate}>
                Regenerate Flow
              </Button>
            </div>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
}
