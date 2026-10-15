"use client";

import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Node as RFNode, Edge as RFEdge } from "@xyflow/react";
import {
  Plus,
  Trash2,
  Workflow,
  X,
  Play,
  ArrowLeft,
  Loader2,
  FlaskConical,
  Bomb,
  Radio,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { checkKeyOf, draftKeyOf } from "@/lib/agent-draft";
import { useAgentBuilderStore } from "@/stores/agent-builder";
import { AgentCanvas } from "./AgentCanvas";
import { AgentChecksBar } from "./AgentChecksBar";
import { AgentBlastPanel } from "./AgentBlastPanel";
import { AgentNodePalette } from "./AgentNodePalette";
import { AgentNodeProperties } from "./AgentNodeProperties";
import { AgentTemplateSelector } from "./AgentTemplateSelector";
import { AgentTestConsole } from "./AgentTestConsole";
import { AgentWatchPanel } from "./AgentWatchPanel";
import { useAgentWatch } from "./useAgentWatch";
import { nodeStates } from "@/lib/agent-watch";
import { applyFix, revertFix } from "@/lib/agent-blast";
import { AgentIOSchemaEditor } from "./config/AgentIOSchemaEditor";
import type {
  AgentDefinition,
  AgentFinding,
  AgentIOField,
  AgentListItem,
  AgentNodeSerialized,
  AgentEdgeSerialized,
  AgentNodeData,
  AgentTemplate,
} from "@/types/agent-builder";

/** An agent saves itself this long after the last change, so typing is not a save per key. */
const AUTOSAVE_MS = 1200;

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
  const [suggesting, setSuggesting] = useState(false);
  const [suggestError, setSuggestError] = useState<string | null>(null);
  // What is wrong with the agent as drawn, kept current while it is edited.
  const [findings, setFindings] = useState<AgentFinding[]>([]);
  const [appChecked, setAppChecked] = useState(true);
  const [confirmingApply, setConfirmingApply] = useState(false);
  // Find problems: bombs thrown at the agent as drawn, with fixes (it also holds the agent's saved tests).
  const [showBlast, setShowBlast] = useState(false);
  // The agent as last saved (see draftKeyOf), or null for one that was only just drawn and never saved.
  const [savedKey, setSavedKey] = useState<string | null>(null);
  // The agent as it was when opened or drawn (saved or not). "Touched" means the person has changed it since, and only
  // a touched agent saves itself: opening "New Agent" and leaving again leaves nothing behind.
  const [baseKey, setBaseKey] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "error" | "blocked">("idle");
  // A save the server refused after verifying the drawing: what is wrong, and whether it could be saved on purpose.
  const [blocked, setBlocked] = useState<{ kind: string; problems: AgentFinding[] } | null>(null);
  const [showTestConsole, setShowTestConsole] = useState(false);
  // Watch the running app's real chats live: the canvas lights up as they happen.
  const [showWatch, setShowWatch] = useState(false);
  const watch = useAgentWatch({ projectId, agentId: currentAgent?.id ?? "", agentName: editName, nodes, edges });

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
      const opened = draftKeyOf(agent.name, agent.description || "", agent.nodes || [], agent.edges || [], agent.config);
      setSavedKey(opened);
      setBaseKey(opened);
      setSaveState("idle");
      setSelectedNodeId(null);
      setShowTestConsole(false);
      setApplyStatus(null);
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
    setSavedKey(null);
    setBaseKey(draftKeyOf(newAgent.name, "", newAgent.nodes, newAgent.edges, newAgent.config));
    setSaveState("idle");
    setSelectedNodeId(null);
    setShowTestConsole(false);
    setApplyStatus(null);
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
      setSavedKey(null);
      setBaseKey(draftKeyOf(newAgent.name, newAgent.description || "", newAgent.nodes, newAgent.edges, newAgent.config));
      setSaveState("idle");
      setSelectedNodeId(null);
      setShowTestConsole(false);
      setApplyStatus(null);
    },
    [setCurrentAgent, setSelectedNodeId],
  );

  // An agent drawn from this app's own Blueprint (its tables, workflows, rules). Nothing is saved
  // until the person saves it; the same id every time, so one agent per app.
  const suggestFromApp = useCallback(async () => {
    setSuggesting(true);
    setSuggestError(null);
    try {
      const suggested = await api.post<AgentDefinition>(
        `/api/projects/${projectId}/agent-definitions/suggest`,
        {},
      );
      setCurrentAgent(suggested);
      setEditName(suggested.name);
      setEditDescription(suggested.description || "");
      setNodes(suggested.nodes);
      setEdges(suggested.edges);
      setSavedKey(null);
      setBaseKey(draftKeyOf(suggested.name, suggested.description || "", suggested.nodes, suggested.edges, suggested.config));
      setSaveState("idle");
      setSelectedNodeId(null);
      setShowTestConsole(false);
      setApplyStatus(null);
    } catch (e) {
      setSuggestError(e instanceof Error ? e.message : "Could not suggest an agent for this app.");
    } finally {
      setSuggesting(false);
    }
  }, [projectId, setCurrentAgent, setSelectedNodeId]);

  // Ask the platform what is wrong with the agent as drawn. Nothing is saved or installed.
  const runCheck = useCallback(async (): Promise<AgentFinding[]> => {
    if (!currentAgent) return [];
    const res = await api.post<{ findings?: AgentFinding[]; appChecked?: boolean }>(
      `/api/projects/${projectId}/agent-definitions/check`,
      {
        id: currentAgent.id,
        name: editName,
        description: editDescription || undefined,
        nodes,
        edges,
        config: currentAgent.config,
      },
    );
    const list = Array.isArray(res?.findings) ? res.findings : [];
    setFindings(list);
    setAppChecked(res?.appChecked !== false);
    return list;
  }, [currentAgent, editName, editDescription, nodes, edges, projectId]);

  // Re-check a moment after the drawing stops changing. Keyed on what the check READS (not on
  // selection or box positions, which change on every click and drag).
  const checkKey = useMemo(() => checkKeyOf(currentAgent?.id, nodes, edges), [currentAgent?.id, nodes, edges]);
  useEffect(() => {
    if (!currentAgent) {
      setFindings([]);
      setConfirmingApply(false);
      return;
    }
    const timer = setTimeout(() => {
      runCheck().catch(() => {
        /* a failed check is not a problem with the agent: the bar keeps what it had */
      });
    }, 800);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkKey]);

  // Which boxes the chat being watched is working on right now.
  const liveStates = useMemo(() => {
    const run = watch.state.selected ? watch.state.runs[watch.state.selected] : undefined;
    return run ? nodeStates(run, watch.state.map) : {};
  }, [watch.state]);

  // Boxes with something wrong, for the canvas: the worst thing said about each.
  const problems = useMemo(() => {
    const out: Record<string, "error" | "warning"> = {};
    for (const f of findings) {
      if (!f.nodeId || f.severity === "info") continue;
      if (f.severity === "error" || !out[f.nodeId]) out[f.nodeId] = f.severity;
    }
    return out;
  }, [findings]);

  // Save current agent. The server verifies the drawing first and refuses a corrupt one outright; `force` is the builder
  // saying "save it anyway" about problems that are not corruption (Apply does, since it asks its own question).
  const saveAgent = useCallback(async (force = false) => {
    if (!currentAgent) return;
    const payload = {
      id: currentAgent.id,
      name: editName,
      description: editDescription || undefined,
      nodes,
      edges,
      config: currentAgent.config,
    };
    await api.post(`/api/projects/${projectId}/agent-definitions${force ? "?force=true" : ""}`, payload);
    setSavedKey(draftKeyOf(editName, editDescription, nodes, edges, currentAgent.config));
    queryClient.invalidateQueries({
      queryKey: ["project", projectId, "agent-definitions"],
    });
  }, [currentAgent, editName, editDescription, nodes, edges, projectId, queryClient]);

  // What the agent is now, what was last saved, and what it was when opened. A change that is not saved yet is saved by
  // itself a moment later (there is no Save button), but only once the person has changed something.
  const draftKey = useMemo(
    () => (currentAgent ? draftKeyOf(editName, editDescription, nodes, edges, currentAgent.config) : ""),
    [currentAgent, editName, editDescription, nodes, edges],
  );
  const agentUnsaved = !!currentAgent && savedKey !== draftKey;
  const touched = !!currentAgent && baseKey !== draftKey;
  const needsSave = agentUnsaved && touched;

  // A failed save is said in the status bar, in words. The message is kept so a later good save can take it away again.
  const saveFailure = useRef<string | null>(null);
  const autoSave = useCallback(async (force = false) => {
    setSaveState("saving");
    try {
      await saveAgent(force);
      setSaveState("idle");
      setBlocked(null);
      const earlier = saveFailure.current;
      saveFailure.current = null;
      if (earlier) setApplyStatus((now) => (now === earlier ? null : now));
    } catch (e) {
      // The server verified the drawing and said no (HTTP 422 with the problems): that is not a failure of saving, it is
      // a drawing that is not right yet. It says what and where, and the last saved version stays as it was.
      const refused = (e as { status?: number; body?: { detail?: { kind?: string; problems?: AgentFinding[] } } })?.body;
      if ((e as { status?: number })?.status === 422 && Array.isArray(refused?.detail?.problems)) {
        const problems = refused!.detail!.problems!;
        setBlocked({ kind: refused!.detail!.kind ?? "problems", problems });
        setSaveState("blocked");
        setFindings((now) => (now.length ? now : problems));
        return;
      }
      const message = `Error: ${e instanceof Error ? e.message : String(e)}`;
      saveFailure.current = message;
      setApplyStatus(message);
      setSaveState("error");
    }
  }, [saveAgent]);

  // No retry loop: after a failure it waits for the next change (or the person pressing the status) to try again.
  useEffect(() => {
    if (!needsSave || isApplying) return;
    const timer = setTimeout(() => void autoSave(), AUTOSAVE_MS);
    return () => clearTimeout(timer);
  }, [needsSave, draftKey, isApplying, autoSave]);

  // Leaving the builder (going back, or the page closing the panel) must not lose a change made a moment ago.
  const leaving = useRef<() => void>(() => {});
  leaving.current = () => {
    if (needsSave && saveState !== "blocked") void saveAgent().catch(() => {});
  };
  useEffect(() => () => leaving.current(), []);

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
  const applyAgent = useCallback(async (force = false) => {
    if (!currentAgent) return;
    setConfirmingApply(false);
    try {
      await saveAgent(true);
    } catch (e) {
      // Reported where the person is looking; thrown from a click handler it
      // surfaced as an uncaught "Runtime ApiError" overlay with no way forward.
      setApplyStatus(`Error: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }

    // BEFORE anything is installed: a problem that will stop a tool working is shown and asked about,
    // not discovered afterwards in a log. A check that itself fails never blocks Apply.
    if (!force) {
      try {
        const list = await runCheck();
        if (list.some((f) => f.severity === "error")) {
          setConfirmingApply(true);
          setApplyStatus(null);
          return;
        }
      } catch {
        /* apply as before */
      }
    }

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
    if (needsSave && saveState === "blocked") {
      // refused by the verification: leaving would lose them, so ask
      if (typeof window !== "undefined" && !window.confirm("Your changes have problems, so they are not saved. Leave without saving them?")) return;
    } else if (needsSave) {
      void saveAgent().catch(() => {});
    }
    saveFailure.current = null;
    setSaveState("idle");
    setBlocked(null);
    setCurrentAgent(null);
    setSelectedNodeId(null);
    setShowTestConsole(false);
    setApplyStatus(null);
  }, [needsSave, saveState, saveAgent, setCurrentAgent, setSelectedNodeId]);

  // The diagram page: the drawing, with the components to build it. The other pages (Test, Find problems, Watch live)
  // are closed to get back to it.
  const showDiagram = useCallback(() => {
    setShowTestConsole(false);
    setShowBlast(false);
    setShowWatch(false);
  }, []);
  const onDiagramPage = !showTestConsole && !showBlast && !showWatch;

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
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={suggestFromApp} disabled={suggesting}>
              {suggesting ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="mr-1 h-3.5 w-3.5" />
              )}
              Suggest from my app
            </Button>
            <Button size="sm" onClick={createAgent}>
              <Plus className="mr-1 h-3.5 w-3.5" />
              New Agent
            </Button>
          </div>
        </div>
        {suggestError && (
          <div role="alert" className="border-b bg-destructive/10 px-4 py-2 text-xs text-destructive">
            {suggestError}
          </div>
        )}

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
              <AgentTemplateSelector
                onSelect={createFromTemplate}
                onSuggest={suggestFromApp}
                suggesting={suggesting}
              />
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
          {saveState === "error" ? (
            <button type="button" className="mr-1 text-xs text-red-700 underline" onClick={() => void autoSave()} data-testid="save-state">
              Not saved. Try again
            </button>
          ) : saveState === "blocked" && blocked ? (
            <span className="mr-1 flex items-center gap-1.5 text-xs text-red-700" data-testid="save-state" title={blocked.problems[0]?.message}>
              Not saved: {blocked.problems.length === 1 ? "1 problem" : `${blocked.problems.length} problems`} to fix
              {blocked.kind !== "corrupt" && (
                <button type="button" className="underline" onClick={() => void autoSave(true)} data-testid="save-anyway">
                  Save anyway
                </button>
              )}
            </span>
          ) : saveState === "saving" ? (
            <span className="mr-1 text-xs text-muted-foreground" data-testid="save-state">
              Saving…
            </span>
          ) : needsSave ? (
            <span className="mr-1 text-xs text-amber-700" data-testid="save-state">
              Unsaved changes
            </span>
          ) : (
            <span className="mr-1 text-xs text-muted-foreground" data-testid="save-state">
              {savedKey !== null ? "Saved" : "Saves as you edit"}
            </span>
          )}
          <Button
            size="sm"
            variant={onDiagramPage ? "default" : "outline"}
            aria-pressed={onDiagramPage}
            onClick={showDiagram}
          >
            <Workflow className="mr-1 h-3.5 w-3.5" />
            Diagram
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setShowBlast(false);
              setShowTestConsole(!showTestConsole);
            }}
          >
            <FlaskConical className="mr-1 h-3.5 w-3.5" />
            Test
          </Button>
          <Button
            size="sm"
            variant={showBlast ? "default" : "outline"}
            aria-pressed={showBlast}
            onClick={() => {
              setShowTestConsole(false);
              setShowBlast(!showBlast);
            }}
          >
            <Bomb className="mr-1 h-3.5 w-3.5" />
            Find problems
          </Button>
          <Button
            size="sm"
            variant={showWatch ? "default" : "outline"}
            aria-pressed={showWatch}
            onClick={() => {
              setShowTestConsole(false);
              setShowBlast(false);
              setShowWatch(!showWatch);
            }}
          >
            <Radio className="mr-1 h-3.5 w-3.5" />
            Watch live
            {watch.link === "connected" && <span className="ml-1.5 inline-block h-2 w-2 rounded-full bg-green-500" aria-label="connected" />}
          </Button>
          <Button
            size="sm"
            onClick={() => applyAgent(false)}
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
      {applyStatus && (
        <div
          role="status"
          className={
            /^(error|failed)/i.test(applyStatus)
              ? "flex items-start gap-2 border-b bg-red-50 px-4 py-1.5"
              : "flex items-start gap-2 border-b bg-blue-50 px-4 py-1.5"
          }
        >
          <p
            className={
              /^(error|failed)/i.test(applyStatus)
                ? "flex-1 text-xs text-red-700"
                : "flex-1 text-xs text-blue-700"
            }
          >
            {applyStatus}
          </p>
          {/* a message that has been read can be put away */}
          <button
            type="button"
            aria-label="Dismiss this message"
            title="Dismiss"
            className="mt-0.5 shrink-0 rounded p-0.5 text-slate-500 hover:bg-black/5 hover:text-slate-800"
            onClick={() => setApplyStatus(null)}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <AgentChecksBar
        findings={findings}
        appChecked={appChecked}
        confirming={confirmingApply}
        onSelectNode={(id) => setSelectedNodeId(id)}
        onApplyAnyway={() => applyAgent(true)}
        onCancel={() => setConfirmingApply(false)}
      />

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
        {onDiagramPage && <AgentNodePalette />}
        <div className="flex-1">
          {showBlast ? (
            <AgentBlastPanel
              projectId={projectId}
              agentId={currentAgent.id}
              graph={{
                id: currentAgent.id,
                name: editName,
                description: editDescription || undefined,
                nodes,
                edges,
                config: currentAgent.config,
              }}
              onApplyFix={(fix) => setNodes((current) => applyFix(current, fix))}
              onRevertFix={(fix) => setNodes((current) => revertFix(current, fix))}
              agentUnsaved={saveState === "error"}
              onSaveAgent={() => autoSave()}
            />
          ) : showTestConsole ? (
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
              problems={problems}
              liveStates={liveStates}
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
        {showWatch && !showTestConsole && !showBlast && (
          <AgentWatchPanel
            state={watch.state}
            link={watch.link}
            reason={watch.reason}
            suggestedUrl={watch.suggestedUrl}
            projectId={projectId}
            onConnect={watch.connect}
            onDisconnect={watch.disconnect}
            onSelect={watch.select}
            onFollow={watch.follow}
          />
        )}
        {selectedNode && !showTestConsole && !showWatch && (
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
