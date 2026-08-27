"use client";
/**
 * Circular progress ring for a Forge generation run.
 *
 * Reads chat store's quest.streamStartedAt + activePhaseIndex +
 * completedPhaseIndices + phaseStartTimes and computes a live %
 * completion + ETA every ~500ms via computeGenerationProgress. Renders
 * an SVG ring with the % in the center and the ETA underneath. When
 * we don't have enough signal (streaming just started, no phase yet),
 * shows an indeterminate spinning arc.
 *
 * Sits inside SSEStatusBar (ChatHistory.tsx) in place of the plain
 * <Loader2 /> spinner while streaming.isStreaming is true.
 */

import { useEffect, useRef, useState } from "react";
import {
  computeGenerationProgress,
  formatElapsed,
} from "@/lib/generation-progress";
import { useChatStore } from "@/stores/chat";

interface GenerationRingProps {
  /** Ring diameter in px. Default 44 — matches the SSEStatusBar height. */
  size?: number;
  /** Ring stroke width. Default 4. */
  stroke?: number;
  /** Compact mode drops the elapsed counter under the ETA (used inside
   *  the tight status row). */
  compact?: boolean;
}

export function GenerationRing({
  size = 44,
  stroke = 4,
  compact,
}: GenerationRingProps) {
  const quest = useChatStore((s) => s.quest);
  const isStreaming = useChatStore((s) => s.streaming.isStreaming);

  // Tick every 500ms so the ring animates smoothly during long phases.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isStreaming) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [isStreaming]);

  // Fix #3/#4/#7 — prefer authoritative progress from the backend
  // `progress` SSE event. When present, no interpolation, no guessing.
  // Fall back to the baseline-based interpolation only for the pre-
  // progress window (before the first event arrives) and for older
  // backends that don't emit the event.
  const interpolated = computeGenerationProgress({
    startedAt: quest.streamStartedAt,
    now,
    activeQuestIndex: quest.activePhaseIndex,
    completedQuestIndices: quest.completedPhaseIndices,
    phaseStartTimes: quest.phaseStartTimes,
    isComplete: false, // completion state comes via a separate "complete" event
  });
  const authoritative = quest.progress;
  const elapsedSec = quest.streamStartedAt
    ? Math.floor((now - quest.streamStartedAt) / 1000)
    : null;
  const rawProgress = authoritative
    ? {
        percent: authoritative.overallPercent,
        etaSeconds: authoritative.etaSeconds,
        etaLabel: formatEtaLabel(authoritative.etaSeconds),
        elapsedSeconds: elapsedSec,
        isIndeterminate: false,
      }
    : interpolated;

  // Bug B-020.3/7: raw ETA jitters (7min → 13min → 11min → 15min …)
  // because a per-phase scale factor jumps when phases complete out of
  // baseline order. Users read that as "the platform is lying about
  // time". Smooth it: within a single run, the displayed ETA can only
  // trend downward (drift at most +30s per tick, so it stays honest
  // when a real slowdown genuinely stretches the estimate) and the
  // percent can only go up. Reset on a new streamStartedAt.
  //
  // Exception: when the backend recalibrates (e.g. plan lands and the
  // frontend_schema baseline goes from 120s to 900s for a 30-page app),
  // the raw ETA can honestly leap by minutes at once. The +30s/tick
  // ceiling would then take ages to catch reality, which is the "51%
  // for 18m" mirage. So if the raw ETA exceeds the current ceiling by
  // more than the drift allowance, accept the jump immediately — the
  // backend has better information than us.
  const ceilingRef = useRef<{
    startedAt: number | null;
    etaSeconds: number | null;
    percent: number;
  }>({ startedAt: null, etaSeconds: null, percent: 0 });
  if (quest.streamStartedAt !== ceilingRef.current.startedAt) {
    ceilingRef.current = {
      startedAt: quest.streamStartedAt ?? null,
      etaSeconds: null,
      percent: 0,
    };
  }
  let smoothedEtaSeconds = rawProgress.etaSeconds;
  if (
    typeof smoothedEtaSeconds === "number" &&
    typeof ceilingRef.current.etaSeconds === "number"
  ) {
    const DRIFT_ALLOWANCE_SEC = 30;
    const RECAL_JUMP_THRESHOLD_SEC = 90; // > this = the backend recalibrated
    const raw = smoothedEtaSeconds;
    const prev = ceilingRef.current.etaSeconds;
    if (raw > prev + RECAL_JUMP_THRESHOLD_SEC) {
      // Trust the leap — the ceiling is stale.
      smoothedEtaSeconds = raw;
    } else {
      // Small rise / any fall → apply the usual anti-jitter cap.
      smoothedEtaSeconds = Math.min(raw, prev - 1 + DRIFT_ALLOWANCE_SEC);
    }
    smoothedEtaSeconds = Math.max(0, smoothedEtaSeconds);
  }
  ceilingRef.current.etaSeconds = smoothedEtaSeconds;
  const monotonicPercent = Math.max(rawProgress.percent, ceilingRef.current.percent);
  ceilingRef.current.percent = monotonicPercent;

  const progress = {
    ...rawProgress,
    percent: monotonicPercent,
    etaSeconds: smoothedEtaSeconds,
    etaLabel: rawProgress.isIndeterminate
      ? rawProgress.etaLabel
      : smoothedEtaSeconds == null
        ? rawProgress.etaLabel
        : formatEtaLabel(smoothedEtaSeconds),
  };

  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset =
    progress.isIndeterminate
      ? circumference * 0.75 // shows 25% arc when indeterminate
      : circumference * (1 - progress.percent / 100);

  return (
    <div
      className="relative flex items-center justify-center shrink-0"
      style={{ width: size, height: size }}
      role="progressbar"
      aria-valuenow={progress.isIndeterminate ? undefined : progress.percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={
        progress.isIndeterminate
          ? "Generation starting"
          : `Generation ${progress.percent}% complete, ETA ${progress.etaLabel}`
      }
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className={progress.isIndeterminate ? "animate-spin" : undefined}
        style={{ animationDuration: "1.6s" }}
      >
        {/* Track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={stroke}
          className="text-muted-foreground/20"
        />
        {/* Progress arc */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          className="text-primary transition-[stroke-dashoffset] duration-500 ease-linear"
        />
      </svg>
      {/* Center label */}
      <div className="absolute inset-0 flex items-center justify-center">
        {progress.isIndeterminate ? (
          <span className="text-[9px] font-medium text-muted-foreground">
            …
          </span>
        ) : (
          <span
            className="font-semibold tabular-nums text-foreground"
            style={{ fontSize: Math.max(9, Math.round(size * 0.28)) }}
          >
            {progress.percent}%
          </span>
        )}
      </div>

      {/* ETA + elapsed as a floating right-side pair for larger rings */}
      {!compact && !progress.isIndeterminate && size >= 60 && (
        <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 leading-tight whitespace-nowrap text-[10px] text-muted-foreground">
          <div title="Estimated remaining time. May take longer during peak load or with complex apps.">
            ~{progress.etaLabel}
          </div>
          {progress.elapsedSeconds != null && (
            <div className="tabular-nums opacity-70">
              {formatElapsed(progress.elapsedSeconds)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Format ETA seconds as "12m 30s" / "45s" — kept local because the shared
 * lib helper is package-private. */
function formatEtaLabel(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}
