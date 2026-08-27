"use client";

import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Node as RFNode, Edge as RFEdge } from "@xyflow/react";
import {
  Plus,
  Trash2,
  Save,
  Play,
  ArrowLeft,
  Loader2,
  FlaskConical,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { useAgentBuilderStore } from "@/stores/agent-builder";
import { AgentCanvas } from "./AgentCanvas";
import { AgentNodePalette } from "./AgentNodePalette";
import { AgentNodeProperties } from "./AgentNodeProperties";
import { AgentTemplateSelector } from "./AgentTemplateSelector";
import { AgentTestConsole } from "./AgentTestConsole";
import { AgentIOSchemaEditor } from "./config/AgentIOSchemaEditor";
import type {
  AgentDefinition,
  AgentIOField,
  AgentListItem,
  AgentNodeSerialized,
  AgentEdgeSerialized,
  AgentNodeData,
  AgentTemplate,
} from "@/types/agent-builder";

interface AgentBuilderPanelProps {
  projectId: string;
  orgId?: string;
}

export function AgentBuilderPanel({ projectId, orgId }: AgentBuilderPanelProps) {
  const queryClient = useQueryClient();
  const {
    currentAgent,
    setCurrentAgent,
    selectedNodeId,
    setSelectedNodeId,
  } = useAgentBuilderStore();

  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [nodes, setNodes] = useState<AgentNodeSerialized[]>([]);
  const [edges, setEdges] = useState<AgentEdgeSerialized[]>([]);
  const [isApplying, setIsApplying] = useState(false);
  const [applyStatus, setApplyStatus] = useState<string | null>(null);
  const [showTestConsole, setShowTestConsole] = useState(false);

  // Fetch agent list
  const { data: agents = [], isLoading } = useQuery({
    queryKey: ["project", projectId, "agent-definitions"],
    queryFn: () =>
      api.get<AgentListItem[]>(`/api/projects/${projectId}/agent-definitions`),
  });

  // Open an agent for editing
  const openAgent = useCallback(
    async (id: string) => {
      const agent = await api.get<AgentDefinition>(
        `/api/projects/${projectId}/agent-definitions/${id}`,
      );
      setCurrentAgent(agent);
      setEditName(agent.name);
      setEditDescription(agent.description || "");
      setNodes(agent.nodes || []);
      setEdges(agent.edges || []);
      setSelectedNodeId(null);
      setShowTestConsole(false);
    },
    [projectId, setCurrentAgent, setSelectedNodeId],
  );

  // Create a new blank agent
  const createAgent = useCallback(() => {
    const id = `agent_${Date.now()}`;
    const newAgent: AgentDefinition = {
      id,
      name: "New Agent",
      nodes: [
        {
          id: "sp_entry",
          type: "system_prompt",
          position: { x: 250, y: 120 },
          data: {
            label: "System Prompt",
            nodeType: "system_prompt",
            config: {
              prompt: "You are a helpful assistant.",
              is_entry_point: true,
            },
          },
        },
      ],
      edges: [],
    };
    setCurrentAgent(newAgent);
    setEditName(newAgent.name);
    setEditDescription("");
    setNodes(newAgent.nodes);
    setEdges(newAgent.edges);
    setSelectedNodeId(null);
    setShowTestConsole(false);
  }, [setCurrentAgent, setSelectedNodeId]);

  // Create from template
  const createFromTemplate = useCallback(
    (template: AgentTemplate) => {
      const id = `agent_${Date.now()}`;
      const newAgent: AgentDefinition = {
        id,
        name: template.name,
        description: template.description,
        nodes: template.nodes,
        edges: template.edges,
      };
      setCurrentAgent(newAgent);
      setEditName(newAgent.name);
      setEditDescription(newAgent.description || "");
      setNodes(newAgent.nodes);
      setEdges(newAgent.edges);
      setSelectedNodeId(null);
      setShowTestConsole(false);
    },
    [setCurrentAgent, setSelectedNodeId],
  );

  // Save current agent
  const saveAgent = useCallback(async () => {
    if (!currentAgent) return;
    const payload = {
      id: currentAgent.id,
      name: editName,
      description: editDescription || undefined,
      nodes,
      edges,
      config: currentAgent.config,
    };
    await api.post(`/api/projects/${projectId}/agent-definitions`, payload);
    queryClient.invalidateQueries({
      queryKey: ["project", projectId, "agent-definitions"],
    });
  }, [currentAgent, editName, editDescription, nodes, edges, projectId, queryClient]);

  // Delete agent
  const deleteAgent = useCallback(
    async (id: string) => {
      await api.delete(`/api/projects/${projectId}/agent-definitions/${id}`);
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "agent-definitions"],
      });
      if (currentAgent?.id === id) {
        setCurrentAgent(null);
      }
    },
    [projectId, queryClient, currentAgent, setCurrentAgent],
  );

  // Apply agent to generated app
  const applyAgent = useCallback(async () => {
    if (!currentAgent) return;
    await saveAgent();

    setIsApplying(true);
    setApplyStatus("Starting...");

    const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
    const token =
      typeof window !== "undefined" ? localStorage.getItem("token") : null;

    try {
      const response = await fetch(
        `${API_BASE}/api/projects/${projectId}/agent-definitions/${currentAgent.id}/apply`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        },
      );

      if (!response.ok) {
        setApplyStatus("Failed to apply");
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:") && currentEvent) {
            try {
              const data = JSON.parse(line.slice(5).trim());
              if (currentEvent === "status") {
                setApplyStatus(data.message || null);
              } else if (currentEvent === "complete") {
                setApplyStatus("Applied successfully!");
              } else if (currentEvent === "error") {
                setApplyStatus(`Error: ${data.message}`);
              }
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }

      queryClient.invalidateQueries({
        queryKey: ["project", projectId],
      });
    } finally {
      setIsApplying(false);
    }
  }, [currentAgent, saveAgent, projectId, queryClient]);

  // Back to list
  const backToList = useCallback(() => {
    setCurrentAgent(null);
    setSelectedNodeId(null);
    setShowTestConsole(false);
  }, [setCurrentAgent, setSelectedNodeId]);

  // Update node data
  const updateNodeData = useCallback(
    (nodeId: string, data: Partial<AgentNodeData>) => {
      setNodes((prev) =>
        prev.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, ...data } } : n,
        ),
      );
    },
    [],
  );

  const selectedNode = selectedNodeId
    ? nodes.find((n) => n.id === selectedNodeId)
    : null;

  // ──────────────────────────────────────────────────────
  // List view
  // ──────────────────────────────────────────────────────
  if (!currentAgent) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-sm font-semibold">AI Agents</h2>
          <Button size="sm" onClick={createAgent}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            New Agent
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : agents.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-4 py-12 px-4">
              <div className="text-center text-muted-foreground">
                <p className="text-sm">No agents yet</p>
                <p className="text-xs mt-1">
                  Create a custom AI agent or start from a template
                </p>
              </div>
              <AgentTemplateSelector onSelect={createFromTemplate} />
            </div>
          ) : (
            <div className="divide-y">
              {agents.map((agent) => (
                <div
                  key={agent.id}
                  className="flex items-center justify-between px-4 py-3 hover:bg-muted/30 cursor-pointer"
                  onClick={() => openAgent(agent.id)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate">
                        {agent.name}
                      </span>
                      <Badge variant="secondary" className="text-[10px]">
                        {agent.node_count} node{agent.node_count !== 1 ? "s" : ""}
                      </Badge>
                    </div>
                    {agent.description && (
                      <p className="text-xs text-muted-foreground truncate mt-0.5">
                        {agent.description}
                      </p>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteAgent(agent.id);
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
              onChange={(e) => setEditName(e.target.value)}
              placeholder="Agent name"
            />
          </div>
          <div className="flex-1">
            <Input
              className="h-7 text-xs"
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
              placeholder="Description (optional)"
            />
          </div>
        </div>

        <div className="flex items-center gap-1">
          <Button size="sm" variant="outline" onClick={saveAgent}>
            <Save className="mr-1 h-3.5 w-3.5" />
            Save
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setShowTestConsole(!showTestConsole)}
          >
            <FlaskConical className="mr-1 h-3.5 w-3.5" />
            Test
          </Button>
          <Button
            size="sm"
            onClick={applyAgent}
            disabled={isApplying}
          >
            {isApplying ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="mr-1 h-3.5 w-3.5" />
            )}
            Apply
          </Button>
        </div>
      </div>

      {/* Progress bar */}
      {isApplying && applyStatus && (
        <div className="border-b bg-blue-50 px-4 py-1.5">
          <p className="text-xs text-blue-700">{applyStatus}</p>
        </div>
      )}

      {/* Agent-level I/O contract — what a caller must supply + what the agent
          returns. Collapsible so it stays out of the way when authoring nodes. */}
      <AgentIOSchemaEditor
        inputs={currentAgent.config?.input_schema ?? []}
        outputs={currentAgent.config?.output_schema ?? []}
        onChange={({ inputs, outputs }: { inputs: AgentIOField[]; outputs: AgentIOField[] }) =>
          setCurrentAgent({
            ...currentAgent,
            config: {
              ...(currentAgent.config ?? {}),
              input_schema: inputs,
              output_schema: outputs,
            },
          })
        }
      />

      {/* Canvas area */}
      <div className="flex flex-1 overflow-hidden">
        <AgentNodePalette />
        <div className="flex-1">
          {showTestConsole ? (
            <AgentTestConsole
              projectId={projectId}
              agentId={currentAgent.id}
              agentName={editName}
              nodes={nodes}
            />
          ) : (
            <AgentCanvas
              initialNodes={nodes}
              initialEdges={edges}
              onNodesChange={(rf: RFNode[]) =>
                setNodes(
                  rf.map((n) => ({
                    id: n.id,
                    type: (n.data as AgentNodeData).nodeType,
                    position: n.position,
                    data: n.data as AgentNodeData,
                  })),
                )
              }
              onEdgesChange={(rf: RFEdge[]) =>
                setEdges(
                  rf.map((e) => ({
                    id: e.id,
                    source: e.source,
                    target: e.target,
                    sourceHandle: e.sourceHandle ?? undefined,
                    data: e.data as AgentEdgeSerialized["data"] | undefined,
                  })),
                )
              }
            />
          )}
        </div>
        {selectedNode && !showTestConsole && (
          <AgentNodeProperties
            nodeData={selectedNode.data}
            nodeId={selectedNode.id}
            onUpdate={(data) => updateNodeData(selectedNode.id, data)}
            onClose={() => setSelectedNodeId(null)}
            projectId={projectId}
            orgId={orgId}
          />
        )}
      </div>
    </div>
  );
}
