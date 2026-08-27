"use client";

import { useOfficeStore } from "../OfficeStateManager";

const PHASES = [
  { key: "planning", label: "Planning", color: "#3B82F6" },
  { key: "schema", label: "Schema", color: "#8B5CF6" },
  { key: "auth", label: "Auth", color: "#DC2626" },
  { key: "api", label: "API", color: "#EA580C" },
  { key: "business_logic", label: "Logic", color: "#4F46E5" },
  { key: "components", label: "UI", color: "#EC4899" },
  { key: "qa", label: "QA", color: "#0891B2" },
  { key: "indexing", label: "Index", color: "#92400E" },
];

export function PipelineProgress() {
  const activePhase = useOfficeStore((s) => s.activePhase);
  const completedPhases = useOfficeStore((s) => s.completedPhases);
  const totalProgress = useOfficeStore((s) => s.totalProgress);

  return (
    <div className="bg-gray-900/80 backdrop-blur-sm border-b border-gray-700/50 px-4 py-2">
      <div className="flex items-center gap-3">
        {/* Phase label */}
        <span className="text-xs text-gray-400 font-medium whitespace-nowrap min-w-[60px]">
          {activePhase
            ? PHASES.find((p) => p.key === activePhase)?.label ?? activePhase
            : "Idle"}
        </span>

        {/* Segmented progress bar */}
        <div className="flex-1 flex items-center gap-0.5 h-3 rounded-full overflow-hidden bg-gray-800">
          {PHASES.map((phase) => {
            const isComplete = completedPhases.has(phase.key);
            const isActive = activePhase === phase.key;

            return (
              <div
                key={phase.key}
                className={`h-full flex-1 transition-colors duration-300 ${
                  isActive ? "animate-pulse" : ""
                }`}
                style={{
                  backgroundColor: isComplete
                    ? phase.color
                    : isActive
                      ? `${phase.color}99`
                      : "transparent",
                }}
                title={phase.label}
              />
            );
          })}
        </div>

        {/* Percentage */}
        <span className="text-xs text-gray-300 font-mono min-w-[40px] text-right">
          {Math.round(totalProgress)}%
        </span>
      </div>
    </div>
  );
}

export default PipelineProgress;
