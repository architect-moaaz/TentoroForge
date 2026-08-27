"use client";
import * as React from "react";
import { X, Sparkles, Loader2 } from "lucide-react";
import { useEditorStore } from "@/lib/editor-store";
import type { Artifacts } from "@forge/patches";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface Props {
  open: boolean;
  onClose: () => void;
  projectId: string;
}

interface LogEntry {
  kind: "status" | "log" | "error";
  text: string;
}

export function AiPromptModal({ open, onClose, projectId }: Props) {
  const [prompt, setPrompt] = React.useState("");
  const [running, setRunning] = React.useState(false);
  const [logs, setLogs] = React.useState<LogEntry[]>([]);
  const dispatch = useEditorStore((s) => s.dispatch);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    if (open) {
      setLogs([]);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  if (!open) return null;

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!prompt.trim() || running) return;
    setRunning(true);
    setLogs([{ kind: "status", text: "Sending to AI…" }]);

    try {
      const res = await fetch(`${API}/api/_debug/project-ai-edit/${projectId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt.trim() }),
      });

      if (!res.body) throw new Error("No response stream");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE event boundary is a blank line. sse-starlette emits CRLF, but
        // accept either by normalising before split.
        const parts = buffer.replace(/\r\n/g, "\n").split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const eventLine = part.match(/^event:\s*(.+)$/m);
          const dataLine = part.match(/^data:\s*(.+)$/m);
          if (!dataLine) continue;
          const event = eventLine?.[1]?.trim() ?? "log";
          let data: Record<string, unknown>;
          try { data = JSON.parse(dataLine[1]); } catch { continue; }

          if (event === "status") {
            setLogs((prev) => [...prev, { kind: "status", text: String(data.message ?? "...") }]);
          } else if (event === "log") {
            setLogs((prev) => [...prev, { kind: "log", text: String(data.text ?? "") }]);
          } else if (event === "error") {
            setLogs((prev) => [...prev, { kind: "error", text: String(data.text ?? "error") }]);
          } else if (event === "artifacts") {
            // Apply via replaceArtifacts so it's undoable
            const artifacts = data.artifacts;
            if (artifacts) {
              dispatch({
                type: "replaceArtifacts",
                artifacts: artifacts as Artifacts,
                rationale: data.rationale as string | undefined,
              });
              setLogs((prev) => [...prev, { kind: "status", text: "Applied — Cmd+Z to undo" }]);
              // Auto-close after a short delay
              setTimeout(() => onClose(), 1200);
            }
          }
        }
      }
    } catch (err) {
      setLogs((prev) => [...prev, { kind: "error", text: `Request failed: ${(err as Error).message}` }]);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center bg-black/40 pt-24"
      onClick={onClose}
    >
      <div
        className="w-[480px] max-w-[92vw] bg-background border rounded-lg shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="px-4 py-3 border-b flex items-center gap-2">
          <Sparkles size={16} className="text-amber-500" />
          <h3 className="text-sm font-semibold flex-1">AI edit</h3>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </header>

        <form onSubmit={handleSubmit} className="p-4 space-y-3">
          <textarea
            ref={inputRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={running}
            placeholder="Describe the change — e.g. 'add a search bar to the products list' or 'make the buttons rounded'"
            className="w-full h-24 border rounded-md px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-foreground/20"
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                handleSubmit();
              }
            }}
          />

          <div className="flex justify-between items-center">
            <span className="text-[11px] text-muted-foreground">
              Cmd+Enter to send · {prompt.length} chars
            </span>
            <button
              type="submit"
              disabled={!prompt.trim() || running}
              className="h-8 px-4 rounded-md bg-foreground text-background text-sm font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              {running && <Loader2 size={14} className="animate-spin" />}
              {running ? "Working…" : "Apply"}
            </button>
          </div>
        </form>

        {logs.length > 0 && (
          <div className="border-t max-h-56 overflow-y-auto bg-muted/30 px-4 py-2 space-y-1">
            {logs.map((l, i) => (
              <div
                key={i}
                className={`text-[11px] font-mono ${
                  l.kind === "error" ? "text-destructive" :
                  l.kind === "status" ? "text-foreground" :
                  "text-muted-foreground"
                }`}
              >
                {l.text}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
