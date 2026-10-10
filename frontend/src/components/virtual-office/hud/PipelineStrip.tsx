"use client";

import { useOfficeStore } from "../OfficeStateManager";
import { PIPELINE } from "../types";

/** Where the build is, stage by stage — the engineer's journal as a strip:
 *  Define → Model → Opening → Features (n of m, which) → Sweep → Whole app →
 *  Handover; and Smith's turn at the Front Desk when a person is talking. */
export function PipelineStrip() {
  const pipeline = useOfficeStore((s) => s.pipeline);
  const smith = useOfficeStore((s) => s.smith);
  const trials = useOfficeStore((s) => s.trials);

  const stage = pipeline.stage;
  const currentIdx = PIPELINE.findIndex((p) => stage !== null && p.stages.includes(stage));
  const stopped = stage === "stopped";

  // Nothing has happened yet: say what the strip is rather than draw an
  // empty one.
  const quiet = stage === null && !smith.inTurn;

  return (
    <div className="bg-gray-900/85 backdrop-blur-sm border-b border-gray-700/50 px-4 py-1.5">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1 shrink-0">
          {PIPELINE.map((p, i) => {
            const done = currentIdx > i && !stopped;
            const here = currentIdx === i;
            const isFeatures = p.id === "features";
            const text = isFeatures && pipeline.total
              ? `Features ${Math.min(pipeline.done.length + (here ? 1 : 0), pipeline.total)}/${pipeline.total}`
              : p.label;
            return (
              <div key={p.id} className="flex items-center gap-1">
                <span
                  title={p.label}
                  className={`text-[11px] px-2 py-0.5 rounded-full border transition-colors ${
                    here && stopped
                      ? "border-red-400/70 bg-red-500/20 text-red-200"
                      : here
                        ? "border-emerald-400/70 bg-emerald-500/20 text-emerald-100 animate-pulse"
                        : done
                          ? "border-emerald-700/60 bg-emerald-900/30 text-emerald-300"
                          : "border-gray-700 text-gray-500"
                  }`}
                >
                  {text}
                </span>
                {i < PIPELINE.length - 1 && <span className="text-gray-600 text-[10px]">›</span>}
              </div>
            );
          })}
        </div>

        <span className={`text-xs truncate flex-1 ${stopped ? "text-red-300" : "text-gray-300"}`}>
          {quiet
            ? "The build moves left to right; Smith works the Front Desk between builds."
            : smith.inTurn
              ? `Smith${smith.mode === "unattended" ? " (for the engineer)" : ""}: ${
                  smith.step?.said || smith.text || "taking a look"
                }`
              : pipeline.name && (stage === "feature" || stage === "proof" || stage === "fix")
                ? `${pipeline.name} — ${pipeline.label}`
                : pipeline.label}
        </span>

        {trials.tried > 0 && (
          <span className="text-[11px] font-mono text-gray-300 shrink-0" title="Statements tried on the Workbench">
            <span className="text-emerald-300">{trials.passed} held</span>
            {trials.failed > 0 && <span className="text-red-300"> · {trials.failed} failed</span>}
            {trials.untried > 0 && <span className="text-gray-400"> · {trials.untried} untried</span>}
          </span>
        )}
      </div>
    </div>
  );
}

export default PipelineStrip;
