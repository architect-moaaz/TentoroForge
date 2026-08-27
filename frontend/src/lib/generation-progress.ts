/**
 * Live progress + ETA computation for a Forge generation run.
 *
 * A generation is one "planning" phase (pre-QUEST_PHASES, no phase index
 * yet — status messages like "Planning your application…" fire but
 * detectPhaseIndex returns -1) followed by 9 quest phases (contracts →
 * foundation → backend → components → pages → seed → qa → validate →
 * index). Each has an empirical baseline duration.
 *
 * ETA math (pure, no I/O):
 *   completedBase = Σ baseline of completedPhaseIndices
 *   currentBase   = baseline of activePhaseIndex (or 0)
 *   elapsed       = now − startedAt
 *   partial       = min(elapsed − Σ (actual completed) , currentBase)
 *                   OR currentBase × 0.5 if we lack per-phase start times
 *   percent       = (completedBase + partial) / totalBase × 100
 *   scale         = elapsed / (completedBase + partial)  ← refines as
 *                   more phases complete; falls back to 1.0 on cold start
 *   remaining     = (totalBase − completedBase − partial) × scale
 *
 * Cold start (no completed phases) uses baseline verbatim. First few
 * phases the ETA can drift wildly — the smoothing in the ring component
 * dampens visual jitter.
 */

export interface PhaseBaseline {
  /** Matches QuestPhase.id from lib/quest-phases.ts, or "planning" for the
   *  pre-quest planning + discovery + design-research phase. */
  id: string;
  /** Baseline seconds (empirical median of recent runs; edit here to
   *  refine). Kept as a plain constant — no runtime tuning yet. */
  seconds: number;
}

/** Empirical baselines. Planning (discovery + design research + the plan
 *  stream) is the longest pre-build phase — it was badly under-weighted at 60s,
 *  which is why the ring shot to ~13% and then FROZE there for the whole
 *  (multi-minute) planning window. 180s reflects reality and, with the
 *  asymptotic fill below, keeps the bar moving throughout planning. */
export const PHASE_BASELINES: PhaseBaseline[] = [
  { id: "planning",   seconds: 180 },
  { id: "contracts",  seconds: 30 },
  { id: "foundation", seconds: 60 },
  { id: "backend",    seconds: 90 },
  { id: "components", seconds: 45 },
  { id: "pages",      seconds: 90 },
  { id: "seed",       seconds: 15 },
  { id: "qa",         seconds: 30 },
  { id: "validate",   seconds: 20 },
  { id: "index",      seconds: 15 },
];

export const TOTAL_BASELINE_SECONDS = PHASE_BASELINES.reduce(
  (s, p) => s + p.seconds,
  0,
);

/** QUEST_PHASES phase indices map to indices 1..9 in PHASE_BASELINES
 *  (planning is 0). Kept as a helper so callers don't drift. */
export function baselineIndexFromQuestIndex(questIndex: number): number {
  // questIndex = -1 (planning) → 0 ; questIndex = 0 (contracts) → 1 ; etc.
  return questIndex + 1;
}

export interface ProgressInputs {
  /** Wall-clock ms when the generation started (chat.ts:startStreaming). */
  startedAt: number | null;
  /** Current wall-clock ms (usually Date.now(); passed in for testability). */
  now: number;
  /** From chat store's quest.activePhaseIndex — -1 during planning, 0-8
   *  during a quest phase, or 9 (all done). */
  activeQuestIndex: number;
  /** From chat store's quest.completedPhaseIndices — QUEST_PHASES indices
   *  (0-8) that have already been marked complete. */
  completedQuestIndices: number[];
  /** Per-phase start times, phaseIndex → ms. -1 for planning, 0-8 for
   *  quest phases. Optional; when absent we heuristic-partial the
   *  current phase at 50%. */
  phaseStartTimes?: Record<number, number>;
  /** True once the run is complete (chat.ts handleSSEEvent "complete"). */
  isComplete?: boolean;
}

