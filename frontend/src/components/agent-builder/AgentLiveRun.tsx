"use client";

/**
 * The builder's live run: watch the agent work, step by step, with the app's own data.
 *
 * It runs the app's REAL chat loop (the same code customers use), as a person the builder picks, and shows each step
 * as it happens: what the AI was given, each model call (time, tokens, what it decided), each tool call with the
 * exact input it wrote and a warning when the input looks wrong, and the real data each tool returned.
 *
 * Tools that change data are NOT run unless "Run changes for real" is on: they are shown as not run and the
 * AI is told so, so the rest of the run can still be watched.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Ban, CheckCircle, ChevronDown, ChevronRight, Loader2, PauseCircle, RotateCcw, Send, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import {
  REPLAY_CHARS,
  applyEvent,
  beginRun,
  emptyRun,
  parseEvents,
  rowsOf,
  type AgentInfo,
  type LiveRun,
  type ModelStep,
  type ToolStep,
} from "@/lib/agent-live";
import type { AgentNodeSerialized } from "@/types/agent-builder";

interface Props {
  projectId: string;
  agentId: string;
  agentName: string;
  nodes: AgentNodeSerialized[];
}

interface Status {
  ok: boolean;
  reason?: string;
  agents?: Array<{ id: string; name: string; enabled: boolean }>;
  users?: Array<{ id: string; name: string; email: string | null; role: string | null }>;
  usersNote?: string | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
const DEFAULT_APP = "http://localhost:3000";

const store = {
  get(key: string): string | null {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key: string, value: string) {
    try {
      window.localStorage.setItem(key, value);
    } catch {
      /* a convenience only */
    }
  },
};

const secs = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
const num = (n: number) => n.toLocaleString();

