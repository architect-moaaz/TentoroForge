"use client";

import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Trash2,
  ArrowLeft,
  Loader2,
  GitBranch,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { useDecisionStore } from "@/stores/decision";
import { DRDCanvas } from "./DRDCanvas";
import { DRDToolbar } from "./DRDToolbar";
import { DRDNodePanel } from "./DRDNodePanel";
import { layoutDRD, type LayoutDirection } from "./utils/drd-layout";
import type { DecisionGraphDefinition } from "@/types/decision";

interface DRDEditorPanelProps {
  projectId: string;
}

interface DRDListItem {
  id: string;
  name: string;
  node_count: number;
}

export function DRDEditorPanel({ projectId }: DRDEditorPanelProps) {
  const queryClient = useQueryClient();
  const {
    currentGraph,
    setCurrentGraph,
    selectedDRDNodeId,
    updateDRDNodes,
  } = useDecisionStore();

  const [editName, setEditName] = useState("");
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [isSaving, setIsSaving] = useState(false);

  // Fetch list of DRDs for this project
  const { data: drdList = [], isLoading } = useQuery({
    queryKey: ["project", projectId, "drds"],
    queryFn: () =>
      api.get<DRDListItem[]>(`/api/projects/${projectId}/drds`).catch(() => []),
  });

  // Open an existing DRD
  const openDRD = useCallback(
    async (id: string) => {
      try {
        const graph = await api.get<DecisionGraphDefinition>(
          `/api/projects/${projectId}/drds/${id}`,
        );
        setCurrentGraph(graph);
        setEditName(graph.name);
      } catch {
        // If the API doesn't exist yet, ignore
      }
    },
    [projectId, setCurrentGraph],
  );

  // Create a new DRD
  const createDRD = useCallback(() => {
    const id = `drd_${Date.now()}`;
    const newGraph: DecisionGraphDefinition = {
      id,
      name: "New Decision Requirement Diagram",
      nodes: [],
      edges: [],
      tables: {},
    };
    setCurrentGraph(newGraph);
    setEditName(newGraph.name);
  }, [setCurrentGraph]);

  // Save the current DRD
  const saveDRD = useCallback(async () => {
    if (!currentGraph) return;
    setIsSaving(true);
    try {
      const payload = { ...currentGraph, name: editName };
      await api.post(`/api/projects/${projectId}/drds`, payload);
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "drds"],
      });
    } catch {
      // API might not exist yet — that's OK, store is local
    } finally {
      setIsSaving(false);
    }
  }, [currentGraph, editName, projectId, queryClient]);

  // Delete a DRD
  const deleteDRD = useCallback(
    async (id: string) => {
      try {
        await api.delete(`/api/projects/${projectId}/drds/${id}`);
      } catch {
        // ignore
      }
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "drds"],
      });
      if (currentGraph?.id === id) {
        setCurrentGraph(null);
      }
    },
    [projectId, queryClient, currentGraph, setCurrentGraph],
  );

  // Auto-layout using dagre
  const autoLayout = useCallback(async () => {
    if (!currentGraph) return;
    const laid = await layoutDRD(currentGraph.nodes, currentGraph.edges, "TB");
    updateDRDNodes(laid);
    setLayoutVersion((v) => v + 1);
  }, [currentGraph, updateDRDNodes]);

  // Back to list
  const backToList = useCallback(() => {
    setCurrentGraph(null);
  }, [setCurrentGraph]);

  const selectedNode = selectedDRDNodeId
    ? currentGraph?.nodes.find((n) => n.id === selectedDRDNodeId)
    : null;

  // ──────────────────────────────────────────────────────
  // List view
  // ──────────────────────────────────────────────────────
  if (!currentGraph) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-sm font-semibold">
            Decision Requirement Diagrams
          </h2>
          <Button size="sm" onClick={createDRD}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            New DRD
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : drdList.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-12 text-muted-foreground">
              <GitBranch className="h-8 w-8" />
              <p className="text-sm">No DRDs yet</p>
              <p className="text-xs">
                Create a Decision Requirement Diagram to model complex decision
                logic
              </p>
              <Button variant="outline" size="sm" onClick={createDRD}>
                <Plus className="mr-1 h-3 w-3" />
                Create your first DRD
              </Button>
            </div>
          ) : (
            <div className="divide-y">
              {drdList.map((drd) => (
                <div
                  key={drd.id}
                  className="flex items-center justify-between px-4 py-3 hover:bg-muted/30 cursor-pointer"
                  onClick={() => openDRD(drd.id)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate">
                        {drd.name}
                      </span>
                      <Badge variant="secondary" className="text-[10px]">
                        {drd.node_count} node
                        {drd.node_count !== 1 ? "s" : ""}
                      </Badge>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteDRD(drd.id);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ──────────────────────────────────────────────────────
  // Editor view
  // ──────────────────────────────────────────────────────
  return (
    <div className="flex h-full flex-col">
      {/* Top toolbar */}
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={backToList}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>

        <div className="flex-1">
          <Input
            className="h-7 text-sm font-medium"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            placeholder="DRD name"
          />
        </div>

        <span className="text-[10px] text-muted-foreground whitespace-nowrap">
          {currentGraph.nodes.length} node
          {currentGraph.nodes.length !== 1 ? "s" : ""} ·{" "}
          {currentGraph.edges.length} edge
          {currentGraph.edges.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Canvas area */}
      <div className="flex flex-1 overflow-hidden">
        <DRDToolbar
          onAutoLayout={autoLayout}
          onSave={saveDRD}
          isSaving={isSaving}
        />
        <div className="flex-1">
          <DRDCanvas layoutVersion={layoutVersion} />
        </div>
        {selectedNode && <DRDNodePanel />}
      </div>
    </div>
  );
}
