"use client";

/**
 * SelfVerifyCard — SV-10
 *
 * Compact chip surfacing a Self-Verify Pass run's outcome. Mirrors
 * SelfHealCard visual shell so users learn the pattern once.
 *
 * States (drive on `status` + `faults_count`):
 *   - running / pending           → "Verifying app…"           (amber, spinner)
 *   - done + faults_count == 0    → "Verified"                 (green)
 *   - done + smith_fixing != null → "Fixing 3 issues…"         (amber)
 *   - done + faults_count > 0     → "N fixed · M needs you"    (orange, click → RemediationReport)
 *   - failed                      → "Verification could not run" (red)
 */
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Loader2,
  Wrench,
  Play,
} from "lucide-react";
import { useState } from "react";

export type VerifyStatus = "pending" | "running" | "done" | "failed" | "superseded";

export interface VerifyRunSummary {
  id: string;
  status: VerifyStatus;
  target: "preview" | "deploy";
  interactions_run: number | null;
  interactions_passed: number | null;
  faults_count: number | null;
  rounds_run: number | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

interface Props {
  run: VerifyRunSummary;
  onOpenReport?: (runId: string) => void;
  onFixAndRepublish?: (runId: string) => void;
}

export function SelfVerifyCard({ run, onOpenReport, onFixAndRepublish }: Props) {
  const [expanded, setExpanded] = useState(false);
  const theme = _themeFor(run);
  const label = _labelFor(run);
  const Icon = theme.Icon;
  const clickable = run.status === "done" && (run.faults_count ?? 0) > 0;

  return (
    <div
      className={`inline-flex items-center gap-2 rounded-md border px-3 py-1.5
                  text-xs font-medium ${theme.bg} ${theme.border} ${theme.text}
                  ${clickable ? "cursor-pointer hover:opacity-90" : ""}`}
      onClick={clickable ? () => {
        setExpanded((x) => !x);
        onOpenReport?.(run.id);
      } : undefined}
      role={clickable ? "button" : "status"}
      aria-label={label}
    >
      <Icon className={theme.iconClass} size={14} aria-hidden />
      <span>{label}</span>
      {run.target === "deploy" && (
        <span className={`ml-1 rounded px-1.5 py-0.5 text-[10px] uppercase
                          tracking-wide ${theme.badgeBg} ${theme.badgeText}`}>
          deploy
        </span>
      )}
      {run.status === "done" && (run.faults_count ?? 0) > 0
        && run.target === "deploy" && onFixAndRepublish && (
        <button
          className="ml-2 inline-flex items-center gap-1 rounded border
                     border-orange-500 px-2 py-0.5 text-[11px] text-orange-700
                     hover:bg-orange-50"
          onClick={(e) => {
            e.stopPropagation();
            onFixAndRepublish(run.id);
          }}
        >
          <Play size={11} /> Fix &amp; republish
        </button>
      )}
    </div>
  );
}


function _themeFor(run: VerifyRunSummary) {
  if (run.status === "failed") {
    return {
      bg: "bg-red-50", border: "border-red-300", text: "text-red-800",
      iconClass: "text-red-600", Icon: XCircle,
      badgeBg: "bg-red-100", badgeText: "text-red-700",
    };
  }
  if (run.status === "pending" || run.status === "running") {
    return {
      bg: "bg-amber-50", border: "border-amber-300", text: "text-amber-800",
      iconClass: "text-amber-600 animate-spin", Icon: Loader2,
      badgeBg: "bg-amber-100", badgeText: "text-amber-700",
    };
  }
  const faults = run.faults_count ?? 0;
  if (faults === 0) {
    return {
      bg: "bg-emerald-50", border: "border-emerald-300", text: "text-emerald-800",
      iconClass: "text-emerald-600", Icon: CheckCircle2,
      badgeBg: "bg-emerald-100", badgeText: "text-emerald-700",
    };
  }
  return {
    bg: "bg-orange-50", border: "border-orange-300", text: "text-orange-800",
    iconClass: "text-orange-600", Icon: AlertTriangle,
    badgeBg: "bg-orange-100", badgeText: "text-orange-700",
  };
}


function _labelFor(run: VerifyRunSummary): string {
  if (run.status === "failed") return "Verification could not run";
  if (run.status === "pending" || run.status === "running") return "Verifying app…";
  const passed = run.interactions_passed ?? 0;
  const total = run.interactions_run ?? 0;
  const faults = run.faults_count ?? 0;
  if (faults === 0) return `Verified (${passed}/${total} checks)`;
  const fixed = Math.max(0, total - faults);
  if (fixed > 0) return `${fixed} fixed · ${faults} needs you`;
  return `${faults} issue${faults === 1 ? "" : "s"} needs you`;
}
