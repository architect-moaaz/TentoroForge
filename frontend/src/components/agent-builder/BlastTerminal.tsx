"use client";

/**
 * The live log of a blast, as a terminal: a dark, monospaced pane where each thing that happens is a new line at the
 * bottom and the older ones scroll up. It follows the newest line, until you scroll up to read; then it stays where you
 * are and offers a way back down. It stays after the blast as a record, and can be cleared, copied or folded away.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Copy, Trash2 } from "lucide-react";
import { logText, stamp, type LogKind, type LogLine } from "@/lib/blast-log";

interface Props {
  lines: LogLine[];
  /** A blast is going on: a cursor blinks under the last line. */
  running: boolean;
  onClear: () => void;
}

const COLOUR: Record<LogKind, string> = {
  cmd: "text-emerald-300",
  info: "text-zinc-100",
  step: "text-cyan-300",
  good: "text-green-400",
  bad: "text-red-400",
  warn: "text-amber-300",
  dim: "text-zinc-500",
};

/** How far from the bottom still counts as "at the bottom", in pixels. */
const NEAR = 24;

export function BlastTerminal({ lines, running, onClear }: Props) {
  const [folded, setFolded] = useState(false);
  const [following, setFollowing] = useState(true);
  const [copied, setCopied] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  // Follow the newest line, unless the reader has scrolled up.
  useEffect(() => {
    const el = scroller.current;
    if (el && following) el.scrollTop = el.scrollHeight;
  }, [lines.length, following, folded]);

  const onScroll = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR);
  }, []);

  const jump = () => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
    setFollowing(true);
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(logText(lines));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard not available: nothing to do */
    }
  };

  return (
    <div className="overflow-hidden rounded-md border border-zinc-800 bg-zinc-950 font-mono text-[11px] leading-[1.45] text-zinc-200 shadow-sm" data-testid="blast-terminal">
      <div className="flex items-center gap-2 border-b border-zinc-800 bg-zinc-900 px-2 py-1">
        <button type="button" className="flex items-center gap-1 text-zinc-300 hover:text-white" onClick={() => setFolded((f) => !f)} aria-expanded={!folded} aria-label={folded ? "Show the log" : "Fold the log"}>
          {folded ? <ChevronRight className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          <span className="flex gap-1" aria-hidden="true">
            <span className="h-2 w-2 rounded-full bg-red-500/80" />
            <span className="h-2 w-2 rounded-full bg-amber-400/80" />
            <span className="h-2 w-2 rounded-full bg-green-500/80" />
          </span>
        </button>
        <span className="text-zinc-400">blast — live log</span>
        {running && <span className="animate-pulse text-emerald-400" data-testid="terminal-running">● running</span>}
        <span className="ml-auto text-zinc-500">{lines.length} line{lines.length === 1 ? "" : "s"}</span>
        <button type="button" className="text-zinc-400 hover:text-white" onClick={copy} aria-label="Copy the log" title="Copy the log">
          <Copy className="h-3 w-3" />
        </button>
        {copied && <span className="text-emerald-400">copied</span>}
        <button type="button" className="text-zinc-400 hover:text-white disabled:opacity-40" onClick={onClear} disabled={running || lines.length === 0} aria-label="Clear the log" title="Clear the log">
          <Trash2 className="h-3 w-3" />
        </button>
      </div>

      {!folded && (
        <div className="relative">
          <div ref={scroller} onScroll={onScroll} role="log" aria-live="polite" className="h-60 overflow-y-auto px-2 py-1.5" data-testid="terminal-lines">
            {lines.map((l) => (
              <div key={l.id} className={`whitespace-pre-wrap break-words ${COLOUR[l.kind]}`} data-kind={l.kind}>
                <span className="mr-2 select-none text-zinc-600">{stamp(l.t)}</span>
                {l.text}
              </div>
            ))}
            {running && (
              <div className="text-zinc-500" aria-hidden="true">
                <span className="animate-pulse">▌</span>
              </div>
            )}
          </div>
          {!following && (
            <button type="button" onClick={jump} className="absolute bottom-2 right-3 rounded bg-zinc-700/90 px-2 py-0.5 text-[10px] text-white hover:bg-zinc-600" data-testid="terminal-jump">
              ↓ newest
            </button>
          )}
        </div>
      )}
    </div>
  );
}
