"use client";

/**
 * VerifyProgressCard — gamified live progress for a Verify & Fix run.
 *
 * Renders during the SSE window from `[smith-verify] verify-intent detected`
 * through `journey_gate` (final summary) or `error`. Reads existing chat
 * store state so it needs no new SSE events:
 *   - status  (streaming.status)         → current activity line
 *   - logs    (streaming.logs)           → phase detection (boot/build)
 *   - journey.results / summary / hints  → per-journey counters + final tally
 *
 * The card feels like a mini quest: five ordered phases with icons that
 * light up as they complete, a moving progress ring, a live counter of
 * journeys passed/failed, and a burst on the final green/orange state.
 * All CSS/transform — no external animation library needed.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Rocket, Package, Waypoints, Wrench, RefreshCw,
  CheckCircle2, AlertTriangle, Loader2, Sparkles, XCircle,
} from "lucide-react";

interface StreamingSlice {
  status: string | null;
  logs: string[];
  journey: {
    results: { slug: string; status: string; duration_ms: number }[];
    summary: { total: number; passed: number; failed: number;
               duration_ms: number; mode: string; ok: boolean } | null;
    hints: { target_seam: string }[];
  };
  /** JV-27 — optional live verify slice. Optional so the /dev preview
   *  page and any test fixtures that predate JV-27 still type-check. */
  verify?: {
    runId: string | null;
    startedAt: number | null;
    progress: { done: number; total: number; currentUrl: string | null } | null;
    recentFaults: {
      id: string;
      interaction_id: string;
      classification: string;
      summary: string;
    }[];
    status: "pending" | "running" | "cancelled" | "done" | "failed" | null;
    /** V&F 2.0 M3 — per-class healed/residual tally. Null on runs
     *  that predate M3 or run without FORGE_AUTOFIX_V2. */
    classProgress?: {
      healed_by_class: Record<string, number>;
      residual_by_class: Record<string, number>;
    } | null;
    /** SV-STRICT — narrated payload piggybacked on verify_end.
     *  Optional so runs older than SV-STRICT still type-check. */
    narrated?: {
      narratives: Array<{
        text: string; priority: string; signature: string;
        w_slot: string; component_id: string; route: string;
        contract_id?: string | null;
      }>;
      by_w_slot: Record<string, Array<{
        text: string; priority: string; signature: string;
        w_slot: string; component_id: string; route: string;
        contract_id?: string | null;
      }>>;
    } | null;
  };
}

interface Props {
  streaming: StreamingSlice;
  /** true while the chat is streaming — hides the card once nothing else
   *  is expected. Passed through from ChatHistory's isStreaming flag. */
  isStreaming?: boolean;
  /** Set when a SMITH_VERIFY_TRIGGER message just landed — tells the card
   *  to show even before the first journey event arrives. */
  verifyActive?: boolean;
  /** JV-27 — the project uuid; needed for the Cancel POST. Optional so
   *  the /dev preview route (no live project) still renders. */
  projectId?: string;
}

type PhaseKey = "kickoff" | "boot" | "walk" | "autofix" | "reverify";

interface Phase {
  key: PhaseKey;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
}

const PHASES: Phase[] = [
  { key: "kickoff",  label: "Kick off",      icon: Rocket },
  { key: "boot",     label: "Boot container",icon: Package },
  { key: "walk",     label: "Walk journeys", icon: Waypoints },
  { key: "autofix",  label: "Auto-fix",      icon: Wrench },
  { key: "reverify", label: "Re-verify",     icon: RefreshCw },
];


