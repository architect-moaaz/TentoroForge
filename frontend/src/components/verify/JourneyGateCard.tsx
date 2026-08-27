"use client";

/**
 * JourneyGateCard
 *
 * Compact chip surfacing the post-generation journey verification pass.
 * Mirrors SelfVerifyCard's visual shell so users learn the pattern once.
 *
 * States (drive on summary presence + counts):
 *   - no summary, no results        → not rendered (gate off / not run yet)
 *   - results but no summary        → "Walking journeys… (N of ?)"   (amber, spinner)
 *   - summary + failed == 0         → "N journeys passed in Xs"      (green)
 *   - summary + failed  > 0         → "N failed · M passed in Xs"    (orange, click expands)
 *
 * Expansion (only when failed > 0) shows one row per failed journey with:
 *   step name that failed + first 200 chars of the error. This is enough
 *   to diagnose most failures without opening the Playwright trace.
 */
import {
  CheckCircle2,
  AlertTriangle,
  Loader2,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { useState } from "react";

export interface JourneyResult {
  slug: string;
  name: string;
  status: "passed" | "failed" | "timedOut" | "skipped" | "unknown";
  duration_ms: number;
  failing_step?: string | null;
  failure?: string | null;
}

export interface JourneyGateSummary {
  mode: "warn" | "strict";
  ok: boolean;
  total: number;
  passed: number;
  failed: number;
  duration_ms: number;
}

export interface JourneyRemediationHint {
  journey_slug: string;
  failing_step: string | null;
  likely_cause: string;
  target_seam: string;
  hint: string;
  tags: string[];
}

interface Props {
  results: JourneyResult[];
  summary: JourneyGateSummary | null;
  hints?: JourneyRemediationHint[];
}

export function JourneyGateCard({ results, summary, hints = [] }: Props) {
  const hintFor = (slug: string) => hints.find((h) => h.journey_slug === slug);
  const [expanded, setExpanded] = useState(false);

  // Gate never ran (or was off) — nothing to show.
  if (!summary && results.length === 0) return null;

  const running = summary === null;
  const failed = summary
    ? summary.failed
    : results.filter((r) => r.status !== "passed").length;
  const passed = summary
    ? summary.passed
    : results.filter((r) => r.status === "passed").length;
  const total = summary?.total ?? results.length;
  const durationS = summary
    ? Math.round(summary.duration_ms / 100) / 10
    : results.reduce((a, r) => a + r.duration_ms, 0) / 1000;

  const theme = _themeFor({ running, failed, passed });
  const label = _labelFor({ running, failed, passed, total, durationS });
  const Icon = theme.Icon;
  const hasFailures = failed > 0;
  const failedRows = results.filter((r) => r.status !== "passed");

  return (
    <div className="inline-flex flex-col gap-1">
      <div
        className={`inline-flex items-center gap-2 rounded-md border px-3 py-1.5
                    text-xs font-medium ${theme.bg} ${theme.border} ${theme.text}
                    ${hasFailures ? "cursor-pointer hover:opacity-90" : ""}`}
        onClick={hasFailures ? () => setExpanded((x) => !x) : undefined}
        role={hasFailures ? "button" : "status"}
        aria-expanded={hasFailures ? expanded : undefined}
        aria-label={label}
      >
        <Icon className={theme.iconClass} size={14} aria-hidden />
        <span>{label}</span>
        {summary?.mode === "strict" && (
          <span
            className={`ml-1 rounded px-1.5 py-0.5 text-[10px] uppercase
                        tracking-wide ${theme.badgeBg} ${theme.badgeText}`}
          >
            strict
          </span>
        )}
        {hasFailures && (
          <span className="ml-1 text-[11px] opacity-70">
            {expanded ? (
              <ChevronDown size={12} aria-hidden />
            ) : (
              <ChevronRight size={12} aria-hidden />
            )}
          </span>
        )}
      </div>

      {hasFailures && expanded && (
        <ul
          className={`mt-1 flex flex-col gap-1 rounded-md border ${theme.border}
                      ${theme.bg} p-2 text-[11px] ${theme.text} max-w-[520px]`}
        >
          {failedRows.map((r) => (
            <li key={r.slug} className="flex flex-col gap-0.5">
              <div className="flex items-center gap-1.5 font-medium">
                <AlertTriangle
                  size={11}
                  className="text-orange-600 shrink-0"
                  aria-hidden
                />
                <span className="truncate">{r.name || r.slug}</span>
                <span className="opacity-60">
                  · {Math.round(r.duration_ms / 100) / 10}s
                </span>
              </div>
              {r.failing_step && (
                <div className="ml-4 opacity-80">
                  failed at:{" "}
                  <code className="text-[10px] bg-black/5 rounded px-1">
                    {r.failing_step}
                  </code>
                </div>
              )}
              {r.failure && (
                <div className="ml-4 opacity-70 line-clamp-2 font-mono text-[10px]">
                  {r.failure.slice(0, 200)}
                </div>
              )}
              {hintFor(r.slug) && (
                <div className="ml-4 mt-1 rounded border border-orange-200 bg-white/60 p-1.5">
                  <div className="text-[10px] uppercase tracking-wide opacity-60">
                    fix hint · {hintFor(r.slug)!.target_seam}
                  </div>
                  <div className="text-[11px] font-medium">
                    {hintFor(r.slug)!.likely_cause}
                  </div>
                  <div className="text-[10px] opacity-80 line-clamp-3">
                    {hintFor(r.slug)!.hint}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


function _themeFor({
  running,
  failed,
  passed,
}: {
  running: boolean;
  failed: number;
  passed: number;
}) {
  if (running) {
    return {
      bg: "bg-amber-50",
      border: "border-amber-300",
      text: "text-amber-800",
      iconClass: "text-amber-600 animate-spin",
      Icon: Loader2,
      badgeBg: "bg-amber-100",
      badgeText: "text-amber-700",
    };
  }
  if (failed === 0 && passed > 0) {
    return {
      bg: "bg-emerald-50",
      border: "border-emerald-300",
      text: "text-emerald-800",
      iconClass: "text-emerald-600",
      Icon: CheckCircle2,
      badgeBg: "bg-emerald-100",
      badgeText: "text-emerald-700",
    };
  }
  // Failures. Orange over red — the gate is warn-mode by default and a
  // strict-mode failure will be surfaced additionally via the pipeline
  // error path; the card itself stays "attention" not "catastrophe".
  return {
    bg: "bg-orange-50",
    border: "border-orange-300",
    text: "text-orange-800",
    iconClass: "text-orange-600",
    Icon: AlertTriangle,
    badgeBg: "bg-orange-100",
    badgeText: "text-orange-700",
  };
}


function _labelFor({
  running,
  failed,
  passed,
  total,
  durationS,
}: {
  running: boolean;
  failed: number;
  passed: number;
  total: number;
  durationS: number;
}) {
  if (running) {
    return total > 0
      ? `Walking journey ${passed + failed + 1} of ${total}…`
      : "Walking journeys…";
  }
  const dur = `${durationS.toFixed(1)}s`;
  if (failed === 0) {
    return `${passed} of ${total} journey${total === 1 ? "" : "s"} passed in ${dur}`;
  }
  return `${failed} failed · ${passed} passed in ${dur}`;
}
