"use client";

import { X, FileCode, MessageCircle } from "lucide-react";
import { useOfficeStore } from "../OfficeStateManager";
import { AGENT_REGISTRY } from "../types";

export function AgentPanel() {
  const selectedAgent = useOfficeStore((s) => s.selectedAgent);
  const agents = useOfficeStore((s) => s.agents);
  const events = useOfficeStore((s) => s.events);
  const selectAgent = useOfficeStore((s) => s.selectAgent);

  if (!selectedAgent) return null;

  const agent = agents.get(selectedAgent);
  const agentState = agent?.getState();
  const agentInfo = AGENT_REGISTRY.find((a) => a.id === selectedAgent);

  if (!agentInfo) return null;

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
            <div className="flex items-center gap-1.5 mt-1">
              <span
                className={`inline-block w-2 h-2 rounded-full ${
                  agentState?.state === "working"
                    ? "bg-green-400 animate-pulse"
                    : agentState?.state === "error"
                      ? "bg-red-400"
                      : agentState?.state === "idle"
                        ? "bg-gray-500"
                        : "bg-yellow-400"
                }`}
              />
              <span className="text-xs text-gray-300">{stateLabel}</span>
            </div>
          </div>
        </div>

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