export function VerifyProgressCard({
  streaming, isStreaming, verifyActive, projectId,
}: Props) {
  const start = useVerifyStartTimestamp(streaming, verifyActive);
  const verifyStatus = streaming.verify?.status ?? null;
  const isCancelled = verifyStatus === "cancelled";
  const isDone = streaming.journey.summary != null || isCancelled;
  const elapsed = useElapsedSeconds(start, isDone);
  const phase = useMemo(() => derivePhase(streaming), [streaming]);

  // Only render while a verify is actually in flight OR has just finished.
  const hasSignal =
    verifyActive ||
    start != null ||
    streaming.journey.summary != null ||
    streaming.journey.results.length > 0 ||
    !!streaming.verify?.progress ||
    isCancelled;
  if (!hasSignal) return null;

  const progress = streaming.verify?.progress ?? null;
  const recentFaults = streaming.verify?.recentFaults ?? [];
  const passed = streaming.journey.summary?.passed
              ?? streaming.journey.results.filter(r => r.status === "passed").length;
  const failed = streaming.journey.summary?.failed
              ?? streaming.journey.results.filter(r => r.status !== "passed").length;
  const total = streaming.journey.summary?.total
             ?? Math.max(passed + failed, streaming.journey.results.length);
  const hintsByStat = streaming.journey.hints.length;
  const finalOk = streaming.journey.summary?.ok ?? false;

  // JV-27/#2 — ETA. Only show once done>=3 so the estimate isn't jitter,
  // and only during the Walk-journeys phase (progress != null).
  const eta = useMemo(() => {
    if (!progress || !streaming.verify?.startedAt) return null;
    if (progress.done < 3 || progress.total === 0) return null;
    if (progress.done >= progress.total) return null;
    const elapsedMs = Date.now() - streaming.verify.startedAt;
    const perItem = elapsedMs / progress.done;
    const remaining = perItem * (progress.total - progress.done);
    return formatEta(remaining);
  }, [progress, streaming.verify?.startedAt]);

  return (
    <div
      data-verify-chip
      className={`my-2 rounded-lg border shadow-sm overflow-hidden ${
        isCancelled ? "opacity-75" : ""
      }`}
    >
      {/* Header — colored strip */}
      <div className={`px-4 py-2.5 flex items-center justify-between
        ${isCancelled
          ? "bg-muted/40 border-b"
          : isDone
          ? (finalOk
              ? "bg-gradient-to-r from-emerald-50 to-teal-50 border-b border-emerald-200"
              : "bg-gradient-to-r from-orange-50 to-amber-50 border-b border-orange-200")
          : "bg-gradient-to-r from-indigo-50 to-purple-50 border-b border-indigo-200"}`}>
        <div className="flex items-center gap-2 min-w-0">
          {isCancelled ? (
            <XCircle className="h-4 w-4 text-muted-foreground shrink-0" />
          ) : isDone ? (
            finalOk ? (
              <span className="relative inline-flex shrink-0">
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                <Sparkles className="h-3 w-3 text-emerald-400 absolute -top-1 -right-2 animate-pulse" />
              </span>
            ) : (
              <AlertTriangle className="h-4 w-4 text-orange-600 shrink-0" />
            )
          ) : (
            <Loader2 className="h-4 w-4 text-indigo-500 animate-spin shrink-0" />
          )}
          <h3 className={`text-sm font-semibold truncate
            ${isCancelled
              ? "text-muted-foreground"
              : isDone
              ? (finalOk ? "text-emerald-900" : "text-orange-900")
              : "text-indigo-900"}`}>
            {isCancelled
              ? "Verify cancelled"
              : isDone
              ? (finalOk ? "Verify passed" : "Verify complete — issues found")
              : progress
              ? <LiveTitle progress={progress} />
              : "Verifying your app…"}
          </h3>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {eta && !isDone && (
            <span className="text-[10px] text-indigo-700">
              ~{eta} left
            </span>
          )}
          <span className="text-[10px] font-mono text-muted-foreground">
            {elapsed}s
          </span>
          {!isDone && streaming.verify?.runId && projectId && (
            <CancelButton runId={streaming.verify.runId} projectId={projectId} />
          )}
        </div>
      </div>

      {/* JV-27/#1 — live fill bar during the Walk-journeys phase. Thin,
       *  non-decorative — reads exact done/total, no shimmer. */}
      {!isDone && progress && progress.total > 0 && (
        <div className="h-1 bg-muted/50">
          <div
            className="h-full bg-indigo-500 transition-all duration-300 ease-out"
            style={{ width: `${Math.min(100, (progress.done / progress.total) * 100)}%` }}
          />
        </div>
      )}

      {/* Phase pips */}
      <div className="flex items-center gap-1 px-4 pt-3 pb-1">
        {PHASES.map((p, i) => {
          const idx = PHASES.findIndex(x => x.key === phase);
          const state: "past" | "current" | "future" =
            idx > i ? "past" : idx === i ? "current" : "future";
          const Icon = p.icon;
          return (
            <div key={p.key} className="flex items-center flex-1">
              <div className={`shrink-0 rounded-full p-1.5 transition-all duration-500
                ${state === "past"
                  ? "bg-emerald-100 text-emerald-700 scale-100"
                  : state === "current"
                  ? "bg-indigo-100 text-indigo-700 scale-110 ring-2 ring-indigo-300"
                  : "bg-muted text-muted-foreground/40 scale-90"}`}>
                <Icon size={12} className={state === "current" && !isDone ? "animate-pulse" : ""} />
              </div>
              {i < PHASES.length - 1 && (
                <div className={`h-0.5 flex-1 mx-1 transition-colors duration-500
                  ${state === "past" ? "bg-emerald-300" : "bg-muted"}`} />
              )}
            </div>
          );
        })}
      </div>

      {/* Phase labels */}
      <div className="grid grid-cols-5 gap-1 px-4 pb-2 text-[9px] text-center text-muted-foreground">
        {PHASES.map((p) => <div key={p.key}>{p.label}</div>)}
      </div>

      {/* Live activity line */}
      {!isDone && streaming.status && (
        <div className="px-4 py-1.5 text-xs text-muted-foreground border-t bg-muted/20">
          {streaming.status}
        </div>
      )}

      {/* Live counters — only show when we have some journey activity or done */}
      {(streaming.journey.results.length > 0 || isDone) && (
        <div className="grid grid-cols-3 gap-2 px-4 py-3 border-t bg-muted/10">
          <Counter label="Passed" value={passed} accent="emerald" />
          <Counter label="Failed" value={failed} accent={failed > 0 ? "orange" : "muted"} />
          <Counter label="Fix hints" value={hintsByStat} accent={hintsByStat > 0 ? "amber" : "muted"} />
        </div>
      )}

      {/* JV-27/#3 — streaming fault previews (up to 3 rows, +N more). */}
      {!isDone && recentFaults.length > 0 && (
        <RecentFaults faults={recentFaults} />
      )}

      {/* V&F 2.0 M3 — per-class healed/residual strip. Renders only
       *  when the backend emitted a `verify_class_progress` event
       *  (FORGE_AUTOFIX_V2=1 runs). Never renders on older runs. */}
      {streaming.verify?.classProgress && (
        <ClassProgressStrip cp={streaming.verify.classProgress} />
      )}

      {/* Final summary line */}
      {isDone && (
        <div className={`px-4 py-2 text-[11px] border-t
          ${finalOk ? "bg-emerald-50/60 text-emerald-900" : "bg-orange-50/60 text-orange-900"}`}>
          {finalOk
            ? `All ${total} journey${total === 1 ? "" : "s"} passed in ${elapsed}s. `
            : `${failed} of ${total} journey${total === 1 ? "" : "s"} failed. `}
          {!finalOk && hintsByStat > 0 && (
            <span>Autofix dispatched to {hintsByStat} seam{hintsByStat === 1 ? "" : "s"}.</span>
          )}
        </div>
      )}

      {/* SV-STRICT-3b — plain-English fault narratives grouped by W-slot.
       *  Only rendered when the backend piggy-backed a narrated payload
       *  on verify_end (SV-STRICT runs); older runs simply skip. */}
      {isDone && streaming.verify?.narrated && (
        <NarratedFaults narrated={streaming.verify.narrated} />
      )}
    </div>
  );
}


