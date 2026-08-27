"use client";

import { Loader2, CheckCircle2, XCircle, FileCode, Wrench } from "lucide-react";

interface SchemaChangeProgressProps {
  isApplying: boolean;
  status: string | null;
  filesChanged: string[];
  toolCalls: { tool: string; args: string }[];
  error: string | null;
}

export function SchemaChangeProgress({
  isApplying,
  status,
  filesChanged,
  toolCalls,
  error,
}: SchemaChangeProgressProps) {
  if (!isApplying && !error && filesChanged.length === 0) return null;

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="mx-4 w-full max-w-md rounded-lg border bg-white p-5 shadow-xl">
        {/* Status */}
        <div className="mb-3 flex items-center gap-2">
          {isApplying ? (
            <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
          ) : error ? (
            <XCircle className="h-5 w-5 text-red-500" />
          ) : (
            <CheckCircle2 className="h-5 w-5 text-green-500" />
          )}
          <span className="text-sm font-medium">
            {error
              ? "Schema change failed"
              : isApplying
                ? status || "Applying changes..."
                : "Schema change complete"}
          </span>
        </div>

        {/* Files changed */}
        {filesChanged.length > 0 && (
          <div className="mb-2">
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              Files changed
            </p>
            <div className="max-h-32 space-y-0.5 overflow-y-auto">
              {filesChanged.map((f, i) => (
                <div key={i} className="flex items-center gap-1 text-xs text-slate-600">
                  <FileCode className="h-3 w-3 shrink-0" />
                  <span className="truncate font-mono">{f}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tool calls */}
        {toolCalls.length > 0 && (
          <div className="mb-2">
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              Operations ({toolCalls.length})
            </p>
            <div className="max-h-20 space-y-0.5 overflow-y-auto">
              {toolCalls.slice(-5).map((tc, i) => (
                <div key={i} className="flex items-center gap-1 text-xs text-slate-500">
                  <Wrench className="h-3 w-3 shrink-0" />
                  <span>{tc.tool}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <p className="mt-2 text-xs text-red-600">{error}</p>
        )}
      </div>
    </div>
  );
}