export interface ProgressResult {
  /** 0-100. Rounded. */
  percent: number;
  /** Estimated remaining seconds; null when we don't have enough signal
   *  yet (streaming hasn't started, or we're in indeterminate state). */
  etaSeconds: number | null;
  /** Elapsed seconds since startedAt; null when startedAt is null. */
  elapsedSeconds: number | null;
  /** Human-readable ETA (e.g. "~2m 30s", "~15s", "almost done"). */
  etaLabel: string;
  /** True when we lack enough signal to give a real % — the ring should
   *  render an indeterminate spinner instead. */
  isIndeterminate: boolean;
}

function _baselineForQuestIndex(questIndex: number): number {
  const bi = baselineIndexFromQuestIndex(questIndex);
  if (bi < 0 || bi >= PHASE_BASELINES.length) return 0;
  return PHASE_BASELINES[bi].seconds;
}

export function computeGenerationProgress(inp: ProgressInputs): ProgressResult {
  const { startedAt, now, activeQuestIndex, completedQuestIndices, phaseStartTimes, isComplete } = inp;

  if (isComplete) {
    return {
      percent: 100,
      etaSeconds: 0,
      elapsedSeconds: startedAt ? Math.floor((now - startedAt) / 1000) : null,
      etaLabel: "done",
      isIndeterminate: false,
    };
  }

  if (startedAt == null) {
    return {
      percent: 0,
      etaSeconds: null,
      elapsedSeconds: null,
      etaLabel: "starting…",
      isIndeterminate: true,
    };
  }

  const elapsedSec = Math.max(0, (now - startedAt) / 1000);

  // Sum baselines of completed quest phases.
  const completedBase = completedQuestIndices.reduce(
    (s, qi) => s + _baselineForQuestIndex(qi),
    0,
  );

  // Baseline of the currently-active phase (or 0 if none).
  const currentBase = activeQuestIndex >= -1
    ? _baselineForQuestIndex(activeQuestIndex)
    : 0;

  // Partial completion of the current phase — ASYMPTOTIC so it never freezes.
  let partial = 0;
  if (currentBase > 0) {
    const currentStart = phaseStartTimes?.[activeQuestIndex];
    // Elapsed WITHIN the current phase: exact if we have per-phase start times,
    // otherwise estimated as total elapsed minus the baseline of finished phases.
    const phaseElapsed = currentStart
      ? Math.max(0, (now - currentStart) / 1000)
      : Math.max(0, elapsedSec - completedBase);
    // Approaches currentBase but never reaches/caps it: a phase that overruns its
    // baseline keeps the bar CREEPING forward instead of pinning (the "stuck at
    // 13%" freeze). phaseElapsed==baseline → 50%, 3× → 75%; always increasing.
    partial = currentBase * (phaseElapsed / (phaseElapsed + currentBase));
  }

  const virtualDone = completedBase + partial;
  const percentRaw = (virtualDone / TOTAL_BASELINE_SECONDS) * 100;
  // Cap at 99% until "complete" fires — a ring pinned at 100% before the
  // final event lands looks misleading.
  const percent = Math.min(99, Math.max(0, Math.round(percentRaw)));

  // Scale: how does actual elapsed compare to what baseline predicts?
  // If elapsed is 1.5× predicted, remaining time scales up too.
  const scale = virtualDone > 0 ? Math.max(0.5, Math.min(3, elapsedSec / virtualDone)) : 1;

  const remainingBase = Math.max(
    0,
    TOTAL_BASELINE_SECONDS - completedBase - partial,
  );
  const etaSeconds = Math.round(remainingBase * scale);

  // Very early: activeQuestIndex still -2 or startedAt just now → don't
  // pretend to know an ETA. Show indeterminate.
  const isIndeterminate =
    activeQuestIndex < -1 || (elapsedSec < 2 && completedQuestIndices.length === 0);

  return {
    percent,
    etaSeconds: isIndeterminate ? null : etaSeconds,
    elapsedSeconds: Math.floor(elapsedSec),
    etaLabel: isIndeterminate ? "starting…" : formatEta(etaSeconds),
    isIndeterminate,
  };
}

/** "3m 20s", "45s", "~1s", "almost done" */
export function formatEta(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s <= 3) return "almost done";
  if (s < 60) return `~${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r === 0 ? `~${m}m` : `~${m}m ${r}s`;
}

/** "0:45", "3:20" — for the elapsed counter. */
export function formatElapsed(seconds: number | null | undefined): string {
  if (seconds == null) return "";
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}