// ── SV-STRICT-3b narrated faults ─────────────────────────────────────────

const W_SLOT_LABEL: Record<string, string> = {
  what: "What broke",
  who: "Access",
  where: "Reachability",
  when: "Trigger",
  how: "Mechanism",
  why: "Promise",
};

const PRIORITY_TONE: Record<string, string> = {
  BLOCKER: "bg-red-100 text-red-800 border-red-200",
  BROKEN: "bg-orange-100 text-orange-800 border-orange-200",
  CONTENT: "bg-amber-100 text-amber-800 border-amber-200",
  FLAKY: "bg-slate-100 text-slate-700 border-slate-200",
};

function NarratedFaults({ narrated }: {
  narrated: {
    narratives: Array<{ text: string; priority: string; w_slot: string; route: string }>;
    by_w_slot: Record<string, Array<{ text: string; priority: string; w_slot: string; route: string }>>;
  };
}) {
  // W-slot render order — most user-visible → most abstract.
  const slotOrder = ["what", "when", "how", "where", "who", "why"];
  const groups = slotOrder
    .map((slot) => ({ slot, items: narrated.by_w_slot?.[slot] || [] }))
    .filter((g) => g.items.length > 0);
  if (groups.length === 0) return null;

  return (
    <div className="border-t bg-slate-50/70 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-600 mb-2">
        What went wrong
      </div>
      <div className="space-y-3">
        {groups.map((g) => (
          <section key={g.slot}>
            <div className="text-[11px] font-medium text-slate-700 mb-1">
              {W_SLOT_LABEL[g.slot] || g.slot} · {g.items.length}
            </div>
            <ul className="space-y-1.5">
              {g.items.map((n, i) => (
                <li key={`${g.slot}-${i}`}
                    className="flex items-start gap-2 text-[11px] leading-snug">
                  <span
                    className={`shrink-0 rounded border px-1.5 py-0.5 text-[9px]
                                uppercase tracking-wide ${
                                  PRIORITY_TONE[n.priority]
                                    || "bg-slate-100 text-slate-700 border-slate-200"
                                }`}
                    title={n.route}
                  >
                    {n.priority}
                  </span>
                  <span className="text-slate-800">{n.text}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}


function LiveTitle({ progress }: {
  progress: { done: number; total: number; currentUrl: string | null };
}) {
  const { done, total, currentUrl } = progress;
  if (!total) return <>Walking journeys…</>;
  return (
    <>
      Walking journeys · <span className="tabular-nums">{done}/{total}</span>
      {currentUrl && (
        <span className="ml-1 font-normal text-indigo-700/80 truncate">
          · currently: {currentUrl}
        </span>
      )}
    </>
  );
}

function CancelButton({ runId, projectId }: { runId: string; projectId: string }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const resetRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (resetRef.current) clearTimeout(resetRef.current); }, []);

  const onClick = async () => {
    if (busy) return;
    if (!confirming) {
      setConfirming(true);
      if (resetRef.current) clearTimeout(resetRef.current);
      resetRef.current = setTimeout(() => setConfirming(false), 3000);
      return;
    }
    setBusy(true);
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL
        || (typeof window !== "undefined"
            && window.location.hostname === "localhost"
            ? "http://localhost:6500"
            : "");
      await fetch(
        `${apiBase}/api/projects/${projectId}/verify/${runId}/cancel`,
        { method: "POST", credentials: "include" },
      );
    } catch {
      /* silent — the chip transitions when the pubsub verify_end lands */
    }
    setBusy(false);
    setConfirming(false);
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
        confirming
          ? "bg-red-50 border-red-300 text-red-700 hover:bg-red-100"
          : "bg-white/60 border-muted-foreground/30 text-muted-foreground hover:bg-white"
      }`}
      title={confirming ? "Click again to confirm" : "Stop this verify run"}
    >
      {busy ? "Cancelling…" : confirming ? "Confirm cancel?" : "Cancel"}
    </button>
  );
}

function RecentFaults({ faults }: {
  faults: { id: string; interaction_id: string; classification: string; summary: string }[];
}) {
  const shown = faults.slice(-3).reverse();
  const more = Math.max(0, faults.length - shown.length);
  return (
    <div className="border-t bg-orange-50/40 px-4 py-2">
      <div className="text-[10px] uppercase tracking-wide text-orange-800/80 mb-1">
        Recent faults
      </div>
      <ul className="space-y-1">
        {shown.map((f) => (
          <li key={f.id} className="flex items-start gap-2 text-[11px]">
            <span className="shrink-0 rounded bg-orange-100 text-orange-800 px-1.5 py-0.5 text-[9px] uppercase tracking-wide">
              {f.classification}
            </span>
            <span className="font-mono text-[10px] text-orange-900/80 shrink-0 truncate max-w-[40%]">
              {f.interaction_id}
            </span>
            <span className="text-orange-900/70 truncate">— {f.summary}</span>
          </li>
        ))}
      </ul>
      {more > 0 && (
        <div className="text-[10px] text-orange-800/70 mt-1">+{more} more</div>
      )}
    </div>
  );
}

function ClassProgressStrip({ cp }: {
  cp: {
    healed_by_class: Record<string, number>;
    residual_by_class: Record<string, number>;
  };
}) {
  const healedEntries = Object.entries(cp.healed_by_class ?? {});
  const residualEntries = Object.entries(cp.residual_by_class ?? {});
  if (healedEntries.length === 0 && residualEntries.length === 0) return null;
  return (
    <div className="px-4 py-2 text-[11px] border-t bg-muted/10">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
        Self-healing
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {healedEntries.map(([cls, n]) => (
          <span key={`h:${cls}`} className="text-emerald-700">
            ✓ {n} {cls} healed
          </span>
        ))}
        {residualEntries.map(([cls, n]) => (
          <span key={`r:${cls}`} className="text-amber-700">
            ! {n} {cls} for you
          </span>
        ))}
      </div>
    </div>
  );
}

function formatEta(ms: number): string {
  const s = Math.max(1, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  return `${m} min`;
}

function Counter({ label, value, accent }: {
  label: string; value: number;
  accent: "emerald" | "orange" | "amber" | "muted";
}) {
  const cls = {
    emerald: "text-emerald-700",
    orange:  "text-orange-700",
    amber:   "text-amber-700",
    muted:   "text-muted-foreground",
  }[accent];
  return (
    <div className="text-center">
      <div className={`text-lg font-semibold tabular-nums transition-colors ${cls}`}>
        {value}
      </div>
      <div className="text-[9px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
    </div>
  );
}


/** Snap the first time we see any signal that verify has started, hold it
 *  through the run, reset when verifyActive drops back to false. */
function useVerifyStartTimestamp(
  streaming: StreamingSlice,
  verifyActive?: boolean,
): number | null {
  const [start, setStart] = useState<number | null>(null);
  useEffect(() => {
    if (verifyActive || streaming.journey.results.length > 0 || streaming.journey.summary) {
      setStart((prev) => prev ?? Date.now());
    } else if (!verifyActive && !streaming.journey.summary
               && streaming.journey.results.length === 0) {
      // Fully reset only when nothing is happening.
      setStart(null);
    }
  }, [verifyActive, streaming.journey.results.length, streaming.journey.summary]);
  return start;
}

/** Live seconds counter. Freezes when `frozen` (i.e., done). */
function useElapsedSeconds(start: number | null, frozen: boolean): number {
  const [now, setNow] = useState<number>(Date.now());
  useEffect(() => {
    if (start == null || frozen) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [start, frozen]);
  if (start == null) return 0;
  return Math.max(0, Math.round((now - start) / 1000));
}

/** Infer the current phase from what's visible in the streaming state.
 *  Kept as a pure function so it's trivially unit-testable when we care. */
function derivePhase(s: StreamingSlice): PhaseKey {
  if (s.journey.summary) {
    // Done state — highlight re-verify if we saw autofix, otherwise walk.
    return s.journey.hints.length > 0 ? "reverify" : "walk";
  }
  const logs = s.logs.join("\n").toLowerCase();
  if (logs.includes("re-run") || logs.includes("second run")) return "reverify";
  if (logs.includes("autofix") || logs.includes("wired")) return "autofix";
  // JV-27 — verify_progress events tell us Playwright is actively walking
  // journeys; that beats waiting for the log-string heuristic to hit and
  // beats waiting for journey.results (which is per-journey summaries the
  // sidecar doesn't emit today).
  if (s.verify?.progress && s.verify.progress.done > 0) return "walk";
  if (s.journey.results.length > 0) return "walk";
  if (logs.includes("booted") || logs.includes("compose")
      || logs.includes("container") || logs.includes("building")) return "boot";
  // If the run has a runId but no progress yet, we're between kickoff and
  // walk — that's boot. Cheap heuristic that matches what the user sees:
  // Cancel button already rendering + counter still at 0.
  if (s.verify?.runId && !s.verify.progress) return "boot";
  return "kickoff";
}
