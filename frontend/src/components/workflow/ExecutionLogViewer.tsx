"use client";

import {
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  SkipForward,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { useState } from "react";
import type {
  ExecutionLog,
  StepLog,
  WorkflowNodeSerialized,
} from "@/types/workflow";

interface ExecutionLogViewerProps {
  log: ExecutionLog;
  nodes: WorkflowNodeSerialized[];
}

const STATUS_ICONS = {
  running: Loader2,
  completed: CheckCircle,
  failed: XCircle,
  skipped: SkipForward,
} as const;

const STATUS_COLORS = {
  running: "text-blue-500",
  completed: "text-green-500",
  failed: "text-red-500",
  skipped: "text-gray-400",
} as const;

export function ExecutionLogViewer({ log, nodes }: ExecutionLogViewerProps) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold">Execution Log</h4>
        {log.completedAt && (
          <span className="text-[10px] text-muted-foreground">
            {totalDuration(log)} total
          </span>
        )}
      </div>

      <div className="space-y-0.5">
        {log.steps.map((step, idx) => (
          <StepEntry
            key={`${step.stepId}-${idx}`}
            step={step}
            node={nodes.find((n) => n.id === step.stepId)}
          />
        ))}
      </div>

      {log.status === "running" && log.steps.length > 0 && (
        <div className="flex items-center gap-1.5 pl-6 pt-1">
          <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
          <span className="text-[10px] text-muted-foreground">
            Executing next step...
          </span>
        </div>
      )}
    </div>
  );
}

function StepEntry({
  step,
  node,
}: {
  step: StepLog;
  node?: WorkflowNodeSerialized;
}) {
  const [expanded, setExpanded] = useState(false);
  const Icon = STATUS_ICONS[step.status];
  const colorClass = STATUS_COLORS[step.status];

  const label = node?.data.label || step.stepId;
  const nodeType = node?.data.nodeType || "unknown";

  return (
    <div className="rounded border bg-white">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
        )}
        <Icon
          className={`h-3.5 w-3.5 shrink-0 ${colorClass} ${
            step.status === "running" ? "animate-spin" : ""
          }`}
        />
        <span className="flex-1 truncate text-xs font-medium">{label}</span>
        <span className="text-[10px] text-muted-foreground">{nodeType}</span>
        {step.durationMs != null && (
          <span className="text-[10px] text-muted-foreground">
            {step.durationMs}ms
          </span>
        )}
      </button>

      {expanded && (
        <div className="border-t px-3 py-2 text-[11px] space-y-1">
          <div className="flex gap-4">
            <span className="text-muted-foreground">Started:</span>
            <span>{formatTime(step.startedAt)}</span>
          </div>
          {step.completedAt && (
            <div className="flex gap-4">
              <span className="text-muted-foreground">Completed:</span>
              <span>{formatTime(step.completedAt)}</span>
            </div>
          )}
          {step.error && (
            <div className="rounded bg-red-50 px-2 py-1 text-red-700">
              {step.error}
            </div>
          )}
          {step.result && Object.keys(step.result).length > 0 && (
            <div>
              <span className="text-muted-foreground">Result:</span>
              <pre className="mt-0.5 rounded bg-muted/50 px-2 py-1 font-mono text-[10px] overflow-x-auto">
                {JSON.stringify(step.result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

function totalDuration(log: ExecutionLog): string {
  if (!log.completedAt) return "";
  const ms =
    new Date(log.completedAt).getTime() - new Date(log.startedAt).getTime();
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
