"use client";

import { X, FileCode, MessageCircle, Lock, RotateCcw, MoveRight } from "lucide-react";
import { useOfficeStore } from "../OfficeStateManager";
import { AGENT_BY_ID, DEPARTMENT_BY_ID } from "../types";

export function AgentPanel() {
  const selectedAgent = useOfficeStore((s) => s.selectedAgent);
  const agents = useOfficeStore((s) => s.agents);
  const events = useOfficeStore((s) => s.events);
  const selectAgent = useOfficeStore((s) => s.selectAgent);
  const roster = useOfficeStore((s) => s.roster);
  const blockedReasons = useOfficeStore((s) => s.blockedReasons);
  const skippedReasons = useOfficeStore((s) => s.skippedReasons);

  if (!selectedAgent) return null;

  const agent = agents.get(selectedAgent);
  const agentState = agent?.getState();
  const agentInfo = AGENT_BY_ID[selectedAgent];

  if (!agentInfo) return null;

  const department = DEPARTMENT_BY_ID[agentInfo.room];
  const parked =
    blockedReasons.get(selectedAgent) ?? skippedReasons.get(selectedAgent) ?? null;
  const isBlocked = blockedReasons.has(selectedAgent);
  const onDuty = roster.size === 0 || roster.has(selectedAgent);

  // Where this agent's finished work went this run — the DAG's outgoing edges,
  // read off the deliveries that actually left this desk.
  const deliveredTo = Array.from(
    new Set(
      events
        .filter((e) => e.type === "artifact_delivery" && e.from === selectedAgent)
        .map((e) => (e.type === "artifact_delivery" ? e.to : ""))
        .filter(Boolean),
    ),
  ).slice(-6);

  const stateLabel = agentState
    ? agentState.state.charAt(0).toUpperCase() + agentState.state.slice(1)
    : "Unknown";

  // Gather recent speech bubble messages for this agent from events
  const recentMessages = events
    .filter(
      (e) =>
        (e.type === "agent_status" && e.agent === selectedAgent) ||
        (e.type === "agent_error" && e.agent === selectedAgent),
    )
    .slice(-5)
    .map((e) => {
      if (e.type === "agent_status") return { text: e.status, type: "status" as const };
      if (e.type === "agent_error") return { text: e.message, type: "error" as const };
      return null;
    })
    .filter(Boolean) as { text: string; type: "status" | "error" }[];

  // Count files generated from complete events
  const filesGenerated = events
    .filter(
      (e) => e.type === "agent_complete" && e.agent === selectedAgent && e.files_generated,
    )
    .reduce((sum, e) => {
      if (e.type === "agent_complete") return sum + (e.files_generated ?? 0);
      return sum;
    }, 0);

  return (
    <div className="absolute top-0 right-0 bottom-0 w-[280px] z-20 bg-gray-900/95 backdrop-blur-sm border-l border-gray-700/50 flex flex-col animate-in slide-in-from-right duration-200">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b border-gray-700/50"
        style={{ borderBottomColor: agentInfo.color }}
      >
        <h3 className="text-sm font-semibold text-white">{agentInfo.name}</h3>
        <button
          onClick={() => selectAgent(null)}
          className="p-1 rounded hover:bg-gray-700/50 transition-colors text-gray-400 hover:text-white"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {/* Sprite placeholder + identity */}
        <div className="flex items-start gap-3">
          <div
            className="w-12 h-12 rounded-lg flex items-center justify-center text-lg font-bold text-white/80 shrink-0"
            style={{ backgroundColor: `${agentInfo.color}33` }}
          >
            {agentInfo.name.charAt(0)}
          </div>
          <div>
            <p className="text-xs text-gray-400">{agentInfo.role}</p>
            <p className="text-[11px] text-gray-500 mt-0.5">
              {department?.label ?? agentInfo.room}
              {!onDuty && " · not on this run"}
            </p>
            <div className="flex items-center gap-1.5 mt-1">
              <span
                className={`inline-block w-2 h-2 rounded-full ${
                  agentState?.state === "working"
                    ? "bg-green-400 animate-pulse"
                    : agentState?.state === "error"
                      ? "bg-red-400"
                      : agentState?.state === "retrying"
                        ? "bg-amber-400 animate-pulse"
                        : agentState?.state === "blocked"
                          ? "bg-slate-400"
                          : agentState?.state === "skipped"
                            ? "bg-slate-600"
                            : agentState?.state === "idle"
                              ? "bg-gray-500"
                              : "bg-yellow-400"
                }`}
              />
              <span className="text-xs text-gray-300">{stateLabel}</span>
            </div>
          </div>
        </div>

        {/* What it is running right now, and how far through a fan-out */}
        {agentState?.node && (
          <div className="text-xs text-gray-400">
            <span className="text-gray-500">Node </span>
            <code className="text-gray-300">{agentState.node}</code>
            {agentState.tally && (
              <span className="ml-2 text-gray-500">
                {agentState.tally.done}/{agentState.tally.total} authored
              </span>
            )}
          </div>
        )}

        {/* Why this agent is parked. The office can show that it stopped; only
            the panel has room to say what it stopped on. */}
        {parked && (
          <div
            className={`flex items-start gap-2 text-xs px-2 py-2 rounded border ${
              isBlocked
                ? "bg-slate-800/50 text-slate-300 border-slate-700/50"
                : "bg-gray-800/40 text-gray-400 border-gray-700/40"
            }`}
          >
            <Lock className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span>
              <span className="font-medium">
                {isBlocked ? "Blocked" : "Skipped"}
              </span>
              {" — "}
              {parked}
            </span>
          </div>
        )}

        {agentState?.state === "retrying" && agentState.attempt && (
          <div className="flex items-center gap-2 text-xs text-amber-300">
            <RotateCcw className="w-3.5 h-3.5" />
            <span>
              Retrying — attempt {agentState.attempt.n} of {agentState.attempt.of}
            </span>
          </div>
        )}

        {/* Progress bar */}
        {agentState?.state === "working" && agentState.progress !== undefined && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-gray-400">Progress</span>
              <span className="text-xs text-gray-300 font-mono">
                {Math.round(agentState.progress * 100)}%
              </span>
            </div>
            <div className="w-full h-1.5 rounded-full bg-gray-700 overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-300"
                style={{
                  width: `${Math.round(agentState.progress * 100)}%`,
                  backgroundColor: agentInfo.color,
                }}
              />
            </div>
          </div>
        )}

        {/* Files generated */}
        {filesGenerated > 0 && (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <FileCode className="w-3.5 h-3.5" />
            <span>
              {filesGenerated} file{filesGenerated !== 1 ? "s" : ""} generated
            </span>
          </div>
        )}

        {/* Who was waiting on this desk */}
        {deliveredTo.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <MoveRight className="w-3.5 h-3.5 text-gray-500" />
              <span className="text-xs text-gray-500 font-medium">Delivered to</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {deliveredTo.map((id) => (
                <button
                  key={id}
                  onClick={() => selectAgent(id)}
                  className="text-[11px] px-1.5 py-0.5 rounded bg-gray-800/60 text-gray-300 hover:bg-gray-700/60 transition-colors"
                >
                  {AGENT_BY_ID[id]?.name ?? id}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Recent messages */}
        {recentMessages.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <MessageCircle className="w-3.5 h-3.5 text-gray-500" />
              <span className="text-xs text-gray-500 font-medium">
                Recent Activity
              </span>
            </div>
            <div className="space-y-1.5">
              {recentMessages.map((msg, i) => (
                <div
                  key={i}
                  className={`text-xs px-2 py-1.5 rounded ${
                    msg.type === "error"
                      ? "bg-red-900/30 text-red-300 border border-red-800/30"
                      : "bg-gray-800/50 text-gray-300"
                  }`}
                >
                  {msg.text}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Speech bubble */}
        {agentState?.speechBubble && (
          <div className="bg-gray-800/50 rounded-lg px-3 py-2">
            <p className="text-xs text-gray-300 italic">
              &ldquo;{agentState.speechBubble}&rdquo;
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default AgentPanel;
