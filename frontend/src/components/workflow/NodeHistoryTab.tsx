"use client";

/**
 * NodeHistoryTab — the "History" affordance in the Properties panel.
 *
 * Fetches the last N execution-log rows for the currently-selected
 * node from the generated app's /api/workflow-runs endpoint, showing
 * the resolved inputs, produced outputs, error message and duration
 * for each run. Powers the debug loop for authors.
 *
 * Data source: the generated app's Postgres, exposed via
 *   GET /api/workflow-runs?workflow_id=…&node_id=…&limit=20
 * (route emitted by backend/services/runtime_injector.py, spec §NC-4).
 *
 * We hit the generated app directly on its dev-server port (via the
 * usePreview hook), NOT through the platform backend — the platform
 * doesn't proxy to project runtime by default. If the preview isn't
 * running, the tab shows a gentle empty state instead of an error.
 *
 * Spec: docs/superpowers/specs/2026-07-22-workflow-node-contracts.md
 */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ChevronDown, ChevronRight, History, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { usePreview } from "@/hooks/usePreview";
import { cn } from "@/lib/utils";

export interface WorkflowRunRow {
  id: string;
  runId: string;
  workflowId: string;
  nodeId: string;
  nodeLabel: string;
  actionType: string;
  stepIndex: number;
  inputs: Record<string, unknown>;
  outputs: unknown;
  status: "running" | "completed" | "failed" | "skipped";
  error: string | null;
  durationMs: number | null;
  createdAt: string;
}

interface NodeHistoryTabProps {
  projectId?: string;
  workflowId?: string;
  nodeId: string;
}

export function NodeHistoryTab({ projectId, workflowId, nodeId }: NodeHistoryTabProps) {
  // Look up the running dev server's port for this project. If the
  // preview isn't running there's nothing to fetch.
  const { port } = usePreview(projectId ?? "");
  const baseUrl = port ? `http://localhost:${port}` : null;

  const enabled = Boolean(baseUrl && workflowId && nodeId);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["workflowRuns", baseUrl, workflowId, nodeId],
    enabled,
    refetchInterval: 5_000,
    queryFn: async (): Promise<{ rows: WorkflowRunRow[] }> => {
      const url = new URL(`${baseUrl}/api/workflow-runs`);
      if (workflowId) url.searchParams.set("workflow_id", workflowId);
      if (nodeId) url.searchParams.set("node_id", nodeId);
      url.searchParams.set("limit", "20");
      const res = await fetch(url.toString());
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
  });

  const rows = data?.rows ?? [];

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="flex items-center gap-1 text-[10px] font-semibold uppercase text-muted-foreground">
          <History className="h-3 w-3" /> History
        </Label>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 px-1.5 text-[10px]"
          onClick={() => refetch()}
          disabled={!enabled || isLoading}
        >
          {isLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : "Refresh"}
        </Button>
      </div>

      {!baseUrl && (
        <p className="text-[10px] text-muted-foreground leading-snug">
          Start the app preview to see execution history for this node.
        </p>
      )}
      {baseUrl && !workflowId && (
        <p className="text-[10px] text-muted-foreground">
          Save the workflow first to enable history.
        </p>
      )}
      {baseUrl && workflowId && error && (
        <p className="text-[10px] text-red-600">
          Couldn&apos;t load history — {(error as Error).message}
        </p>
      )}
      {baseUrl && workflowId && !error && rows.length === 0 && !isLoading && (
        <p className="text-[10px] text-muted-foreground">
          No runs recorded yet for this node.
        </p>
      )}

      <div className="space-y-1">
        {rows.map((r) => (
          <RunRow key={r.id} row={r} />
        ))}
      </div>
    </div>
  );
}

function RunRow({ row }: { row: WorkflowRunRow }) {
  const [open, setOpen] = useState(false);
  const failed = row.status === "failed";
  return (
    <div
      className={cn(
        "rounded border bg-white",
        failed ? "border-red-200" : "border-slate-100",
      )}
    >
      <button
        type="button"
        className="flex w-full items-center gap-1.5 px-2 py-1 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? (
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 text-muted-foreground" />
        )}
        {failed ? (
          <XCircle className="h-3.5 w-3.5 text-red-500" />
        ) : (
          <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
        )}
        <span className="flex-1 truncate text-[11px]">
          {new Date(row.createdAt).toLocaleTimeString()}
        </span>
        {row.durationMs != null && (
          <span className="text-[10px] text-muted-foreground">
            {row.durationMs}ms
          </span>
        )}
      </button>
      {open && (
        <div className="space-y-1 border-t px-2 py-1.5">
          <Section title="Inputs" value={row.inputs} />
          {row.error ? (
            <div className="rounded bg-red-50 px-1.5 py-1 text-[10px] text-red-700">
              {row.error}
            </div>
          ) : (
            <Section title="Outputs" value={row.outputs} />
          )}
          <div className="text-[9px] text-muted-foreground">
            run {row.runId.slice(0, 8)} · step #{row.stepIndex}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, value }: { title: string; value: unknown }) {
  const isEmpty =
    value == null ||
    (typeof value === "object" && Object.keys(value as object).length === 0);
  return (
    <div>
      <div className="text-[9px] uppercase text-muted-foreground">{title}</div>
      <pre className="max-h-32 overflow-auto rounded bg-muted/40 px-1.5 py-1 text-[10px] font-mono">
        {isEmpty ? "(empty)" : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
