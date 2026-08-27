"use client";

import { Play, Pause } from "lucide-react";
import { useOfficeStore } from "../OfficeStateManager";

const SPEED_OPTIONS = [1, 2, 4] as const;

export function SpeedControls() {
  const speed = useOfficeStore((s) => s.speed);
  const isRunning = useOfficeStore((s) => s.isRunning);
  const setSpeed = useOfficeStore((s) => s.setSpeed);

  const handleTogglePause = () => {
    setSpeed(isRunning ? 0 : 1);
  };

  return (
    <div className="flex items-center gap-1 bg-gray-900/80 backdrop-blur-sm rounded-lg border border-gray-700/50 px-2 py-1.5">
      {/* Pause / Play toggle */}
      <button
        onClick={handleTogglePause}
        className="p-1 rounded hover:bg-gray-700/50 transition-colors text-gray-300 hover:text-white"
        title={isRunning ? "Pause" : "Play"}
      >
        {isRunning ? (
          <Pause className="w-3.5 h-3.5" />
        ) : (
          <Play className="w-3.5 h-3.5" />
        )}
      </button>

      {/* Divider */}
      <div className="w-px h-4 bg-gray-700 mx-0.5" />

      {/* Speed buttons */}
      {SPEED_OPTIONS.map((s) => (
        <button
          key={s}
          onClick={() => setSpeed(s)}
          className={`px-1.5 py-0.5 rounded text-xs font-mono transition-colors ${
            speed === s && isRunning
              ? "bg-blue-600 text-white"
              : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
          }`}
        >
          {s}x
        </button>
      ))}

      {/* Paused indicator */}
      {!isRunning && (
        <span className="text-xs text-yellow-400 font-medium ml-1">
          Paused
        </span>
      )}
    </div>
  );
}

export default SpeedControls;
