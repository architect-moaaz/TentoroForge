/**
 * A step that has gone quiet, said in words.
 *
 * A model call that is slow but alive looked exactly like one that hung: the
 * stage line stayed put and only the clock moved. After a while with nothing
 * landing, the panel says so — the build is still working, this step is just
 * long. A call that actually fails is a different state ("waiting for the
 * API"), drawn from the run's own moments; this is only about silence.
 */
import type { BlueprintRun } from "@/hooks/useBlueprintRun";

/** Quiet this long before the note appears. */
export const SLOW_STEP_MS = 3 * 60 * 1000;

/** Everything whose change means the build moved: a step or a call landing,
 *  a step starting, a page reviewed, a thought streamed. Heartbeats are not
 *  progress and never reach the reducer. */
export function progressMark(run: BlueprintRun): string {
  const running = run.nodes
    .filter((n) => n.state === "running")
    .map((n) => `${n.key}:${n.subject ?? ""}`)
    .join(",");
  return [
    run.status, run.nodesDone, run.callsDone, running,
    run.moments?.length ?? 0, run.events.length, run.thoughts.length,
  ].join("|");
}

/** `3m 20s`, or `45s`. */
function quietFor(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return s >= 60 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
}

/** The note for a step quiet for `quietMs`, or null while it is not slow. */
export function slowStepNote(quietMs: number): string | null {
  if (quietMs < SLOW_STEP_MS) return null;
  return `This step is taking longer than usual (nothing new for ${quietFor(quietMs)}). ` +
    "It's still working; long steps can take several minutes.";
}
