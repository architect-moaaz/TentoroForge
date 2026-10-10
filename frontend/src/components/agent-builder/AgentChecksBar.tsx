"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Info, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AgentFinding, FindingSeverity } from "@/types/agent-builder";

const ICON = { error: XCircle, warning: AlertTriangle, info: Info } as const;
const TONE: Record<FindingSeverity, string> = {
  error: "text-red-700",
  warning: "text-amber-700",
  info: "text-slate-600",
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

interface AgentChecksBarProps {
  findings: AgentFinding[];
  /** False when the project has no built app yet, so only the agent itself was checked. */
  appChecked: boolean;
  /** Apply was pressed while there are errors: ask before going on. */
  confirming: boolean;
  onSelectNode: (nodeId: string) => void;
  onApplyAnyway: () => void;
  onCancel: () => void;
}

/**
 * What is wrong with the agent, said before Apply. Each line is pinned to the box it is about
 * ("Show" selects it); the boxes themselves are marked on the canvas.
 */
export function AgentChecksBar({
  findings,
  appChecked,
  confirming,
  onSelectNode,
  onApplyAnyway,
  onCancel,
}: AgentChecksBarProps) {
  const [open, setOpen] = useState(false);
  const count = (s: FindingSeverity) => findings.filter((f) => f.severity === s).length;
  const errors = count("error");
  const warnings = count("warning");
  const notes = count("info");

  if (findings.length === 0) {
    return (
      <div data-testid="agent-checks" aria-live="polite" className="flex items-center gap-1.5 border-b px-4 py-1 text-[11px] text-muted-foreground">
        <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
        {appChecked
          ? "No problems found, checked against this app."
          : "No problems found in the agent. This project has no built app yet, so nothing was checked against one."}
      </div>
    );
  }

  const summary = [
    errors ? plural(errors, "problem", "problems") : null,
    warnings ? plural(warnings, "warning", "warnings") : null,
    notes ? plural(notes, "note", "notes") : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      data-testid="agent-checks"
      aria-live="polite"
      className={`border-b px-4 py-1.5 text-xs ${errors ? "bg-red-50" : warnings ? "bg-amber-50" : "bg-slate-50"}`}
    >
      <button
        type="button"
        className="flex w-full items-center gap-1.5 text-left font-medium"
        aria-expanded={open || confirming}
        onClick={() => setOpen((o) => !o)}
      >
        {open || confirming ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <span className={errors ? TONE.error : warnings ? TONE.warning : TONE.info}>Checks: {summary}</span>
        {!appChecked && <span className="font-normal text-muted-foreground">(not checked against an app: none built yet)</span>}
      </button>

      {confirming && (
        <div className="mt-1.5 flex items-center gap-2 rounded border border-red-200 bg-white px-2 py-1.5">
          <span className="flex-1 text-red-700">
            {plural(errors, "problem", "problems")} will stop some of the tools from working. Apply anyway?
          </span>
          <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={onCancel}>
            Cancel
          </Button>
          <Button size="sm" className="h-6 px-2 text-xs" onClick={onApplyAnyway}>
            Apply anyway
          </Button>
        </div>
      )}

      {(open || confirming) && (
        <ul className="mt-1.5 max-h-40 space-y-1 overflow-y-auto pr-1">
          {findings.map((f, i) => {
            const Icon = ICON[f.severity];
            return (
              <li key={`${f.code}-${f.nodeId ?? "agent"}-${i}`} className="flex items-start gap-1.5">
                <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${TONE[f.severity]}`} aria-label={f.severity} />
                <span className="flex-1 text-slate-700">{f.message}</span>
                {f.nodeId && (
                  <button type="button" className="shrink-0 text-indigo-600 underline" onClick={() => onSelectNode(f.nodeId as string)}>
                    Show
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
