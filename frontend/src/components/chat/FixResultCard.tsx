"use client";

import { CheckCircle2, AlertTriangle, GitCommit } from "lucide-react";
import type { FixResult } from "@/stores/chat";

interface FixResultCardProps {
  result: FixResult;
}

/** Coerce a "remaining" entry into a short human string. */
function renderRemaining(item: unknown): string {
  if (typeof item === "string") return item;
  if (item && typeof item === "object") {
    const o = item as Record<string, unknown>;
    const label =
      (o.reason as string) ||
      (o.message as string) ||
      (o.column as string) ||
      (o.node as string);
    if (label) return label;
    try {
      return JSON.stringify(item);
    } catch {
      return String(item);
    }
  }
  return String(item);
}

export function FixResultCard({ result }: FixResultCardProps) {
  const resolved = result?.verify?.resolved && result?.applied;
  const remaining = result?.verify?.remaining ?? [];

  return (
    <div
      className={`my-2 rounded-lg border shadow-sm ${
        resolved
          ? "border-emerald-200 bg-emerald-50/50"
          : "border-amber-200 bg-amber-50/50"
      }`}
    >
      {/* Header */}
      <div className="flex items-start gap-2.5 px-4 py-3">
        <div
          className={`shrink-0 rounded-full p-1.5 ${
            resolved ? "bg-emerald-100" : "bg-amber-100"
          }`}
        >
          {resolved ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
          ) : (
            <AlertTriangle className="h-4 w-4 text-amber-600" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p
            className={`text-sm font-medium ${
              resolved ? "text-emerald-800" : "text-amber-800"
            }`}
          >
            {resolved ? "Fix applied" : "Still needs attention"}
          </p>
          {result?.message && (
            <p
              className={`mt-0.5 text-xs leading-relaxed ${
                resolved ? "text-emerald-700" : "text-amber-700"
              }`}
            >
              {result.message}
            </p>
          )}
        </div>
      </div>

      {/* Remaining issues when unresolved */}
      {!resolved && Array.isArray(remaining) && remaining.length > 0 && (
        <div className="border-t border-amber-200 px-4 py-2.5">
          <div className="mb-1 text-[11px] font-medium text-amber-800">
            Remaining ({remaining.length})
          </div>
          <ul className="space-y-1">
            {remaining.map((item, i) => (
              <li
                key={i}
                className="flex items-start gap-1.5 text-[11px] text-amber-700"
              >
                <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-amber-500" />
                <span className="min-w-0">{renderRemaining(item)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Committed note — undo available */}
      {result?.committed && (
        <div
          className={`flex items-center gap-1.5 border-t px-4 py-2 text-[10px] ${
            resolved
              ? "border-emerald-200 text-emerald-700"
              : "border-amber-200 text-amber-700"
          }`}
        >
          <GitCommit className="h-3 w-3" />
          Committed — you can undo this change if needed.
        </div>
      )}
    </div>
  );
}
