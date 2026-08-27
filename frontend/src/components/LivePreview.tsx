"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import {
  Send,
  RefreshCw,
  Loader2,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { type StreamEvent } from "./ProgressStream";

interface LivePreviewProps {
  projectId: string;
  port: number;
  onRefineComplete?: () => void;
}

export function LivePreview({
  projectId,
  port,
  onRefineComplete,
}: LivePreviewProps) {
  const [instruction, setInstruction] = useState("");
  const [isRefining, setIsRefining] = useState(false);
  const [logEvents, setLogEvents] = useState<StreamEvent[]>([]);
  const [logExpanded, setLogExpanded] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll log
  useEffect(() => {
    if (logExpanded && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logEvents, logExpanded]);

  const handleRefresh = useCallback(() => {
    if (iframeRef.current) {
      iframeRef.current.src = `http://localhost:${port}`;
    }
  }, [port]);

  const handleRefine = useCallback(async () => {
    if (!instruction.trim() || isRefining) return;

    setIsRefining(true);
    setLogEvents([]);
    setLogExpanded(true);

    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500"}/api/projects/${projectId}/refine`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instruction: instruction.trim() }),
        }
      );

      if (!response.ok) {
        throw new Error(`Server error: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const dataStr = line.slice(6);
            try {
              const data = JSON.parse(dataStr);
              let type: StreamEvent["type"] = "log";
              if (data.message && !data.num_turns) type = "status";
              if (data.text) type = "log";
              if (data.tool) type = "tool_call";
              if (data.path && !data.tool) type = "file_created";

              const event: StreamEvent = { type, data, timestamp: Date.now() };
              setLogEvents((prev) => [...prev, event]);

              // On refine_complete, reload iframe
              if (data.message === "Refinement complete") {
                // Brief delay for hot-reload to kick in
                setTimeout(() => {
                  handleRefresh();
                  onRefineComplete?.();
                }, 1000);
              }
            } catch {
              // skip
            }
          }
        }
      }
    } catch (err) {
      setLogEvents((prev) => [
        ...prev,
        {
          type: "error",
          data: { message: String(err) },
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setIsRefining(false);
      setInstruction("");
    }
  }, [instruction, isRefining, projectId, handleRefresh, onRefineComplete]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleRefine();
      }
    },
    [handleRefine]
  );

  return (
    <div className="flex h-full flex-col">
      {/* iframe area */}
      <div className="relative flex-1 bg-white">
        <iframe
          ref={iframeRef}
          src={`http://localhost:${port}`}
          className="h-full w-full border-0"
          title="Live Preview"
        />
      </div>

      {/* Collapsible refinement log */}
      {logEvents.length > 0 && (
        <div className="border-t border-border bg-surface">
          <button
            onClick={() => setLogExpanded(!logExpanded)}
            className="flex w-full items-center gap-1.5 px-3 py-1.5 text-xs text-text-tertiary hover:text-text-secondary"
          >
            {logExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            Refinement log ({logEvents.length} events)
            {isRefining && (
              <Loader2 className="ml-1 h-3 w-3 animate-spin text-brand-500" />
            )}
          </button>
          {logExpanded && (
            <div className="max-h-40 overflow-y-auto border-t border-border px-3 py-2 custom-scrollbar">
              {logEvents.map((evt, i) => (
                <div key={i} className="text-xs text-text-secondary">
                  {evt.type === "tool_call" && (
                    <span className="text-amber-600">
                      {String(evt.data.tool)}{" "}
                    </span>
                  )}
                  {evt.type === "log" && (
                    <span className="text-text-tertiary">
                      {String(evt.data.text || "").slice(0, 120)}
                      {String(evt.data.text || "").length > 120 ? "..." : ""}
                    </span>
                  )}
                  {evt.type === "file_created" && (
                    <span className="font-mono text-green-600">
                      {String(evt.data.path)}
                    </span>
                  )}
                  {evt.type === "status" && (
                    <span className="text-brand-600">
                      {String(evt.data.message || "")}
                    </span>
                  )}
                  {evt.type === "error" && (
                    <span className="text-red-600">
                      {String(evt.data.message || "")}
                    </span>
                  )}
                </div>
              ))}
              <div ref={logEndRef} />
            </div>
          )}
        </div>
      )}

      {/* Bottom bar: input + buttons */}
      <div className="flex items-center gap-2 border-t border-border bg-surface px-3 py-2">
        <input
          type="text"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe a change... (e.g. &quot;make the button red&quot;)"
          disabled={isRefining}
          className="flex-1 rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text-primary placeholder:text-text-tertiary focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:opacity-50"
        />
        <button
          onClick={handleRefine}
          disabled={isRefining || !instruction.trim()}
          className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white transition-colors hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed"
          title="Send refinement"
        >
          {isRefining ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </button>
        <button
          onClick={handleRefresh}
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-border text-text-secondary transition-colors hover:bg-surface-secondary"
          title="Refresh preview"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
