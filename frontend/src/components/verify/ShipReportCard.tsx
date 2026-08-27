"use client";

/**
 * ShipReportCard
 *
 * The build's terminal verdict chip (V3). Renders the consolidated
 * `ship_report` SSE event emitted by the pipeline's ship node
 * (backend services/ship_report.py), which folds every verification
 * artifact — delivery gate, security gate, binding validation,
 * phase-gate quarantine, in-app test manifest — into one pass/warn/block
 * answer to "can this app ship?".
 *
 * States:
 *   - verdict "pass"  → green  "Ready to ship"
 *   - verdict "warn"  → amber  "Ships with N finding(s)" (click expands)
 *   - verdict "block" → red    "Blocked: N critical finding(s)" (expanded)
 *
 * Expansion lists per-source counts + up to 5 sample findings each, so
 * the user can see WHICH dimension (security vs bindings vs delivery)
 * needs attention without opening artifacts on disk.
 */
import {
  CheckCircle2,
  AlertTriangle,
  ShieldAlert,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { useState } from "react";

export interface ShipReport {
  verdict: "pass" | "warn" | "block";
  mode: string;
  summary: { criticals: number; errors: number; warnings: number };
  sources: Record<
    string,
    {
      present: boolean;
      criticals?: number;
      errors?: number;
      warnings?: number;
      sample?: string[];
    }
  >;
}

const SOURCE_LABELS: Record<string, string> = {
  delivery: "Delivery gate",
  security: "Security gate",
  quarantine: "Phase-gate quarantine",
  binding_smoke: "Binding smoke",
  binding_report: "Binding report",
  workflow_validation: "Workflow validation",
  requirement_fidelity: "Requirement fidelity",
  proof: "Proof pass",
  app_tests: "In-app test suite",
  auto_heal: "Auto-heal",
};

export function ShipReportCard({ report }: { report: ShipReport }) {
  const [expanded, setExpanded] = useState(report.verdict === "block");
  const { criticals, errors, warnings } = report.summary;
  const findings = criticals + errors;

  const tone =
    report.verdict === "pass"
      ? "border-green-500/40 bg-green-500/5 text-green-700 dark:text-green-400"
      : report.verdict === "warn"
        ? "border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-400"
        : "border-red-500/40 bg-red-500/5 text-red-700 dark:text-red-400";

  const Icon =
    report.verdict === "pass"
      ? CheckCircle2
      : report.verdict === "block"
        ? ShieldAlert
        : AlertTriangle;

  const headline =
    report.verdict === "pass"
      ? warnings > 0
        ? `Ready to ship · ${warnings} advisory warning${warnings === 1 ? "" : "s"}`
        : "Ready to ship — all verification gates passed"
      : report.verdict === "warn"
        ? `Ships with ${findings} open finding${findings === 1 ? "" : "s"}`
        : `Blocked — ${criticals} critical finding${criticals === 1 ? "" : "s"}`;

  const problemSources = Object.entries(report.sources).filter(
    ([, s]) => s.present && ((s.criticals ?? 0) + (s.errors ?? 0) + (s.warnings ?? 0)) > 0,
  );
  const expandable = problemSources.length > 0;

  return (
    <div className={`rounded-md border px-2.5 py-1.5 text-xs ${tone}`}>
      <button
        type="button"
        className="flex w-full items-center gap-1.5 text-left"
        onClick={() => expandable && setExpanded((e) => !e)}
        disabled={!expandable}
      >
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span className="font-medium">{headline}</span>
        <span className="ml-auto flex items-center gap-1 text-[10px] opacity-70">
          ship-report.json
          {expandable &&
            (expanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            ))}
        </span>
      </button>
      {expanded && expandable && (
        <div className="mt-1.5 space-y-1.5 border-t border-current/10 pt-1.5">
          {problemSources.map(([name, s]) => (
            <div key={name}>
              <p className="font-medium">
                {SOURCE_LABELS[name] ?? name}
                <span className="ml-1.5 font-normal opacity-70">
                  {(s.criticals ?? 0) > 0 && `${s.criticals} critical · `}
                  {(s.errors ?? 0) > 0 && `${s.errors} error(s) · `}
                  {(s.warnings ?? 0) > 0 && `${s.warnings} warning(s)`}
                </span>
              </p>
              {(s.sample ?? []).slice(0, 3).map((line, i) => (
                <p
                  key={i}
                  className="truncate pl-3 font-mono text-[10px] opacity-60"
                  title={line}
                >
                  {line}
                </p>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
