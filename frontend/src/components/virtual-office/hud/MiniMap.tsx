"use client";

import { useCallback } from "react";
import { useOfficeStore } from "../OfficeStateManager";
import { OFFICE_LAYOUT } from "../layout";
import { AGENT_REGISTRY } from "../types";

const MAP_W = 160;
const MAP_H = 120;

export function MiniMap() {
  const agents = useOfficeStore((s) => s.agents);
  const activeAgents = useOfficeStore((s) => s.activeAgents);

  const { rooms, width: gridW, height: gridH } = OFFICE_LAYOUT;

  const scaleX = MAP_W / gridW;
  const scaleY = MAP_H / gridH;

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      // Convert minimap coords back to tile coords
      const _tileX = mx / scaleX;
      const _tileY = my / scaleY;
      // Camera jump would be handled by renderer / camera util
    },
    [scaleX, scaleY],
  );

  return (
    <div
      className="rounded-lg overflow-hidden border border-gray-600/50 cursor-pointer select-none"
      style={{ width: MAP_W, height: MAP_H }}
      onClick={handleClick}
    >
      <svg
        width={MAP_W}
        height={MAP_H}
        viewBox={`0 0 ${MAP_W} ${MAP_H}`}
        className="bg-gray-900/80 backdrop-blur-sm"
      >
        {/* Rooms as colored rectangles */}
        {rooms.map((room) => (
          <rect
            key={room.id}
            x={room.x * scaleX}
            y={room.y * scaleY}
            width={room.w * scaleX}
            height={room.h * scaleY}
            fill={room.color}
            fillOpacity={0.25}
            stroke={room.color}
            strokeOpacity={0.5}
            strokeWidth={0.5}
            rx={1}
          />
        ))}

        {/* Agent dots */}
        {Array.from(agents.values()).map((agent) => {
          const state = agent.getState();
          const info = AGENT_REGISTRY.find((a) => a.id === state.id);
          const isActive = activeAgents.has(state.id);
          const color = info?.color ?? "#9CA3AF";

          return (
            <circle
              key={state.id}
              cx={state.position.x * scaleX}
              cy={state.position.y * scaleY}
              r={isActive ? 2.5 : 1.5}
              fill={isActive ? color : "#6B7280"}
              opacity={isActive ? 1 : 0.4}
            >
              {isActive && (
                <animate
                  attributeName="r"
                  values="2;3;2"
                  dur="1.5s"
                  repeatCount="indefinite"
                />
              )}
            </circle>
          );
        })}

        {/* Viewport indicator (placeholder - would need camera state) */}
        <rect
          x={MAP_W * 0.3}
          y={MAP_H * 0.3}
          width={MAP_W * 0.4}
          height={MAP_H * 0.4}
          fill="none"
          stroke="white"
          strokeOpacity={0.5}
          strokeWidth={1}
          rx={1}
        />
      </svg>
    </div>
  );
}

export default MiniMap;
