"use client";

import { useEffect } from "react";
import { X, FileCode2, Repeat, Clock, Coins } from "lucide-react";
import type { CompletionStats } from "@/stores/chat";

interface AchievementBannerProps {
  stats: CompletionStats;
  onDismiss: () => void;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const secs = Math.round(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  return `${mins}m ${remSecs}s`;
}

export function AchievementBanner({ stats, onDismiss }: AchievementBannerProps) {
  useEffect(() => {
    // Fire confetti on mount. Purely decorative — it must NEVER crash the
    // editor, so every step is guarded (the dynamic import, the default export,
    // and each call). If canvas-confetti misbehaves under the current bundler,
    // the banner still renders and confetti is simply skipped.
    let cancelled = false;
    const colors = ["#f59e0b", "#d97706", "#fbbf24", "#10b981", "#6366f1"];
    (async () => {
      try {
        const mod = await import("canvas-confetti");
        const confetti = mod?.default;
        if (cancelled || typeof confetti !== "function") return;
        const burst = (x: number) => {
          try {
            confetti({ particleCount: 80, spread: 70, origin: { x, y: 0.6 }, colors });
          } catch {
            /* decorative — ignore */
          }
        };
        burst(0.2);
        setTimeout(() => {
          if (!cancelled) burst(0.8);
        }, 150);
      } catch (err) {
        if (process.env.NODE_ENV !== "production") {
          console.warn("[AchievementBanner] confetti skipped:", err);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 mx-3 mb-2 rounded-lg border border-amber-200 bg-gradient-to-r from-amber-50 to-yellow-50 p-4 shadow-sm">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-lg">🏆</span>
          <span className="font-bold text-amber-900">Quest Complete!</span>
          <span className="flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
            ✨ {stats.totalXp} XP Earned
          </span>
        </div>
        <button
          onClick={onDismiss}
          className="rounded-md p-1 text-amber-400 hover:bg-amber-100 hover:text-amber-600"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-4 gap-3 text-center text-xs">
        <div className="rounded-md bg-white/60 px-2 py-2">
          <FileCode2 className="mx-auto mb-1 h-4 w-4 text-green-600" />
          <div className="font-bold text-green-800">{stats.totalFiles}</div>
          <div className="text-muted-foreground">Files</div>
        </div>
        <div className="rounded-md bg-white/60 px-2 py-2">
          <Repeat className="mx-auto mb-1 h-4 w-4 text-blue-600" />
          <div className="font-bold text-blue-800">{stats.totalTurns}</div>
          <div className="text-muted-foreground">Turns</div>
        </div>
        <div className="rounded-md bg-white/60 px-2 py-2">
          <Clock className="mx-auto mb-1 h-4 w-4 text-purple-600" />
          <div className="font-bold text-purple-800">
            {formatDuration(stats.totalDuration)}
          </div>
          <div className="text-muted-foreground">Duration</div>
        </div>
        <div className="rounded-md bg-white/60 px-2 py-2">
          <Coins className="mx-auto mb-1 h-4 w-4 text-amber-600" />
          <div className="font-bold text-amber-800">
            ${stats.totalCost.toFixed(2)}
          </div>
          <div className="text-muted-foreground">Cost</div>
        </div>
      </div>
    </div>
  );
}
