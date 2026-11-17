"use client";

/**
 * The step cards the live view draws: one for each time the AI is called and one for each tool it uses, with the
 * exact input, the real requests behind the tool, the real data it returned, and a warning when an input looks wrong.
 * Shared by the live panel (AgentWatchPanel).
 */
import { useMemo } from "react";
import { AlertTriangle, CheckCircle, Loader2, PauseCircle, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { REPLAY_CHARS, rowsOf, type ModelStep, type ToolStep } from "@/lib/agent-live";

export const secs = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
export const num = (n: number) => n.toLocaleString();

export function ModelCard({ step, last, pending }: { step: ModelStep; last: boolean; pending?: string }) {
  if (step.running || step.failed) {
    return (
      <div className={`rounded border p-2 ${step.failed ? "border-red-300 bg-red-50" : "border-purple-300 bg-purple-50"}`} data-testid="live-model-running">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary" className="bg-purple-100 px-1 py-0 text-[9px] text-purple-700">Step {step.n}</Badge>
          {step.failed ? (
            <span className="text-[11px] font-semibold text-red-700">The AI call failed: {step.failed}</span>
          ) : (
            <>
              <Loader2 className="h-3 w-3 animate-spin text-purple-600" />
              <span className="text-[11px] font-semibold">Calling the AI…</span>
            </>
          )}
          <span className="text-[10px] text-muted-foreground">
            {step.messages} {step.messages === 1 ? "message" : "messages"}
            {step.tools !== undefined ? ` · ${step.tools} tools offered` : ""}
            {step.systemChars !== undefined ? ` · instructions ${num(step.systemChars)} characters` : ""}
          </span>
        </div>
        {!step.failed && pending && <p className="mt-1 whitespace-pre-wrap text-[11px] italic text-purple-900">“{pending.trim()}”</p>}
      </div>
    );
  }
  return (
    <div className="rounded border border-purple-200 bg-purple-50/50 p-2" data-testid="live-model">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary" className="bg-purple-100 px-1 py-0 text-[9px] text-purple-700">Step {step.n}</Badge>
        <span className="text-[11px] font-semibold">The AI worked on it for {secs(step.ms)}</span>
        <span className="text-[10px] text-muted-foreground">
          {num(step.inputTokens)} tokens in · {num(step.outputTokens)} out · given {step.messages} {step.messages === 1 ? "message" : "messages"}
        </span>
      </div>
      {step.said && !last && <p className="mt-1 whitespace-pre-wrap text-[11px] italic text-purple-900">“{step.said}”</p>}
      <p className="mt-1 text-[10px] text-muted-foreground">
        {step.toolsRequested.length ? (
          <>
            It decided to use: <span className="font-mono">{step.toolsRequested.join(", ")}</span>
          </>
        ) : (
          last ? "It had what it needed and answered. Its words are below." : "It had what it needed and answered."
        )}
      </p>
    </div>
  );
}

export function ToolCard({ step }: { step: ToolStep }) {
  const rows = useMemo(() => rowsOf(step.result), [step.result]);
  const json = useMemo(() => {
    try {
      return JSON.stringify(step.result, null, 2) ?? "";
    } catch {
      return String(step.result);
    }
  }, [step.result]);
  const label = { running: "running…", ok: "worked", failed: "failed", held: "held: waiting for a yes" }[step.status];
  const tone = { running: "text-blue-600", ok: "text-green-600", failed: "text-red-600", held: "text-amber-600" }[step.status];
  const Icon = { running: Loader2, ok: CheckCircle, failed: XCircle, held: PauseCircle }[step.status];

  return (
    <div className="rounded border border-blue-200 bg-blue-50/40 p-2" data-testid="live-tool">
      <div className="flex flex-wrap items-center gap-2">
        <Icon className={`h-3.5 w-3.5 ${tone} ${step.status === "running" ? "animate-spin" : ""}`} />
        <span className="font-mono text-[11px] font-semibold">{step.tool}</span>
        <span className={`text-[10px] ${tone}`}>{label}</span>
        {step.ms !== undefined && <span className="text-[10px] text-muted-foreground">{secs(step.ms)}</span>}
      </div>

      <p className="mt-1 text-[10px] font-semibold uppercase text-muted-foreground">What the AI sent</p>
      <pre className="max-h-40 overflow-auto rounded bg-white p-1.5 text-[10px]">{JSON.stringify(step.input, null, 2)}</pre>
      {step.problems.length > 0 && (
        <ul className="mt-1 space-y-0.5" data-testid="live-problems">
          {step.problems.map((p, i) => (
            <li key={i} className="flex gap-1 text-[10px] text-amber-800">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              {p.message}
            </li>
          ))}
        </ul>
      )}

      {step.status === "held" && (
        <p className="mt-1 text-[10px] text-amber-800">The app is holding this change until the person agrees: they have to reply "yes" in the app's chat to release it.</p>
      )}
      {step.error && <p className="mt-1 text-[10px] text-red-700">{step.error}</p>}

      {step.calls.length > 0 && (
        <>
          <p className="mt-1 text-[10px] font-semibold uppercase text-muted-foreground">What it did in the app</p>
          <ul className="space-y-1" data-testid="live-calls">
            {step.calls.map((c, i) => (
              <li key={i} className="rounded bg-white p-1.5 text-[10px]">
                <span className="font-mono">
                  <span className="font-semibold">{c.kind === "request" ? c.method : c.kind}</span> {c.label}
                  {c.query ? `?${new URLSearchParams(Object.entries(c.query).map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v) : String(v)])).toString()}` : ""}
                </span>{" "}
                <span className={c.ok ? "text-green-700" : "text-red-700"}>
                  {c.status !== undefined ? c.status : c.ok ? "done" : "failed"}
                </span>{" "}
                <span className="text-muted-foreground">{secs(c.ms)}</span>
                {c.error && <span className="block text-red-700">{c.error}</span>}
                {c.body !== undefined && <pre className="mt-0.5 max-h-24 overflow-auto text-[9px] text-muted-foreground">{typeof c.body === "string" ? c.body : JSON.stringify(c.body, null, 2)}</pre>}
              </li>
            ))}
          </ul>
        </>
      )}

      {step.status !== "running" && step.result !== undefined && step.result !== null && (
        <>
          <p className="mt-1 text-[10px] font-semibold uppercase text-muted-foreground">What the app returned</p>
          {rows ? (
            <div className="overflow-auto rounded bg-white">
              <RowsTable rows={rows} />
            </div>
          ) : (
            <pre className="max-h-48 overflow-auto rounded bg-white p-1.5 text-[10px]">{json}</pre>
          )}
        </>
      )}
      {typeof step.chars === "number" && step.chars > 0 && (
        <p className="mt-0.5 text-[10px] text-muted-foreground" data-testid="live-size">
          {num(step.chars)} characters.{" "}
          {step.chars > REPLAY_CHARS && `The AI reads all of it now, but on later turns only the first ${num(REPLAY_CHARS)}. `}
          {step.cut && "Cut here for the screen; the AI still received everything."}
        </p>
      )}
    </div>
  );
}

function RowsTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  const shown = rows.slice(0, 8);
  const cols = [...new Set(shown.flatMap((r) => Object.keys(r)))].slice(0, 6);
  const cell = (v: unknown) => {
    const t = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
    return t.length > 40 ? `${t.slice(0, 40)}…` : t;
  };
  return (
    <>
      <table className="w-full text-[10px]">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            {cols.map((c) => (
              <th key={c} className="px-1.5 py-1 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i} className="border-b last:border-0">
              {cols.map((c) => (
                <td key={c} className="px-1.5 py-1 align-top">
                  {cell(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length && <p className="px-1.5 py-1 text-[10px] text-muted-foreground">…and {rows.length - shown.length} more rows.</p>}
    </>
  );
}
