"use client";
import { useEffect, useMemo, useRef } from "react";
import { WorkflowCanvas } from "@/components/workflow/WorkflowCanvas";
import { TriggerInputForm } from "./TriggerInputForm";
import { TaskInputPanel } from "./TaskInputPanel";
import { useWorkflowSim, isTimerTask } from "@/stores/workflow-sim";
import { realSimApi } from "@/lib/workflow-sim/sim-api";
import { computeTakenEdges } from "@/lib/workflow-sim/node-status";
import type { NodeVisualStatus } from "@/lib/workflow-sim/types";
import type { WorkflowDefinition } from "@/types/workflow";

const POLL_MS = 800;
const REVEAL_MS = 250;

export interface WorkflowSimulatorProps {
  projectId: string;
  def: WorkflowDefinition;
}
export function WorkflowSimulator({ projectId, def }: WorkflowSimulatorProps) {
  const api = useMemo(() => realSimApi(projectId), [projectId]);
  const s = useWorkflowSim();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const revealRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Reset when switching workflows.
  useEffect(() => { useWorkflowSim.getState().reset(); }, [def.id]);

  // Poll while running/waiting.
  useEffect(() => {
    const running = s.phase === "running" || s.phase === "awaitingInput";
    if (running && !pollRef.current) pollRef.current = setInterval(() => useWorkflowSim.getState().poll(api), POLL_MS);
    if (!running && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [s.phase, api]);

  // Drain the reveal queue on a steady cadence (staggered greying).
  useEffect(() => {
    if (!revealRef.current) revealRef.current = setInterval(() => useWorkflowSim.getState().revealNext(), REVEAL_MS);
    return () => { if (revealRef.current) { clearInterval(revealRef.current); revealRef.current = null; } };
  }, []);

  // Auto fast-forward timer tasks (after they surface as activeTask).
  useEffect(() => {
    if (s.phase === "awaitingInput" && s.activeTask && isTimerTask(s.activeTask)) {
      void useWorkflowSim.getState().fastForwardTimer(api);
    }
  }, [s.phase, s.activeTask, api]);

  // Once a run starts, dim every not-yet-reached node by seeding "pending",
  // then overlay the store's done/active/failed statuses on top.
  const displayStatuses = useMemo(() => {
    if (s.phase === "idle") return {} as Record<string, NodeVisualStatus>;
    const base: Record<string, NodeVisualStatus> = {};
    for (const n of def.definition.nodes) base[n.id] = "pending";
    return { ...base, ...s.nodeStatuses };
  }, [s.phase, s.nodeStatuses, def.definition.nodes]);

  const takenEdges = useMemo(
    () => computeTakenEdges(s.nodeStatuses, def.definition.edges),
    [s.nodeStatuses, def.definition.edges],
  );
  const human = s.phase === "awaitingInput" && s.activeTask && !isTimerTask(s.activeTask);

  return (
    <div className="flex flex-1 min-w-0 w-full flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-2 border-b text-sm">
        <span className="font-medium">{def.name}</span>
        <button className="bg-white border rounded px-2 py-1" onClick={async () => { await useWorkflowSim.getState().cancel(api); useWorkflowSim.getState().reset(); }}>↻ Reset</button>
        <span className="ml-auto text-xs px-2 py-0.5 rounded-full bg-gray-100">{s.phase}{s.error ? ` — ${s.error}` : ""}</span>
      </div>
      <div className="flex flex-1 min-h-0">
        <div className="flex-1 min-w-0">
          <WorkflowCanvas
            initialNodes={def.definition.nodes}
            initialEdges={def.definition.edges}
            nodeStatuses={displayStatuses}
            takenEdgeIds={takenEdges}
            activeNodeId={s.activeTask?.node_id ?? null}
            readOnly
          />
        </div>
        <div className="w-72 border-l p-3 overflow-auto space-y-3">
          {(s.phase === "idle" || s.phase === "completed" || s.phase === "failed" || s.phase === "cancelled") && (
            <TriggerInputForm def={def} onRun={(vars) => useWorkflowSim.getState().start(api, def.id, vars)} />
          )}
          {human && s.activeTask && (
            <TaskInputPanel task={s.activeTask} onSubmit={(vals) => useWorkflowSim.getState().submitTask(api, vals)} />
          )}
          <div className="border-t pt-2">
            <div className="text-xs font-medium mb-1">Execution log</div>
            <ul className="text-xs space-y-0.5">
              {s.logs.map((l) => (
                <li key={l.id} className={l.status === "failed" ? "text-red-600" : "text-gray-600"}>
                  {l.status === "completed" ? "✓" : l.status === "failed" ? "✗" : "•"} {l.node_label ?? l.node_id}
                  {l.error_message ? ` — ${l.error_message}` : ""}
                </li>
              ))}
            </ul>
          </div>
          <details className="text-xs">
            <summary className="cursor-pointer">Variables</summary>
            <pre className="bg-gray-50 p-2 rounded overflow-auto">{JSON.stringify(s.variables, null, 2)}</pre>
          </details>
        </div>
      </div>
    </div>
  );
}
