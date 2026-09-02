"use client";

import { useOfficeStore } from "../OfficeStateManager";
import { AGENT_REGISTRY, DEPARTMENTS, PHASE_ROOM_MAP } from "../types";

/** Which agents sit in each department, resolved once. */
const AGENTS_BY_ROOM: Record<string, string[]> = DEPARTMENTS.reduce(
  (acc, d) => {
    acc[d.id] = AGENT_REGISTRY.filter((a) => a.room === d.id).map((a) => a.id);
    return acc;
  },
  {} as Record<string, string[]>,
);

type Fill = "idle" | "active" | "done" | "parked";

export function PipelineProgress() {
  const agents = useOfficeStore((s) => s.agents);
  const activeAgents = useOfficeStore((s) => s.activeAgents);
  const roster = useOfficeStore((s) => s.roster);
  const activePhase = useOfficeStore((s) => s.activePhase);
  const completedPhases = useOfficeStore((s) => s.completedPhases);
  const totalProgress = useOfficeStore((s) => s.totalProgress);
  const nodesDone = useOfficeStore((s) => s.nodesDone);
  const nodesPlanned = useOfficeStore((s) => s.nodesPlanned);

  // A department's state is the state of the people in it. Under a DAG run
  // only rostered agents count — an empty department on an incremental run is
  // not "pending", it is simply not part of this change.
  const fillOf = (roomId: string): Fill => {
    const members = AGENTS_BY_ROOM[roomId] ?? [];
    const onDuty = roster.size === 0 ? members : members.filter((id) => roster.has(id));
    if (onDuty.length === 0) return "idle";
    if (onDuty.some((id) => activeAgents.has(id))) return "active";

    const states = onDuty.map((id) => agents.get(id)?.getState().state);
    if (states.some((st) => st === "blocked" || st === "skipped" || st === "error")) {
      return "parked";
    }
    // The relay drives phases rather than a roster, so fall back to it.
    if (roster.size === 0) {
      const phase = Object.entries(PHASE_ROOM_MAP).find(
        ([p, r]) => r === roomId && completedPhases.has(p),
      );
      return phase ? "done" : "idle";
    }
    return states.every((st) => st === "idle") && nodesDone > 0 ? "done" : "idle";
  };

  // The label names what is happening, not where — a room id tells the user
  // nothing they cannot already see on the floor.
  const workingIn = DEPARTMENTS.filter((d) => fillOf(d.id) === "active");
  const label = workingIn.length
    ? workingIn.map((d) => d.label).join(" + ")
    : activePhase
      ? activePhase.replace(/_/g, " ")
      : "Idle";

  return (
    <div className="bg-gray-900/80 backdrop-blur-sm border-b border-gray-700/50 px-4 py-2">
      <div className="flex items-center gap-3">
        <span className="text-xs text-gray-400 font-medium whitespace-nowrap max-w-[180px] truncate">
          {label}
        </span>

        {/* One segment per department, in DAG order */}
        <div className="flex-1 flex items-center gap-0.5 h-3 rounded-full overflow-hidden bg-gray-800">
          {DEPARTMENTS.map((dept) => {
            const fill = fillOf(dept.id);
            return (
              <div
                key={dept.id}
                className={`h-full flex-1 transition-colors duration-300 ${
                  fill === "active" ? "animate-pulse" : ""
                }`}
                style={{
                  backgroundColor:
                    fill === "done"
                      ? dept.color
                      : fill === "active"
                        ? `${dept.color}99`
                        : fill === "parked"
                          ? "#64748b66"
                          : "transparent",
                }}
                title={`${dept.label} — ${dept.description}`}
              />
            );
          })}
        </div>

        {/* Node count when a DAG run declared a plan, percentage otherwise */}
        <span className="text-xs text-gray-300 font-mono min-w-[52px] text-right">
          {nodesPlanned > 0
            ? `${nodesDone}/${nodesPlanned}`
            : `${Math.round(totalProgress)}%`}
        </span>
      </div>
    </div>
  );
}

export default PipelineProgress;
