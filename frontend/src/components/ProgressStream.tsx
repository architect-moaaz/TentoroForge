"use client";

import { useRef, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  CheckCircle2,
  Loader2,
  AlertCircle,
  Wrench,
  FileCode2,
  MessageSquare,
  ChevronDown,
  ChevronRight,
  Eye,
  Hammer,
  BadgeCheck,
  Paintbrush,
} from "lucide-react";

export interface StreamEvent {
  type: "status" | "log" | "tool_call" | "file_created" | "complete" | "error" | "review_start" | "review_issues" | "fix_start" | "review_approved" | "refine_start" | "refine_complete";
  data: Record<string, unknown>;
  timestamp: number;
}

interface ProgressStreamProps {
  events: StreamEvent[];
  isGenerating: boolean;
}

/** Format an event timestamp (ms epoch) as HH:MM:SS. */
function fmtTime(ts: number): string {
  if (!ts) return "";
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/** Strip inline markdown so a truncated one-line summary reads clean. */
function stripMd(s: string): string {
  return s
    .replace(/`{1,3}([^`]*)`{1,3}/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Compact markdown renderer for streamed agent text. */
function Md({ children }: { children: string }) {
  return (
    <div className="prose prose-sm max-w-none text-text-secondary [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0.5 [&_h1]:text-sm [&_h2]:text-sm [&_h3]:text-[13px] [&_h1]:mt-2 [&_h2]:mt-2 [&_h3]:mt-1.5 [&_h1]:mb-1 [&_h2]:mb-1 [&_pre]:bg-surface-tertiary [&_pre]:p-2 [&_pre]:rounded [&_pre]:text-xs [&_code]:text-xs [&_code]:bg-surface-tertiary [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}

function EventItem({ event }: { event: StreamEvent }) {
  const [expanded, setExpanded] = useState(false);

  switch (event.type) {
    case "status":
      return (
        <div className="flex items-start gap-2 text-sm">
          <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-brand-500" />
          <span className="text-text-secondary">
            {String(event.data.message || "")}
          </span>
        </div>
      );

    case "log":
      return (
        <div className="flex items-start gap-2 text-sm">
          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-0.5 shrink-0 text-text-tertiary hover:text-text-secondary"
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <MessageSquare className="h-3.5 w-3.5 shrink-0 text-text-tertiary" />
              <span className="truncate text-text-secondary">
                {stripMd(String(event.data.text || "")).slice(0, 100)}
                {stripMd(String(event.data.text || "")).length > 100 ? "…" : ""}
              </span>
            </div>
            {expanded && (
              <div className="mt-1.5 max-h-64 overflow-auto rounded bg-surface-tertiary p-2 custom-scrollbar">
                <Md>{String(event.data.text || "")}</Md>
              </div>
            )}
          </div>
        </div>
      );

    case "tool_call":
      return (
        <div className="flex items-start gap-2 text-sm">
          <Wrench className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
          <span className="text-text-secondary">
            <span className="font-medium text-text-primary">
              {String(event.data.tool || "")}
            </span>
            {String(event.data.tool) === "Write" && event.data.args ? (
              <span className="text-text-tertiary">
                {" → "}
                {(() => {
                  try {
                    const args = typeof event.data.args === "string"
                      ? JSON.parse(String(event.data.args))
                      : (event.data.args as Record<string, string>);
                    return args.file_path || "";
                  } catch {
                    return "";
                  }
                })()}
              </span>
            ) : null}
          </span>
        </div>
      );

    case "file_created":
      return (
        <div className="flex items-start gap-2 text-sm">
          <FileCode2 className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
          <span className="font-mono text-xs text-green-700">
            {String(event.data.path || "")}
          </span>
        </div>
      );

    case "complete":
      return (
        <div className="flex items-start gap-2 text-sm">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
          <div className="text-text-secondary">
            <span className="font-medium text-green-700">Complete!</span>
            <span className="ml-2 text-xs text-text-tertiary">
              {String(event.data.num_turns)} turns
              {event.data.cost_usd != null &&
                ` · $${Number(event.data.cost_usd).toFixed(3)}`}
              {event.data.duration_ms != null &&
                ` · ${(Number(event.data.duration_ms) / 1000).toFixed(1)}s`}
            </span>
          </div>
        </div>
      );

    case "review_start":
      return (
        <div className="flex items-start gap-2 text-sm">
          <Eye className="mt-0.5 h-4 w-4 shrink-0 animate-pulse text-purple-500" />
          <span className="font-medium text-purple-700">
            {String(event.data.message || "")}
          </span>
        </div>
      );

    case "review_issues": {
      const issues = event.data.issues ? String(event.data.issues) : null;
      return (
        <div className="flex items-start gap-2 text-sm">
          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-0.5 shrink-0 text-text-tertiary hover:text-text-secondary"
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <Eye className="h-3.5 w-3.5 shrink-0 text-amber-500" />
              <span className="text-amber-700">
                {String(event.data.message || "")}
              </span>
            </div>
            {expanded && issues && (
              <div className="mt-1.5 max-h-64 overflow-auto rounded bg-surface-tertiary p-2 custom-scrollbar">
                <Md>{issues}</Md>
              </div>
            )}
          </div>
        </div>
      );
    }

    case "fix_start":
      return (
        <div className="flex items-start gap-2 text-sm">
          <Hammer className="mt-0.5 h-4 w-4 shrink-0 animate-pulse text-blue-500" />
          <span className="font-medium text-blue-700">
            {String(event.data.message || "")}
          </span>
        </div>
      );

    case "review_approved":
      return (
        <div className="flex items-start gap-2 text-sm">
          <BadgeCheck className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
          <span className="font-medium text-green-700">
            {String(event.data.message || "")}
          </span>
        </div>
      );

    case "refine_start":
      return (
        <div className="flex items-start gap-2 text-sm">
          <Paintbrush className="mt-0.5 h-4 w-4 shrink-0 animate-pulse text-violet-500" />
          <span className="font-medium text-violet-700">
            {String(event.data.message || "")}
          </span>
        </div>
      );

    case "refine_complete":
      return (
        <div className="flex items-start gap-2 text-sm">
          <Paintbrush className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
          <div className="text-text-secondary">
            <span className="font-medium text-green-700">Refinement complete</span>
            <span className="ml-2 text-xs text-text-tertiary">
              {event.data.num_turns != null && `${String(event.data.num_turns)} turns`}
              {event.data.cost_usd != null &&
                ` · $${Number(event.data.cost_usd).toFixed(3)}`}
              {event.data.duration_ms != null &&
                ` · ${(Number(event.data.duration_ms) / 1000).toFixed(1)}s`}
            </span>
          </div>
        </div>
      );

    case "error":
      return (
        <div className="flex items-start gap-2 text-sm">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
          <span className="text-red-600">
            {String(event.data.message || "Unknown error")}
          </span>
        </div>
      );

    default:
      return null;
  }
}

export function ProgressStream({ events, isGenerating }: ProgressStreamProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [events]);

  if (events.length === 0 && !isGenerating) {
    return (
      <div className="flex h-full items-center justify-center p-5 text-center text-sm text-text-tertiary">
        Agent progress will appear here
      </div>
    );
  }

  return (
    <div ref={containerRef} className="space-y-2.5 p-4">
      {events.map((event, i) => (
        <div key={i} className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <EventItem event={event} />
          </div>
          {event.timestamp ? (
            <span className="mt-0.5 shrink-0 text-[10px] tabular-nums text-text-tertiary">
              {fmtTime(event.timestamp)}
            </span>
          ) : null}
        </div>
      ))}
      {isGenerating && events.length > 0 && (
        <div className="flex items-center gap-2 pt-1 text-xs text-text-tertiary">
          <Loader2 className="h-3 w-3 animate-spin" />
          Agent is working...
        </div>
      )}
    </div>
  );
}
