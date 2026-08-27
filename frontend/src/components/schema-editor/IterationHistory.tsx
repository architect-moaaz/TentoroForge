// frontend/src/components/schema-editor/IterationHistory.tsx
"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { IterationDiffViewer } from "./IterationDiffViewer";

export interface IterationRow {
  iteration: number;
  score: number;
  issues?: any[];
  patch_summary?: string[];
  pass: boolean;
  manual_run?: boolean;
  screenshotUrl?: string;
}

interface IterationHistoryProps {
  iterations: IterationRow[];
  /** When provided, the diff viewer renders for iter > 0 in expanded rows. */
  shortId?: string;
  pagePath?: string;
}

export function IterationHistory({ iterations, shortId, pagePath }: IterationHistoryProps) {
  const [open, setOpen] = useState(false);
  const [expandedIter, setExpandedIter] = useState<number | null>(null);

  if (!iterations.length) return null;

  return (
    <div className="border rounded">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:bg-muted/50"
      >
        <span>Iteration history ({iterations.length})</span>
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
      </button>
      {open && (
        <div className="divide-y">
          {iterations.map((it, idx) => {
            const prevScore = idx > 0 ? iterations[idx - 1].score : null;
            const delta = prevScore !== null ? it.score - prevScore : 0;
            const isExpanded = expandedIter === it.iteration;
            return (
              <div key={`${it.iteration}-${idx}`} className="px-3 py-2 text-xs">
                <button
                  type="button"
                  onClick={() =>
                    setExpandedIter(isExpanded ? null : it.iteration)
                  }
                  className="flex w-full items-center gap-3"
                >
                  <span className="font-mono text-muted-foreground">
                    iter {it.iteration}
                  </span>
                  <span className="font-semibold">{it.score.toFixed(1)}</span>
                  {prevScore !== null && (
                    <span
                      className={
                        delta >= 0 ? "text-emerald-600" : "text-rose-600"
                      }
                    >
                      {delta >= 0 ? "+" : ""}
                      {delta.toFixed(1)}
                    </span>
                  )}
                  <span className="ml-auto text-muted-foreground">
                    {it.patch_summary?.length
                      ? `${it.patch_summary.length} patch${it.patch_summary.length === 1 ? "" : "es"}`
                      : "no patches"}
                  </span>
                  {it.manual_run && (
                    <span className="text-[10px] text-blue-600">manual</span>
                  )}
                  <span
                    className={
                      it.pass ? "text-emerald-600" : "text-muted-foreground"
                    }
                  >
                    {it.pass ? "pass" : "—"}
                  </span>
                </button>
                {isExpanded && (
                  <div className="mt-2 ml-12 space-y-2 text-muted-foreground">
                    {it.patch_summary?.map((s, i) => (
                      <div key={i}>↳ {s}</div>
                    ))}
                    {it.screenshotUrl && (
                      <img
                        src={it.screenshotUrl}
                        alt={`iter ${it.iteration}`}
                        className="mt-2 max-w-xs rounded border"
                      />
                    )}
                    {idx > 0 && shortId && pagePath && (
                      <IterationDiffViewer
                        shortId={shortId}
                        pagePath={pagePath}
                        iterFrom={iterations[idx - 1].iteration}
                        iterTo={it.iteration}
                        patchSummary={it.patch_summary}
                      />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
