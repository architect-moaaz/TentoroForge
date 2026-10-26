"use client";

/**
 * Which workflows use an assistant, in the Agents tab: a "Used by N workflows" tag, a quiet "Made for a workflow" tag
 * for assistants that were created for one step, and a delete button that says which workflows would lose their
 * assistant before it goes.
 *
 * These are small separate pieces so the big builder panel only needs a line or two to show them. An older platform
 * has no used-by route: the answer then reads as "none" and nothing is shown, never an error.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { isWorkflowOnly } from "@/lib/agent-step";

export interface UsedByWorkflow {
  workflowId: string;
  workflowName: string;
  stepId: string;
}

const usedByKey = (projectId: string, agentId: string) =>
  ["project", projectId, "agent-definitions", agentId, "used-by"] as const;

/** The steps that use this assistant. A missing route, an error or an odd answer all mean "none we know of". */
async function fetchUsedBy(projectId: string, agentId: string): Promise<UsedByWorkflow[]> {
  try {
    const res = await api.get<{ workflows?: unknown }>(
      `/api/projects/${projectId}/agent-definitions/${encodeURIComponent(agentId)}/used-by`,
    );
    const list = Array.isArray(res?.workflows) ? res.workflows : [];
    return list
      .filter((w): w is Record<string, unknown> => typeof w === "object" && w !== null)
      .map((w) => ({
        workflowId: String(w.workflowId ?? ""),
        workflowName: String(w.workflowName ?? w.workflowId ?? ""),
        stepId: String(w.stepId ?? ""),
      }));
  } catch {
    return [];
  }
}

/** How many different workflows use it (two steps in one workflow count once). */
export function workflowCount(used: UsedByWorkflow[]): number {
  return new Set(used.map((u) => u.workflowId || u.workflowName)).size;
}

/** "Triage visit, Reminders" for the confirm and the tag's hover text. */
export function workflowNames(used: UsedByWorkflow[]): string {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const u of used) {
    const n = u.workflowName || u.workflowId;
    if (n && !seen.has(n)) {
      seen.add(n);
      names.push(n);
    }
  }
  return names.join(", ");
}

/** The tags shown beside an assistant's name in the list. */
export function AgentListTags({ projectId, agentId }: { projectId: string; agentId: string }) {
  const { data: used = [] } = useQuery({
    queryKey: usedByKey(projectId, agentId),
    queryFn: () => fetchUsedBy(projectId, agentId),
    retry: false,
    staleTime: 30_000,
  });
  const n = workflowCount(used);
  return (
    <>
      {isWorkflowOnly(agentId) && (
        <span className="rounded border border-gray-200 px-1.5 text-[10px] text-muted-foreground">Made for a workflow</span>
      )}
      {n > 0 && (
        <span
          className="rounded-full bg-purple-50 px-2 py-0.5 text-[10px] font-medium text-purple-800"
          title={workflowNames(used)}
        >
          Used by {n} workflow{n === 1 ? "" : "s"}
        </span>
      )}
    </>
  );
}

/**
 * The delete button of a list row. An assistant nothing uses is deleted at once, as before. One that workflows use
 * asks first, naming them, because deleting it leaves those steps with no assistant.
 */
export function DeleteAgentButton({
  projectId,
  agentId,
  agentName,
  onDelete,
}: {
  projectId: string;
  agentId: string;
  agentName: string;
  onDelete: () => void | Promise<void>;
}) {
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState<UsedByWorkflow[] | null>(null);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    // Ask fresh: a workflow may have picked this assistant since the list was drawn.
    const used = await queryClient.fetchQuery({
      queryKey: usedByKey(projectId, agentId),
      queryFn: () => fetchUsedBy(projectId, agentId),
      staleTime: 0,
    });
    if (used.length === 0) {
      await onDelete();
      return;
    }
    setAsking(used);
  };

  const confirm = async () => {
    setBusy(true);
    try {
      await onDelete();
    } finally {
      setBusy(false);
      setAsking(null);
    }
  };

  return (
    // The dialog is drawn in a portal, but React still passes its clicks up to the row (which opens the assistant):
    // this wrapper stops them here. `contents` keeps the button where the old one sat.
    <span className="contents" onClick={(e) => e.stopPropagation()}>
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0"
        aria-label={`Delete ${agentName}`}
        onClick={() => void start()}
      >
        <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
      </Button>
      <Dialog open={asking !== null} onOpenChange={(open) => { if (!open && !busy) setAsking(null); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Delete this assistant?</DialogTitle>
            <DialogDescription>
              {agentName} is used by {asking ? workflowCount(asking) : 0} workflow{asking && workflowCount(asking) === 1 ? "" : "s"}.
              If you delete it, those steps are left without an assistant and the app will not build until you pick another.
            </DialogDescription>
          </DialogHeader>
          <ul className="space-y-1 text-sm" data-testid="used-by-list">
            {(asking ?? []).map((u, i) => (
              <li key={`${u.workflowId}-${u.stepId}-${i}`}>
                <span className="font-medium">{u.workflowName || u.workflowId}</span>
                {u.stepId && <span className="text-muted-foreground">, step {u.stepId}</span>}
              </li>
            ))}
          </ul>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setAsking(null)} disabled={busy}>Keep it</Button>
            <Button variant="destructive" size="sm" onClick={confirm} disabled={busy}>Delete it anyway</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </span>
  );
}
