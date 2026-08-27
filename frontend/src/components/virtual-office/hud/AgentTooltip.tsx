"use client";

import { useEffect, useState } from "react";
import { useOfficeStore } from "../OfficeStateManager";
import { AGENT_REGISTRY } from "../types";

export function AgentTooltip() {
  const hoveredAgent = useOfficeStore((s) => s.hoveredAgent);
  const agents = useOfficeStore((s) => s.agents);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      setMousePos({ x: e.clientX, y: e.clientY });
    };
    window.addEventListener("mousemove", handler);
    return () => window.removeEventListener("mousemove", handler);
  }, []);

  if (!hoveredAgent) return null;

  const agent = agents.get(hoveredAgent);
  if (!agent) return null;
  const agentState = agent.getState();

  const agentInfo = AGENT_REGISTRY.find((a) => a.id === hoveredAgent);
  if (!agentInfo) return null;

  const stateLabel =
    agentState.state.charAt(0).toUpperCase() + agentState.state.slice(1);

  return (
    <div
      className="fixed z-50 pointer-events-none"
      style={{
        left: mousePos.x + 12,
        top: mousePos.y - 10,
      }}
    >
      <div
        className="bg-gray-900/95 backdrop-blur-sm rounded-lg shadow-xl px-3 py-2 min-w-[180px] border border-gray-700/50"
        style={{ borderLeftColor: agentInfo.color, borderLeftWidth: 3 }}
      >
        {/* Name */}
        <p className="text-sm font-semibold text-white">{agentInfo.name}</p>

        {/* Role */}
        <p className="text-xs text-gray-400 mt-0.5">{agentInfo.role}</p>

        {/* State */}
        <div className="flex items-center gap-1.5 mt-1.5">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              agentState.state === "working"
                ? "bg-green-400 animate-pulse"
                : agentState.state === "error"
                  ? "bg-red-400"
                  : agentState.state === "idle"
                    ? "bg-gray-500"
                    : agentState.state === "walking"
                      ? "bg-blue-400 animate-pulse"
                      : "bg-yellow-400"
            }`}
          />
          <span className="text-xs text-gray-300">{stateLabel}</span>
        </div>

        {/* Progress bar if working */}
        {agentState.state === "working" &&
          agentState.progress !== undefined && (
            <div className="mt-1.5">
              <div className="w-full h-1 rounded-full bg-gray-700 overflow-hidden">
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

        {/* Speech bubble / current action */}
        {agentState.speechBubble && (
          <p className="text-xs text-gray-400 mt-1.5 italic truncate max-w-[200px]">
            &ldquo;{agentState.speechBubble}&rdquo;
          </p>
        )}

        {/* Room */}
        <p className="text-[10px] text-gray-500 mt-1">
          Room: {agentInfo.room.replace(/_/g, " ")}
        </p>
      </div>
    </div>
  );
}

export default AgentTooltip;
