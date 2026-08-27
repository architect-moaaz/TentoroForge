"use client";

import { useState, useCallback, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Trash2,
  Save,
  Play,
  ArrowLeft,
  Loader2,
  LayoutGrid,
  FlaskConical,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, describeDetail } from "@/lib/api";
import { toast } from "sonner";
import { useSchemaChange } from "@/hooks/useSchemaChange";
import { useWorkflowStore } from "@/stores/workflow";
import { WorkflowCanvas } from "./WorkflowCanvas";
import { WorkflowSimulator } from "./simulator/WorkflowSimulator";
import { NodePalette } from "./NodePalette";
import { NodePropertiesPanel } from "./NodePropertiesPanel";
import { ProcessVariablesEditor } from "./ProcessVariablesEditor";
import type { ProcessVariable } from "@/types/workflow";
import type { AppModel } from "@/types/app-model";
import { layoutWorkflow, type LayoutDirection } from "./utils/workflow-layout";
import { normalizeWorkflowNodes } from "./utils/normalize-nodes";
import type {
  WorkflowDefinition,
  WorkflowListItem,
  WorkflowNodeSerialized,
  WorkflowEdgeSerialized,
  WorkflowNodeData,
  WorkflowNodeConfig,
} from "@/types/workflow";

interface WorkflowPanelProps {
  projectId: string;
  orgId?: string;
}

