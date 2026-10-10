"use client";

import { useEffect, useState } from "react";
import { useOfficeStore } from "../OfficeStateManager";
import { ENGINE_BY_ID } from "../types";

/** What an engine is and what it is doing, when the mouse is over it. */
export function EngineTooltip() {
  const hovered = useOfficeStore((s) => s.hoveredEngine);
  const engines = useOfficeStore((s) => s.engines);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const handler = (e: MouseEvent) => setMousePos({ x: e.clientX, y: e.clientY });
    window.addEventListener("mousemove", handler);
    return () => window.removeEventListener("mousemove", handler);
  }, []);

  if (!hovered) return null;
  const info = ENGINE_BY_ID[hovered];
  if (!info) return null;
  const light = engines.get(hovered);
  const state = light?.state ?? "off";

  return (
    <div className="fixed z-50 pointer-events-none" style={{ left: mousePos.x + 12, top: mousePos.y - 10 }}>
      <div
        className="bg-gray-900/95 backdrop-blur-sm rounded-lg shadow-xl px-3 py-2 w-[240px] border border-gray-700/50"
        style={{ borderLeftColor: info.color, borderLeftWidth: 3 }}
      >
        <p className="text-sm font-semibold text-white">{info.label}</p>
        <p className="text-xs text-gray-400 mt-0.5 leading-snug">{info.does}</p>
        <div className="flex items-center gap-1.5 mt-1.5">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              state === "busy" ? "bg-amber-400 animate-pulse" : state === "on" ? "bg-emerald-400" : "bg-gray-600"
            }`}
          />
          <span className="text-xs text-gray-300">
            {state === "busy" ? "Working" : state === "on" ? "Serving" : "Idle"}
            {light?.detail ? ` — ${light.detail}` : ""}
          </span>
        </div>
      </div>
    </div>
  );
}

export default EngineTooltip;
