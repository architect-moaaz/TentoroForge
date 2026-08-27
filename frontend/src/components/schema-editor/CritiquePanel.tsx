"use client";

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";
import {
  scorePage,
  fetchFidelityLog,
  type Critique,
  type PageLogEntry,
} from "@/lib/fidelity-client";
import { FidelityScoreBadge } from "./FidelityScoreBadge";
import { IterationHistory } from "./IterationHistory";

interface CritiquePanelProps {
  shortId: string;
  pageRoute: string;
  pagePath: string;
  context: {
    domain: string;
    appName: string;
    description: string;
    tone: string;
  };
}

/**
 * Synthesize a Critique-shaped object from the latest iteration in a log entry.
 * Used as a fallback when a live re-score hasn't been run yet.
 */
function deriveCritiqueFromLog(entry: PageLogEntry): Critique | null {
  const iters = entry.iterations;
  if (!iters.length) return null;
  const last = iters[iters.length - 1];
  return {
    compositeScore: last.score,
    pass: last.pass,
    scores: { overall: last.score },
    topIssues: (last.issues ?? []) as Critique["topIssues"],
    strengths: [],
    designerApprovalRecommended: entry.failed_fidelity ?? false,
  };
}

export function CritiquePanel({
  shortId,
  pageRoute,
  pagePath,
  context,
}: CritiquePanelProps) {
  const [logEntry, setLogEntry] = useState<PageLogEntry | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchFidelityLog(shortId).then((log) => {
      if (!cancelled && log) setLogEntry(log[pagePath] ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [shortId, pagePath]);

  const m = useMutation<Critique, Error>({
    mutationFn: () => scorePage(shortId, pageRoute, pagePath, context),
  });

  // Prefer fresh re-score data; fall back to derived log data.
  const displayCritique: Critique | null =
    m.data ?? (logEntry ? deriveCritiqueFromLog(logEntry) : null);

  const isFailedFidelity = logEntry?.failed_fidelity;
  const iterations = logEntry?.iterations ?? [];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b px-4 py-2 shrink-0">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Fidelity Score
        </span>
        <FidelityScoreBadge
          score={displayCritique ? displayCritique.compositeScore : null}
        />
        {displayCritique && (
          <span
            className={`text-[11px] font-medium ${displayCritique.pass ? "text-emerald-600" : "text-rose-600"}`}
          >
            {displayCritique.pass ? "PASS" : "FAIL"}
          </span>
        )}
        <button
          type="button"
          onClick={() => m.mutate()}
          disabled={m.isPending}
          className="ml-auto rounded border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
        >
          {m.isPending ? "Scoring…" : "Re-score"}
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto p-4">
        {/* Failed fidelity warning */}
        {isFailedFidelity && !m.data && (
          <div className="mb-4 flex items-start gap-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <strong>Quality target not reached.</strong> This page didn&apos;t
              reach the rubric pass after {logEntry?.final_iteration} iterations.
              Re-score after manual edits, or accept it as-is.
            </div>
          </div>
        )}

        {m.isPending && (
          <div className="flex items-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Rendering and evaluating…
          </div>
        )}

        {m.error && (
          <div className="rounded border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {m.error.message}
          </div>
        )}

        {displayCritique && !m.isPending && (
          <div className="space-y-4 text-sm">
            {/* Score breakdown grid */}
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(displayCritique.scores).map(([k, v]) => (
                <div
                  key={k}
                  className="flex items-center justify-between rounded border px-3 py-1.5"
                >
                  <span className="capitalize text-xs text-muted-foreground">
                    {k.replace(/([A-Z])/g, " $1").trim()}
                  </span>
                  <span className="font-mono">{Number(v).toFixed(1)}</span>
                </div>
              ))}
            </div>

            {/* Top issues */}
            {displayCritique.topIssues.length > 0 && (
              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                  Top Issues
                </h4>
                <ul className="space-y-2">
                  {displayCritique.topIssues.map((issue, idx) => (
                    <li key={idx} className="rounded border p-3">
                      <div className="mb-1 flex items-center gap-2">
                        <AlertTriangle className="h-3.5 w-3.5 text-amber-600 shrink-0" />
                        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                          {issue.severity} · {issue.axis}
                        </span>
                        {issue.nodeIdHint && (
                          <code className="ml-auto rounded bg-muted px-1.5 py-0.5 text-[11px]">
                            {issue.nodeIdHint}
                          </code>
                        )}
                      </div>
                      <div className="text-foreground">{issue.issue}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        → {issue.suggestion}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Strengths */}
            {displayCritique.strengths.length > 0 && (
              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                  Strengths
                </h4>
                <ul className="space-y-1">
                  {displayCritique.strengths.map((s, idx) => (
                    <li key={idx} className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
                      <span>{s}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Iteration history */}
            {iterations.length > 0 && (
              <div className="mt-4">
                <IterationHistory
                  iterations={iterations}
                  shortId={shortId}
                  pagePath={pagePath}
                />
              </div>
            )}

            {/* Designer approval hint */}
            {displayCritique.designerApprovalRecommended && (
              <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                Designer approval recommended before shipping.
              </div>
            )}
          </div>
        )}

        {!m.isPending && !displayCritique && !m.error && (
          <div className="space-y-4 text-sm text-muted-foreground">
            <p>
              Click <strong>Re-score</strong> to render and evaluate this page.
            </p>
            {/* Show iteration history even when no critique is available */}
            {iterations.length > 0 && (
              <IterationHistory
                iterations={iterations}
                shortId={shortId}
                pagePath={pagePath}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