export function AgentLiveRun({ projectId, agentId, agentName, nodes }: Props) {
  const [appUrl, setAppUrl] = useState(DEFAULT_APP);
  const [status, setStatus] = useState<Status | null>(null);
  const [checking, setChecking] = useState(false);
  const [asUserId, setAsUserId] = useState("");
  const [source, setSource] = useState<"draft" | "installed">("draft");
  const [allowChanges, setAllowChanges] = useState(false);
  const [run, setRun] = useState<LiveRun>(emptyRun());
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState(() => `live-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`);
  const [message, setMessage] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const running = run.status === "running";

  useEffect(() => {
    const saved = store.get(`forge.liveRun.app.${projectId}`);
    if (saved) setAppUrl(saved);
    const who = store.get(`forge.liveRun.user.${projectId}`);
    if (who) setAsUserId(who);
  }, [projectId]);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [run.steps.length, run.answer, run.status]);

  const check = useCallback(async () => {
    setChecking(true);
    store.set(`forge.liveRun.app.${projectId}`, appUrl);
    try {
      const s = await api.get<Status>(`/api/projects/${projectId}/agent-definitions/debug/status?app_url=${encodeURIComponent(appUrl)}`);
      setStatus(s);
      if (s.ok && s.users?.length) {
        setAsUserId((cur) => (cur && s.users!.some((u) => u.id === cur) ? cur : s.users![0].id));
      }
    } catch (e) {
      setStatus({ ok: false, reason: e instanceof Error ? e.message : "Could not check the app." });
    } finally {
      setChecking(false);
    }
  }, [projectId, appUrl]);

  const reset = useCallback(() => {
    setRun(emptyRun());
    setMessage("");
    setSessionId(`live-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`);
  }, []);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || running || !status?.ok || !asUserId) return;
    setInput("");
    setMessage(text);
    setRun((prev) => ({ ...beginRun(prev, text), allowChanges, draft: source === "draft" }));
    const token = typeof window !== "undefined" ? window.localStorage.getItem("token") : null;
    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/agent-definitions/${agentId}/debug-run`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          app_url: appUrl,
          message: text,
          as_user_id: asUserId,
          session_id: sessionId,
          conversation_id: run.conversationId ?? null,
          allow_changes: allowChanges,
          use_draft: source === "draft",
          graph: source === "draft" ? { id: agentId, name: agentName, nodes, edges: [] } : null,
        }),
      });
      if (!res.ok || !res.body) {
        const detail = await res.text().catch(() => "");
        setRun((r) => applyEvent(r, { type: "error", message: detail || `The platform answered ${res.status}.` }));
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseEvents(buffer);
        buffer = parsed.rest;
        if (parsed.events.length) setRun((r) => parsed.events.reduce(applyEvent, r));
      }
      setRun((r) => (r.status === "running" ? applyEvent(r, { type: "error", message: "The run ended without finishing." }) : r));
    } catch (e) {
      setRun((r) => applyEvent(r, { type: "error", message: e instanceof Error ? e.message : "The connection broke." }));
    }
  }, [input, running, status, asUserId, allowChanges, source, projectId, agentId, agentName, nodes, appUrl, sessionId, run.conversationId]);

  const people = status?.users ?? [];

  return (
    <div className="flex h-full flex-col" data-testid="live-run">
      {/* Controls */}
      <div className="space-y-2 border-b p-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-[10px] text-muted-foreground">
            The running app
            <Input
              aria-label="App address"
              className="mt-0.5 h-7 w-52 text-xs"
              value={appUrl}
              onChange={(e) => setAppUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && check()}
            />
          </label>
          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={check} disabled={checking}>
            {checking ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
            Connect
          </Button>
          {status?.ok && (
            <>
              <label className="text-[10px] text-muted-foreground">
                Run as
                <select
                  aria-label="Run as"
                  className="mt-0.5 block h-7 rounded border bg-transparent px-1 text-xs"
                  value={asUserId}
                  onChange={(e) => {
                    setAsUserId(e.target.value);
                    store.set(`forge.liveRun.user.${projectId}`, e.target.value);
                  }}
                >
                  {people.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name}
                      {u.role ? ` (${u.role})` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-[10px] text-muted-foreground">
                Agent
                <select
                  aria-label="Which agent"
                  className="mt-0.5 block h-7 rounded border bg-transparent px-1 text-xs"
                  value={source}
                  onChange={(e) => setSource(e.target.value as "draft" | "installed")}
                >
                  <option value="draft">As drawn now</option>
                  <option value="installed">As applied in the app</option>
                </select>
              </label>
              <label className="flex items-center gap-1 pb-1 text-[10px]">
                <input type="checkbox" aria-label="Run changes for real" checked={allowChanges} onChange={(e) => setAllowChanges(e.target.checked)} />
                Run changes for real
              </label>
              <Button size="sm" variant="ghost" className="h-7 text-[10px]" onClick={reset} disabled={running}>
                <RotateCcw className="mr-1 h-3 w-3" />
                New conversation
              </Button>
            </>
          )}
        </div>
        {status && !status.ok && (
          <p role="alert" className="rounded border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-800">
            {status.reason}
          </p>
        )}
        {status?.ok && (
          <p className="text-[10px] text-muted-foreground">
            Connected. It runs the app's real chat as {people.find((u) => u.id === asUserId)?.name ?? "that person"}, so the data is what they would see.
            {allowChanges
              ? " Changes WILL really be made."
              : " Anything that changes data is shown but not run."}
            {status.usersNote ? ` ${status.usersNote}` : ""}
          </p>
        )}
        {!status && <p className="text-[10px] text-muted-foreground">Connect to the app while it is running to watch the agent work on real data.</p>}
      </div>

      {/* The run */}
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {message && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl bg-primary px-3 py-1.5 text-xs text-primary-foreground">{message}</div>
          </div>
        )}

        {run.notes.length > 0 && (
          <div className="rounded border border-amber-300 bg-amber-50 p-2 text-[11px] text-amber-800" data-testid="live-notes">
            {run.notes.map((n, i) => (
              <p key={i}>{n}</p>
            ))}
          </div>
        )}

        {run.agent && <GivenCard agent={run.agent} run={run} />}

        {run.steps.map((s, i) => (s.kind === "model" ? <ModelCard key={i} step={s} /> : <ToolCard key={i} step={s} />))}

        {running && (
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" /> Working…
          </div>
        )}

        {run.status === "done" && run.answer.trim() && (
          <div className="rounded-lg border bg-muted/30 p-2" data-testid="live-answer">
            <p className="mb-0.5 text-[10px] font-semibold uppercase text-muted-foreground">What the person would read</p>
            <p className="whitespace-pre-wrap text-xs">{run.answer.trim()}</p>
          </div>
        )}
        {run.status === "blocked" && <p className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-700">Refused: {run.blocked}</p>}
        {run.status === "error" && <p role="alert" className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-700">{run.error}</p>}

        {(run.status === "done" || run.status === "blocked") && run.totals.modelCalls > 0 && (
          <p className="text-[10px] text-muted-foreground" data-testid="live-totals">
            {secs(run.totals.ms)} in all · {run.totals.modelCalls} model {run.totals.modelCalls === 1 ? "call" : "calls"} · {run.totals.toolCalls}{" "}
            {run.totals.toolCalls === 1 ? "tool call" : "tool calls"} · {num(run.totals.inputTokens)} tokens in, {num(run.totals.outputTokens)} out
          </p>
        )}
        <div ref={endRef} />
      </div>

      <div className="border-t p-2">
        <div className="flex gap-2">
          <Input
            aria-label="Message"
            className="h-8 text-xs"
            placeholder={status?.ok ? "Type a message to the agent…" : "Connect to the app first"}
            value={input}
            disabled={!status?.ok || running}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <Button size="sm" className="h-8" onClick={send} disabled={!status?.ok || running || !input.trim()} aria-label="Send">
            {running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── cards ─────────────────────────────────────────────────────────────────

function GivenCard({ agent, run }: { agent: AgentInfo; run: LiveRun }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded border bg-white" data-testid="live-given">
      <button type="button" className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span className="text-[11px] font-semibold">What the AI is given</span>
        <span className="text-[10px] text-muted-foreground">
          {run.user ? `running as ${run.user.name}${run.user.role ? ` (${run.user.role})` : ""} · ` : ""}
          {agent.tools.length} tools · instructions {num(agent.systemPrompt.length)} characters{run.draft ? " · the draft" : " · as applied"}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t p-2">
          <div>
            <p className="text-[10px] font-semibold uppercase text-muted-foreground">Instructions (exactly as the model gets them)</p>
            <pre className="mt-0.5 max-h-56 overflow-auto whitespace-pre-wrap rounded bg-muted/40 p-2 text-[10px]">{agent.systemPrompt}</pre>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase text-muted-foreground">Tools it can use</p>
            <ul className="mt-0.5 space-y-1">
              {agent.tools.map((t) => (
                <li key={t.name} className="text-[10px]">
                  <span className="font-mono font-semibold">{t.name}</span>{" "}
                  {t.changes && <Badge variant="secondary" className="px-1 py-0 text-[8px]">changes data{t.confirm ? " · asks first" : ""}</Badge>}
                  <span className="block text-muted-foreground">{t.description}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

function ModelCard({ step }: { step: ModelStep }) {
  return (
    <div className="rounded border border-purple-200 bg-purple-50/50 p-2" data-testid="live-model">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary" className="bg-purple-100 px-1 py-0 text-[9px] text-purple-700">Step {step.n}</Badge>
        <span className="text-[11px] font-semibold">The AI worked on it for {secs(step.ms)}</span>
        <span className="text-[10px] text-muted-foreground">
          {num(step.inputTokens)} tokens in · {num(step.outputTokens)} out · given {step.messages} {step.messages === 1 ? "message" : "messages"}
        </span>
      </div>
      {step.said && <p className="mt-1 whitespace-pre-wrap text-[11px] italic text-purple-900">“{step.said}”</p>}
      <p className="mt-1 text-[10px] text-muted-foreground">
        {step.toolsRequested.length ? (
          <>
            It decided to use: <span className="font-mono">{step.toolsRequested.join(", ")}</span>
          </>
        ) : (
          "It had what it needed and answered."
        )}
      </p>
    </div>
  );
}

function ToolCard({ step }: { step: ToolStep }) {
  const rows = useMemo(() => rowsOf(step.result), [step.result]);
  const json = useMemo(() => {
    try {
      return JSON.stringify(step.result, null, 2) ?? "";
    } catch {
      return String(step.result);
    }
  }, [step.result]);
  const label = { running: "running…", ok: "worked", failed: "failed", held: "held: waiting for a yes", not_run: "not run" }[step.status];
  const tone = { running: "text-blue-600", ok: "text-green-600", failed: "text-red-600", held: "text-amber-600", not_run: "text-amber-600" }[step.status];
  const Icon = { running: Loader2, ok: CheckCircle, failed: XCircle, held: PauseCircle, not_run: Ban }[step.status];

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

      {step.notRunReason && (
        <p className="mt-1 text-[10px] text-amber-800">
          Not run: {step.notRunReason}. The AI was told so and carried on. Switch on "Run changes for real" to let it run.
        </p>
      )}
      {step.status === "held" && (
        <p className="mt-1 text-[10px] text-amber-800">The app is holding this change until the person agrees. Reply "yes" in this conversation to release it.</p>
      )}
      {step.error && <p className="mt-1 text-[10px] text-red-700">{step.error}</p>}

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
