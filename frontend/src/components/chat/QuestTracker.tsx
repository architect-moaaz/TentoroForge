"use client";

import {
  Swords,
  Sparkles,
  CheckCircle2,
  Loader2,
  Circle,
  FileCode2,
  Wrench,
  Coins,
} from "lucide-react";
import { QUEST_PHASES, getDisplayPhases, DESIGN_UI_PHASE } from "@/lib/quest-phases";
import type { QuestState } from "@/stores/chat";

interface QuestTrackerProps {
  quest: QuestState;
  streaming: {
    filesCreated: string[];
    toolCalls: { tool: string; args: string }[];
    status: string | null;
  };
}

export function QuestTracker({ quest, streaming }: QuestTrackerProps) {
  const displayPhases = getDisplayPhases(quest.isDesign);
  const maxXp = displayPhases.reduce((sum, p) => sum + p.xp, 0);
  const xpPercent = maxXp > 0 ? Math.min((quest.totalXp / maxXp) * 100, 100) : 0;

  // Map original phase indices to display-phase status
  function getPhaseStatus(phase: typeof displayPhases[number]) {
    if (phase.id === "design-ui") {
      // The design phase is "active" if either components or pages is active
      const compIdx = QUEST_PHASES.findIndex((p) => p.id === "components");
      const pagesIdx = QUEST_PHASES.findIndex((p) => p.id === "pages");
      const isCompleted =
        quest.completedPhaseIndices.includes(compIdx) &&
        quest.completedPhaseIndices.includes(pagesIdx);
      const isActive =
        !isCompleted &&
        (quest.activePhaseIndex === compIdx || quest.activePhaseIndex === pagesIdx);
      return isCompleted ? "completed" : isActive ? "active" : "pending";
    }
    const originalIdx = QUEST_PHASES.findIndex((p) => p.id === phase.id);
    if (quest.completedPhaseIndices.includes(originalIdx)) return "completed";
    if (quest.activePhaseIndex === originalIdx) return "active";
    return "pending";
  }

  function getPhaseXp(phase: typeof displayPhases[number]) {
    if (phase.id === "design-ui") return DESIGN_UI_PHASE.xp;
    return phase.xp;
  }

  return (
    <div className="border-t px-4 py-3">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold text-amber-800">
          <Swords className="h-4 w-4" />
          QUEST LOG
        </div>
        <div className="flex items-center gap-1 text-sm font-semibold text-amber-600">
          <Sparkles className="h-3.5 w-3.5" />
          {quest.totalXp} XP
        </div>
      </div>

      {/* XP Progress bar */}
      <div className="mb-3 h-2 overflow-hidden rounded-full bg-amber-100">
        <div
          className="xp-bar-glow h-full rounded-full bg-gradient-to-r from-amber-400 to-amber-500 transition-all duration-700 ease-out"
          style={{ width: `${xpPercent}%` }}
        />
      </div>

      {/* Phase list */}
      <div className="mb-3 space-y-1">
        {displayPhases.map((phase) => {
          const status = getPhaseStatus(phase);
          const Icon = phase.icon;
          const xp = getPhaseXp(phase);

          return (
            <div
              key={phase.id}
              className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors ${
                status === "active"
                  ? "bg-blue-50 text-blue-800"
                  : status === "completed"
                    ? "text-green-700"
                    : "text-muted-foreground"
              }`}
            >
              {/* Status icon */}
              {status === "completed" && (
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-500" />
              )}
              {status === "active" && (
                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500" />
              )}
              {status === "pending" && (
                <Circle className="h-3.5 w-3.5 shrink-0 text-gray-300" />
              )}

              {/* Phase icon */}
              <Icon className="h-3.5 w-3.5 shrink-0" />

              {/* Quest name */}
              <span className="flex-1 font-medium">{phase.questName}</span>

              {/* XP badge */}
              {status === "completed" && (
                <span className="animate-in fade-in rounded-full bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold text-green-700">
                  +{xp} XP
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Loot stats bar */}
      <div className="mb-2 flex items-center gap-4 text-[10px] text-muted-foreground">
        {streaming.filesCreated.length > 0 && (
          <div className="flex items-center gap-1">
            <FileCode2 className="h-3 w-3 text-green-500" />
            <span>{streaming.filesCreated.length} files</span>
          </div>
        )}
        {streaming.toolCalls.length > 0 && (
          <div className="flex items-center gap-1">
            <Wrench className="h-3 w-3 text-blue-500" />
            <span>{streaming.toolCalls.length} actions</span>
          </div>
        )}
        {quest.completionStats?.totalCost ? (
          <div className="flex items-center gap-1">
            <Coins className="h-3 w-3 text-amber-500" />
            <span>${quest.completionStats.totalCost.toFixed(2)}</span>
          </div>
        ) : null}
      </div>

      {/* Current status line */}
      {streaming.status && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" />
          {streaming.status}
        </div>
      )}
    </div>
  );
}
