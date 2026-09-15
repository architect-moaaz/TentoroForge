"use client";

/**
 * The render-review utility window.
 *
 * While Smith looks at the app it just built — screenshotting each page and
 * running a vision critic over them — this small window comes up bottom-right
 * and shows what Smith is seeing: the screenshots, then the critic's analysis,
 * then which pages are being re-composed. Smith narrates the same story in the
 * chat; this is the picture beside the words.
 *
 * State is fed live from `run.review` (SSE `review` events). It carries no
 * history: it means something only while the review is happening.
 */
import { useEffect, useState } from "react";
import type { ReviewState, ReviewFinding } from "@/hooks/useBlueprintRun";

const PHASE_LABEL: Record<ReviewState["phase"], string> = {
  start: "Opening the pages…",
  shots: "Looking at the render…",
  analysis: "Reviewing the design…",
  fixing: "Re-composing what needs work…",
  done: "Review complete",
};

const SEVERITY_STYLE: Record<string, string> = {
  error: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  warn: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  info: "bg-slate-100 text-slate-600 dark:bg-slate-700/40 dark:text-slate-300",
};

function findingsByRoute(findings: ReviewFinding[]): Map<string, ReviewFinding[]> {
  const m = new Map<string, ReviewFinding[]>();
  for (const f of findings) {
    const arr = m.get(f.route) ?? [];
    arr.push(f);
    m.set(f.route, arr);
  }
  return m;
}

export function ReviewWindow({ review }: { review: ReviewState | null }) {
  const [dismissed, setDismissed] = useState(false);
  const [zoom, setZoom] = useState<string | null>(null);

  // A fresh review (back to phase "start") re-opens a window the user closed.
  useEffect(() => {
    if (review?.phase === "start") setDismissed(false);
  }, [review?.phase]);

  if (!review || !review.active || dismissed) return null;

  const working = review.phase !== "done";
  const byRoute = findingsByRoute(review.findings);
  const done = review.phase === "done";

  return (
    <>
      {zoom && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-6"
          onClick={() => setZoom(null)}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={zoom} alt="page" className="max-h-full max-w-full rounded-lg shadow-2xl" />
        </div>
      )}

      <div className="fixed bottom-4 right-4 z-[60] w-[360px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        {/* Header */}
        <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2.5 dark:border-slate-800">
          <span className="relative flex h-2.5 w-2.5 shrink-0">
            {working && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sky-400 opacity-70" />
            )}
            <span
              className={`relative inline-flex h-2.5 w-2.5 rounded-full ${
                working ? "bg-sky-500" : review.converged ? "bg-emerald-500" : "bg-amber-500"
              }`}
            />
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-semibold text-slate-800 dark:text-slate-100">
              Smith is reviewing the build
            </div>
            <div className="truncate text-[11px] text-slate-500 dark:text-slate-400">
              {PHASE_LABEL[review.phase]}
              {review.round > 0 && review.phase !== "done" ? ` · round ${review.round}` : ""}
            </div>
          </div>
          {done && (
            <button
              onClick={() => setDismissed(true)}
              className="rounded-md px-1.5 py-0.5 text-[11px] text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"
            >
              Close
            </button>
          )}
        </div>

        {/* Body */}
        <div className="max-h-[52vh] overflow-y-auto px-3 py-2.5">
          {review.shots.length === 0 && working && (
            <div className="py-6 text-center text-[12px] text-slate-400">
              Capturing the pages…
            </div>
          )}

          <div className="flex flex-col gap-3">
            {review.shots.map((s) => {
              const fs = byRoute.get(s.route) ?? [];
              const fixing = review.fixing.includes(s.route);
              return (
                <div key={s.route} className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700">
                  <button
                    onClick={() => setZoom(s.image)}
                    className="group relative block w-full"
                    title="Click to enlarge"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={s.image}
                      alt={s.route}
                      className="block max-h-40 w-full object-cover object-top transition group-hover:opacity-90"
                    />
                    {fixing && (
                      <span className="absolute inset-0 flex items-center justify-center bg-sky-900/40 text-[11px] font-medium text-white backdrop-blur-[1px]">
                        Re-composing…
                      </span>
                    )}
                  </button>
                  <div className="flex items-center justify-between gap-2 border-t border-slate-100 px-2.5 py-1.5 dark:border-slate-800">
                    <span className="truncate font-mono text-[11px] text-slate-500 dark:text-slate-400">
                      {s.route}
                    </span>
                    {review.phase === "analysis" || done ? (
                      fs.length === 0 ? (
                        <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
                          looks good
                        </span>
                      ) : (
                        <span className="shrink-0 text-[10px] text-slate-400">
                          {fs.length} issue{fs.length === 1 ? "" : "s"}
                        </span>
                      )
                    ) : null}
                  </div>
                  {fs.length > 0 && (
                    <ul className="space-y-1 border-t border-slate-100 px-2.5 py-2 dark:border-slate-800">
                      {fs.map((f, i) => (
                        <li key={i} className="flex items-start gap-1.5">
                          <span
                            className={`mt-0.5 shrink-0 rounded px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${
                              SEVERITY_STYLE[f.severity] ?? SEVERITY_STYLE.info
                            }`}
                          >
                            {f.kind.replace(/_/g, " ")}
                          </span>
                          <span className="text-[11px] leading-snug text-slate-600 dark:text-slate-300">
                            {f.note}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer — the outcome, once done */}
        {done && (
          <div className="border-t border-slate-100 px-3 py-2 text-[11px] dark:border-slate-800">
            {review.converged ? (
              <span className="text-emerald-600 dark:text-emerald-400">
                ✓ Re-composed {review.recomposed?.length ?? 0} page
                {(review.recomposed?.length ?? 0) === 1 ? "" : "s"} — it looks right now.
              </span>
            ) : (
              <span className="text-amber-600 dark:text-amber-400">
                Re-composed {review.recomposed?.length ?? 0}; {review.remaining?.length ?? 0} still
                need a look.
              </span>
            )}
          </div>
        )}
      </div>
    </>
  );
}
