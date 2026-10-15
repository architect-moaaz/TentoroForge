/**
 * The live log of a blast: what is happening, line by line, like a terminal.
 *
 * Several bombs are thrown at once, so each line carries a short tag, `[03]`, that says which bomb it belongs to.
 * Pure functions: an event of the run stream becomes the lines to print, nothing more.
 */
import { roundSummary, type BlastSummary } from "./agent-blast";

export type LogKind = "cmd" | "info" | "step" | "good" | "bad" | "warn" | "dim";

export interface LogLine {
  id: number;
  /** Milliseconds since the blast began. */
  t: number;
  kind: LogKind;
  text: string;
}

/** The most lines kept: the oldest scroll away first. */
export const MAX_LOG = 600;

type Event = { type: string; [key: string]: any };
export type Printed = Array<{ kind: LogKind; text: string }>;

/** `+00:07`: how long into the blast a line was printed. */
export function stamp(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `+${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** `[03]` out of 16, padded to the width of the total so the columns line up. */
export const tag = (index: number, total: number): string => `[${String(index).padStart(String(Math.max(total, 1)).length, "0")}]`;

const short = (text: string, n: number) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);
const oneLine = (text: string) => text.replace(/\s+/g, " ").trim();

const TOOL_WORD: Record<string, string> = { lookup: "lookup", change: "change", handoff: "hand-over", unknown: "unknown tool" };

export interface LogContext {
  /** How many tests are in this blast. */
  total: number;
  /** A bomb's key in words ("made_up_id" → "Made-up ID"). */
  bombTitle: (key?: string | null) => string | null;
  /** A tool test's kind in words ("tool_data_exposure" → "Secrets and privacy"). */
  kindTitle?: (kind?: string | null) => string | null;
}

/** The lines to print for one event of the run stream. */
export function linesForEvent(e: Event, ctx: LogContext): Printed {
  const total = e.total ?? ctx.total;
  const t = e.index ? tag(e.index, ctx.total) : "";
  switch (e.type) {
    case "start":
      return [{ kind: "info", text: `Throwing ${e.total} test${e.total === 1 ? "" : "s"}${e.repeats > 1 ? `, each ${e.repeats} times` : ""}, a few at a time…` }];

    case "test_start": {
      const kind = ctx.bombTitle(e.bomb) ?? (e.tool ? [e.tool, ctx.kindTitle?.(e.kind)].filter(Boolean).join(" · ") : null);
      return [{ kind: "cmd", text: `${tag(e.index, total)} ▶ ${e.name}${kind ? `  (${kind})` : ""}${e.runs > 1 ? `  run ${e.run}/${e.runs}` : ""}` }];
    }

    case "step":
      switch (e.kind) {
        case "tool":
          return [{ kind: "step", text: `${t}   › asks to use ${e.tool} (${TOOL_WORD[e.toolKind] ?? "tool"})${e.input && e.input !== "{}" ? ` ${short(e.input, 70)}` : ""}` }];
        case "tool_result":
          return e.held
            ? [{ kind: "warn", text: `${t}   ⏸ ${e.tool}: ${e.outcome}` }]
            : e.error
              ? [{ kind: "warn", text: `${t}   ✗ ${e.tool}: ${e.outcome}` }]
              : [{ kind: "dim", text: `${t}   ← ${e.tool}: ${e.outcome}` }];
        case "reply":
          return [{ kind: "dim", text: `${t}   ✎ replies (${e.chars} characters): “${short(oneLine(String(e.preview ?? "")), 80)}”` }];
        case "blocked":
          return [{ kind: "info", text: `${t}   ⛔ stopped by the safety rules before the AI saw it` }];
        case "rules":
          return (e.failures as string[]).map((f) => ({ kind: "bad" as LogKind, text: `${t}   ✗ ${short(oneLine(f), 110)}` }));
        case "guard":
          return [{ kind: "info", text: `${t}   🛡 ${short(oneLine(String(e.text ?? "")), 120)}` }];
        case "judge_start":
          return [{ kind: "dim", text: `${t}   ⚖ asking a reviewer…` }];
        case "judge":
          return [{ kind: e.pass ? "good" : "bad", text: `${t}   ⚖ reviewer says ${e.pass ? "it held" : "it did not hold"}${e.reason ? `: ${short(oneLine(String(e.reason)), 110)}` : ""}` }];
        default:
          return [];
      }

    case "result": {
      const r = e.result;
      const at = tag(e.index ?? 0, ctx.total);
      if (r.status === "passed") return [{ kind: "good", text: `${at} ✔ DEFUSED   ${r.name}` }];
      if (r.status === "failed") return [{ kind: "bad", text: `${at} ✖ EXPLODED  ${r.name}${r.failures?.[0] ? ` — ${short(oneLine(r.failures[0]), 100)}` : ""}` }];
      if (r.status === "flaky") return [{ kind: "warn", text: `${at} ◐ UNSTABLE  ${r.name} — held ${r.passedRuns} of ${r.runs} runs` }];
      return [{ kind: "warn", text: `${at} ⚠ MISFIRE   ${r.name} — ${short(oneLine(String(r.error ?? "could not be run")), 100)}` }];
    }

    case "done": {
      const s = e.summary as BlastSummary;
      const went = s.failed + s.flaky;
      return [{ kind: went ? "bad" : s.error ? "warn" : "good", text: `Done. ${roundSummary(s) || "Nothing was thrown."}` }];
    }

    case "error":
      return [{ kind: "bad", text: `✗ ${e.message}` }];

    default:
      return [];
  }
}

/** Add lines, keeping the newest MAX_LOG. */
export function appendLines(log: LogLine[], printed: Printed, t: number, nextId: number): { log: LogLine[]; nextId: number } {
  if (!printed.length) return { log, nextId };
  const added = printed.map((p, i) => ({ id: nextId + i, t, kind: p.kind, text: p.text }));
  const merged = [...log, ...added];
  return { log: merged.length > MAX_LOG ? merged.slice(merged.length - MAX_LOG) : merged, nextId: nextId + added.length };
}

/** The log as plain text, for copying. */
export const logText = (log: LogLine[]): string => log.map((l) => `${stamp(l.t)} ${l.text}`).join("\n");