export function WorkflowPanel({ projectId, orgId }: WorkflowPanelProps) {
  const queryClient = useQueryClient();
  const {
    currentWorkflow,
    setCurrentWorkflow,
    selectedNodeId,
    setSelectedNodeId,
  } = useWorkflowStore();

  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [nodes, setNodes] = useState<WorkflowNodeSerialized[]>([]);
  const [edges, setEdges] = useState<WorkflowEdgeSerialized[]>([]);
  const [showSimulator, setShowSimulator] = useState(false);
  const [layoutDirection, setLayoutDirection] = useState<LayoutDirection>("TB");
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState<Date | null>(null);

  const { applyChange, isApplying: isApplyingHook, progress } = useSchemaChange();
  // A17-1: the button was driven by `isApplying` from useSchemaChange(), but
  // `applyChange` is never called from this component — so the flag was always
  // false. The button was never disabled, its spinner never rendered, and the
  // progress bar below was unreachable code: a slow, code-generating operation
  // ran with no feedback and no double-click guard. This local flag is set by
  // applyWorkflow itself, which is the operation actually running.
  const [isApplyingSelf, setIsApplying] = useState(false);
  const isApplying = isApplyingHook || isApplyingSelf;

  // Fetch workflow list
  const { data: workflows = [], isLoading } = useQuery({
    queryKey: ["project", projectId, "workflows"],
    queryFn: () =>
      api.get<WorkflowListItem[]>(`/api/projects/${projectId}/workflows`),
  });

  // Fetch app model for variable picker
  const { data: appModel } = useQuery({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () => api.get<AppModel>(`/api/projects/${projectId}/app-model`),
  });

  // Open a workflow for editing
  const openWorkflow = useCallback(
    async (id: string) => {
      const wf = await api.get<WorkflowDefinition>(
        `/api/projects/${projectId}/workflows/${id}`,
      );
      setCurrentWorkflow(wf);
      setEditName(wf.name);
      setEditDescription(wf.description || "");
      setNodes(normalizeWorkflowNodes(wf.definition.nodes));
      setEdges(wf.definition.edges || []);
      setSelectedNodeId(null);
      setIsDirty(false);
      setLastSaved(null);
      setShowSimulator(false);
    },
    [projectId, setCurrentWorkflow, setSelectedNodeId],
  );

  // Create a new workflow
  const createWorkflow = useCallback(() => {
    const id = `wf_${Date.now()}`;
    const newWf: WorkflowDefinition = {
      id,
      name: "New Workflow",
      definition: {
        trigger: { type: "manual" },
        steps: [],
        nodes: [
          {
            id: "trigger_1",
            type: "trigger",
            position: { x: 250, y: 50 },
            data: {
              label: "Start",
              nodeType: "trigger",
              config: {} as WorkflowNodeConfig,
              status: "idle",
            },
          },
        ],
        edges: [],
      },
    };
    setCurrentWorkflow(newWf);
    setEditName(newWf.name);
    setEditDescription("");
    setNodes(newWf.definition.nodes);
    setEdges(newWf.definition.edges);
    setSelectedNodeId(null);
  }, [setCurrentWorkflow, setSelectedNodeId]);

  // Save current workflow
  const saveWorkflow = useCallback(async () => {
    if (!currentWorkflow) return;
    setIsSaving(true);
    try {
      const payload = {
        id: currentWorkflow.id,
        name: editName,
        description: editDescription || undefined,
        processVariables: currentWorkflow.processVariables || [],
        definition: {
          ...currentWorkflow.definition,
          trigger: currentWorkflow.definition.trigger,
          // A6-1: this used to be `steps: []`. The POST is an upsert, so the
          // stored definition is REPLACED — which meant opening a generated
          // workflow and pressing Save silently destroyed the planner's steps.
          // `steps` is not vestigial: plan_validator.py validates
          // $.workflows[i].steps. The editor edits nodes/edges; it has no
          // business rewriting anything else, hence the spread.
          steps: currentWorkflow.definition.steps ?? [],
          nodes,
          edges,
        },
      };
      await api.post(`/api/projects/${projectId}/workflows`, payload);
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "workflows"],
      });
      setIsDirty(false);
      setLastSaved(new Date());
    } catch (err) {
      // A6-2: there was no catch here at all, so a failed save surfaced
      // NOTHING — the button just stayed on "Save*", which is indistinguishable
      // from not having pressed it. deleteWorkflow (below) already does this
      // correctly; save now matches it.
      //
      // isDirty is deliberately left TRUE: the edits are still unsaved, and
      // clearing it would tell the user their work is safe when it is not.
      toast.error(
        err instanceof Error ? `Save failed: ${err.message}` : "Save failed",
      );
      throw err;   // applyWorkflow awaits this — it must not proceed on a failed save
    } finally {
      setIsSaving(false);
    }
  }, [currentWorkflow, editName, editDescription, nodes, edges, projectId, queryClient]);

  // Delete workflow. Confirms first — the trash icon used to fire an
  // immediate irreversible delete with no dialog, which is exactly the
  // "destructive without confirmation" pattern the audit's UX pack flagged.
  const deleteWorkflow = useCallback(
    async (id: string, name?: string) => {
      const label = name ? `"${name}"` : "this workflow";
      if (!confirm(`Delete ${label}? This can't be undone.`)) return;
      try {
        await api.delete(`/api/projects/${projectId}/workflows/${id}`);
        toast.success("Workflow deleted");
        queryClient.invalidateQueries({
          queryKey: ["project", projectId, "workflows"],
        });
        if (currentWorkflow?.id === id) {
          setCurrentWorkflow(null);
        }
      } catch (err) {
        toast.error(
          err instanceof Error
            ? `Delete failed: ${err.message}`
            : "Delete failed",
        );
      }
    },
    [projectId, queryClient, currentWorkflow, setCurrentWorkflow],
  );

  // Apply workflow to generated app
  const applyWorkflow = useCallback(async () => {
    if (!currentWorkflow) return;
    // Save first. saveWorkflow now rethrows after toasting (A6-2), so an apply
    // can never run against edits that failed to persist — it would report
    // success for a workflow the server never received. The user already has
    // the "Save failed" toast, so this just stops here.
    try {
      await saveWorkflow();
    } catch {
      return;
    }
    // A17-1: the busy flag is set HERE, around the operation that actually
    // runs. `finally` covers every exit below — including the early returns on
    // an HTTP failure and on a stream error — so the button can never stick.
    setIsApplying(true);
    try {
    // Then apply via SSE
    const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
    const token =
      typeof window !== "undefined" ? localStorage.getItem("token") : null;

    const response = await fetch(
      `${API_BASE}/api/projects/${projectId}/workflows/${currentWorkflow.id}/apply`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      },
    );

    if (!response.ok) {
      // Silent-swallow used to make Apply look like a no-op — the button
      // fired, nothing happened, no error surfaced. Surface it now.
      let detail = "";
      try {
        const j = await response.json();
        // A9-1 again: apply uses a RAW fetch rather than the api client, so it
        // needs the same normalisation — a 422 here would otherwise toast
        // "[object Object]" exactly like the auth form did.
        detail = describeDetail(j?.error) || describeDetail(j?.detail) || "";
      } catch {
        detail = await response.text().catch(() => "");
      }
      toast.error(
        `Apply failed (${response.status})${detail ? `: ${detail}` : ""}`,
      );
      return;
    }

    const reader = response.body?.getReader();
    if (!reader) return;

    const decoder = new TextDecoder();
    let buffer = "";
    let streamError = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // A17-2: the stream used to be decoded, split and DISCARDED — the comment
      // read "Simply consume the SSE stream". `response.ok` only covers the
      // handshake, so a generation that failed HALFWAY completed silently and
      // refreshed the queries as if it had worked. Read the events instead.
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload || payload === "[DONE]") continue;
        try {
          const evt = JSON.parse(payload);
          if (evt?.error || evt?.status === "error" || evt?.type === "error") {
            streamError =
              describeDetail(evt.error) || evt.message || "Apply failed during generation";
          }
        } catch {
          // A non-JSON data line is progress chatter, not a failure.
        }
      }
    }

    if (streamError) {
      toast.error(`Apply failed: ${streamError}`);
      return;
    }

    toast.success("Workflow applied to the app");
    queryClient.invalidateQueries({
      queryKey: ["project", projectId],
    });
    } finally {
      setIsApplying(false);
    }
  }, [currentWorkflow, saveWorkflow, projectId, queryClient]);

  // Back to list
  const backToList = useCallback(() => {
    // A13-4: this used to discard unsaved work with no prompt. Combined with
    // A13-1 (canvas edits never even set dirty) a whole session could vanish in
    // one click. deleteWorkflow already confirms before an irreversible action;
    // leaving with unsaved edits is the same kind of loss.
    if (isDirty && !confirm("You have unsaved changes. Leave without saving?")) {
      return;
    }
    setCurrentWorkflow(null);
    setSelectedNodeId(null);
    setIsDirty(false);
  }, [isDirty, setCurrentWorkflow, setSelectedNodeId]);

  // A13-4 (second half): a tab close or reload bypasses backToList entirely,
  // so the in-app confirm alone does not protect the work.
  useEffect(() => {
    if (!isDirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [isDirty]);

  // Update node data
  const updateNodeData = useCallback(
    (nodeId: string, data: Partial<WorkflowNodeData>) => {
      setNodes((prev) =>
        prev.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, ...data } } : n,
        ),
      );
      setIsDirty(true);
    },
    [],
  );

  // Auto-layout using dagre
  const autoLayout = useCallback(async () => {
    const laid = await layoutWorkflow(nodes, edges, layoutDirection);
    setNodes(laid);
    setLayoutVersion((v) => v + 1);
    // A13-3: re-layout rewrites EVERY node position but never marked the
    // document dirty, so Save stayed disabled and the new layout was silently
    // thrown away on navigate-away. Positions are persisted state — moving them
    // is an edit.
    setIsDirty(true);
  }, [nodes, edges, layoutDirection]);

  const selectedNode = selectedNodeId
    ? nodes.find((n) => n.id === selectedNodeId)
    : null;

  // ──────────────────────────────────────────────────────
  // List view
  // ──────────────────────────────────────────────────────
  if (!currentWorkflow) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-sm font-semibold">Workflows</h2>
          <Button size="sm" onClick={createWorkflow}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            New Workflow
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : workflows.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-12 text-muted-foreground">
              <p className="text-sm">No workflows yet</p>
              <p className="text-xs">
                Create a workflow to automate business processes
              </p>
            </div>
          ) : (
            <div className="divide-y">
              {workflows.map((wf) => (
                <div
                  key={wf.id}
                  className="flex items-center justify-between px-4 py-3 hover:bg-muted/30 cursor-pointer"
                  onClick={() => openWorkflow(wf.id)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate">
                        {wf.name}
                      </span>
                      {wf.trigger_type && (
                        <Badge variant="secondary" className="text-[10px]">
                          {wf.trigger_type}
                        </Badge>
                      )}
                    </div>
                    {wf.description && (
                      <p className="text-xs text-muted-foreground truncate mt-0.5">
                        {wf.description}
                      </p>
                    )}
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      {wf.step_count} step{wf.step_count !== 1 ? "s" : ""}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteWorkflow(wf.id, wf.name);
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
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={backToList}>
          <ArrowLeft className="h-4 w-4" />
        </Button>

        <div className="flex flex-1 items-center gap-2">
          <div className="flex-1">
            <Input
              className="h-7 text-sm font-medium"
              value={editName}
              onChange={(e) => { setEditName(e.target.value); setIsDirty(true); }}
              placeholder="Workflow name"
            />
          </div>
          <div className="flex-1">
            <Input
              className="h-7 text-xs"
              value={editDescription}
              onChange={(e) => { setEditDescription(e.target.value); setIsDirty(true); }}
              placeholder="Description (optional)"
            />
          </div>
        </div>

        <div className="flex items-center gap-1">
          <Button size="sm" variant={isDirty ? "default" : "outline"} onClick={saveWorkflow} disabled={isSaving || !isDirty}>
            <Save className="mr-1 h-3.5 w-3.5" />
            {isSaving ? "Saving..." : isDirty ? "Save*" : "Saved"}
          </Button>
          <Button size="sm" variant="outline" onClick={autoLayout}>
            <LayoutGrid className="mr-1 h-3.5 w-3.5" />
            Layout
          </Button>
          <Select value={layoutDirection} onValueChange={(v) => setLayoutDirection(v as LayoutDirection)}>
            <SelectTrigger className="h-8 w-[52px] text-[10px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="TB">&darr; TB</SelectItem>
              <SelectItem value="LR">&rarr; LR</SelectItem>
            </SelectContent>
          </Select>
          <Button
            size="sm"
            onClick={applyWorkflow}
            disabled={isApplying}
          >
            {isApplying ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="mr-1 h-3.5 w-3.5" />
            )}
            Apply
          </Button>
          <Button
            size="sm"
            variant={showSimulator ? "default" : "outline"}
            onClick={async () => {
              if (!showSimulator) {
                // Auto-save so the backend runs exactly what's on canvas,
                // and a never-saved workflow (client id wf_<ts>) gets persisted first.
                try {
                  await saveWorkflow();
                } catch {
                  return; // surface via existing isSaving/saveWorkflow error path
                }
              }
              setShowSimulator((v) => !v);
            }}
          >
            <FlaskConical className="mr-1 h-3.5 w-3.5" />
            Simulate
          </Button>
        </div>
      </div>

      {/* Progress bar */}
      {isApplying && progress.status && (
        <div className="border-b bg-blue-50 px-4 py-1.5">
          <p className="text-xs text-blue-700">{progress.status}</p>
        </div>
      )}

      {/* Canvas area */}
      <div className="flex flex-1 overflow-hidden">
        {showSimulator ? (
          <WorkflowSimulator
            projectId={projectId}
            def={{
              ...currentWorkflow,
              name: editName,
              definition: {
                ...currentWorkflow.definition,
                nodes,
                edges,
              },
            }}
          />
        ) : (
          <>
            <NodePalette />
            <div className="flex-1">
              <WorkflowCanvas
                initialNodes={nodes}
                initialEdges={edges}
                onNodeAdded={(node) => { setNodes((prev) => [...prev, node]); setIsDirty(true); }}
                onEdgeAdded={(edge) => { setEdges((prev) => [...prev, edge]); setIsDirty(true); }}
                layoutVersion={layoutVersion}
              />
            </div>
            {selectedNode ? (
              <NodePropertiesPanel
                nodeData={selectedNode.data}
                nodeId={selectedNode.id}
                allNodes={nodes}
                allEdges={edges}
                appModel={appModel || null}
                projectId={projectId}
                orgId={orgId}
                workflowId={currentWorkflow?.id}
                processVariables={(currentWorkflow?.processVariables as ProcessVariable[]) || []}
                onUpdate={(data) => updateNodeData(selectedNode.id, data)}
                onClose={() => setSelectedNodeId(null)}
              />
            ) : (
              <div className="w-[320px] shrink-0 border-l bg-white overflow-y-auto p-3 space-y-4">
                <span className="text-xs font-semibold">Workflow Properties</span>
                <ProcessVariablesEditor
                  variables={(currentWorkflow?.processVariables as ProcessVariable[]) || []}
                  onChange={(variables) => {
                    if (currentWorkflow) {
                      setCurrentWorkflow({ ...currentWorkflow, processVariables: variables });
                      // Without this, adding/renaming/removing process
                      // variables kept the Save button disabled ("Saved")
                      // and the edits were silently lost on back-navigation
                      // or reload — every other mutation on this panel
                      // flags dirty, this one used to be the exception.
                      setIsDirty(true);
                    }
                  }}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
