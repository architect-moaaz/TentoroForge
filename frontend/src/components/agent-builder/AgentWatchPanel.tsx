"use client";

/**
 * Watch live: the real chats from the running app, as they happen.
 *
 * Next to the canvas. You connect once; then whenever anyone chats with the assistant in the app, the flowchart
 * lights up box by box, and this panel shows the message that came in, where the chat has got to, the checklist of
 * tools the AI chose (ticking off as each finishes), each step with the real inputs, requests and data, and the
 * reply that was handed back.
 *
 * It only watches. It cannot stop or change a chat, and it works only against a development app.
 *
 * Where the app runs: if TentoroForge is on the builder's own computer, the app is a localhost address to type. If it is on a
 * server, the server cannot see the builder's localhost, so the panel shows "Your computer": a one-time code and one command to
 * run where the app is (it opens a reverse SSH tunnel, see lib/watch-tunnel.ts), and the live state of that tunnel.
 */
import { useEffect, useRef, useState } from "react";
import { Check, Circle, Copy, Laptop, Loader2, PauseCircle, Radio, Unplug, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { checklist, stageOf, type CheckStatus, type WatchRun, type WatchState, type WatchWho } from "@/lib/agent-watch";
import type { ModelStep } from "@/lib/agent-live";
import { clock, connectorCommands, secondsLeft, summarise, validPort } from "@/lib/watch-tunnel";
import { ModelCard, ToolCard, num, secs } from "./AgentRunCards";
import type { Link } from "./useAgentWatch";
import { useWatchTunnel } from "./useWatchTunnel";

interface Props {
  state: WatchState;
  link: Link;
  reason: string | null;
  suggestedUrl: string | null;
  projectId: string;
  onConnect: (appUrl: string, who: WatchWho) => void;
  onDisconnect: () => void;
  onSelect: (id: string) => void;
  onFollow: () => void;
}

const DEFAULT_APP = "http://localhost:3000";

const LINK_TEXT: Record<Link, string> = {
  idle: "Not connected",
  checking: "Checking the app…",
  connecting: "Connecting…",
  connected: "Connected",
  reconnecting: "Connection dropped, reconnecting…",
  failed: "Could not connect",
};
const LINK_DOT: Record<Link, string> = {
  idle: "bg-slate-400",
  checking: "bg-amber-400",
  connecting: "bg-amber-400",
  connected: "bg-green-500",
  reconnecting: "bg-amber-400",
  failed: "bg-red-500",
};

const short = (text: string, n = 38) => (text.length > n ? `${text.slice(0, n)}…` : text);

interface WhoOptions {
  roles: string[];
  people: Array<{ id: string; name: string; role: string | null }>;
}

/** The dropdown's value for a choice, and back: "all", "role:Admin" or "user:<id>". */
const whoValue = (w: WatchWho): string => (w.userId ? `user:${w.userId}` : w.role ? `role:${w.role}` : "all");
const whoOf = (value: string): WatchWho => (value.startsWith("user:") ? { userId: value.slice(5) } : value.startsWith("role:") ? { role: value.slice(5) } : {});

export function AgentWatchPanel({ state, link, reason, suggestedUrl, projectId, onConnect, onDisconnect, onSelect, onFollow }: Props) {
  const [appUrl, setAppUrl] = useState(DEFAULT_APP);
  const [who, setWho] = useState<WatchWho>({});
  const [options, setOptions] = useState<WhoOptions>({ roles: [], people: [] });
  const [optionsNote, setOptionsNote] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const tun = useWatchTunnel(projectId);
  // Where the app runs: a localhost address to type, or (platform on a server) the builder's own computer through a tunnel.
  const viaTunnel = tun.tunnel.enabled;
  const [portText, setPortText] = useState("3000");
  const [copied, setCopied] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const run = state.selected ? state.runs[state.selected] : undefined;
  const connected = link === "connected" || link === "reconnecting";
  const working = link === "checking" || link === "connecting";

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(`forge.liveRun.app.${projectId}`);
      if (saved) setAppUrl(saved);
    } catch {
      /* a convenience only */
    }
  }, [projectId]);

  // The app's own roles and people: who there is to watch.
  useEffect(() => {
    let live = true;
    try {
      const saved = window.localStorage.getItem(`forge.watch.who.${projectId}`);
      if (saved) setWho(whoOf(saved));
    } catch {
      /* a convenience only */
    }
    api
      .get<WhoOptions & { peopleNote?: string | null }>(`/api/projects/${projectId}/agent-definitions/handoff-options`)
      .then((o) => {
        if (!live) return;
        setOptions({ roles: o.roles ?? [], people: o.people ?? [] });
        setOptionsNote(o.peopleNote ?? null);
      })
      .catch(() => live && setOptionsNote("The app's roles and people could not be listed, so everyone's chats are watched."));
    return () => {
      live = false;
    };
  }, [projectId]);

  const connect = (address?: string, chosen: WatchWho = who) => {
    const where = viaTunnel ? "tunnel" : address ?? appUrl;
    if (address && !viaTunnel) setAppUrl(address);
    try {
      if (!viaTunnel) window.localStorage.setItem(`forge.liveRun.app.${projectId}`, where);
      window.localStorage.setItem(`forge.watch.who.${projectId}`, whoValue(chosen));
    } catch {
      /* a convenience only */
    }
    onConnect(where, chosen);
  };

  // The port the app runs on is remembered, and the code's countdown ticks only while there is a code to count down.
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(`forge.watch.appPort.${projectId}`);
      if (saved && validPort(saved)) setPortText(saved);
    } catch {
      /* a convenience only */
    }
  }, [projectId]);
  useEffect(() => {
    if (tun.tunnel.appPort && validPort(String(tun.tunnel.appPort))) setPortText(String(tun.tunnel.appPort));
  }, [tun.tunnel.appPort]);
  useEffect(() => {
    if (!tun.pairing) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [tun.pairing]);
  // Once the computer has connected, the setup box has done its job.
  useEffect(() => {
    if (tun.tunnel.connected && tun.pairing) tun.dismissPairing();
  }, [tun.tunnel.connected]); // eslint-disable-line react-hooks/exhaustive-deps
  const choosePort = (text: string) => {
    setPortText(text);
    try {
      if (validPort(text)) window.localStorage.setItem(`forge.watch.appPort.${projectId}`, text);
    } catch {
      /* a convenience only */
    }
  };
  const copy = async (what: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
      setTimeout(() => setCopied((c) => (c === what ? null : c)), 2000);
    } catch {
      setCopied(null); // the command is on screen to select by hand
    }
  };
  const port = validPort(portText);
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const commands = tun.pairing && port ? connectorCommands(origin, tun.pairing.code, port) : null;
  const left = tun.pairing ? secondsLeft(tun.pairing, now) : 0;
  const summary = summarise(tun.tunnel);

  // Changing whom to watch takes effect at once: while connected it reconnects to the new choice.
  const chooseWho = (value: string) => {
    const next = whoOf(value);
    setWho(next);
    if (connected || working) connect(undefined, next);
  };

  const personName = state.who.userId ? options.people.find((p) => p.id === state.who.userId)?.name ?? "that person" : null;
  const watching = personName ? `${personName}'s chats only` : state.who.role ? `${state.who.role} chats only` : "everyone's chats";
  const watchedName = personName ?? (state.who.role ? `anyone with the role ${state.who.role}` : "anyone");

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [run?.live.steps.length, run?.live.answer.length, run?.finished]);

  return (
    <aside className="flex h-full w-[420px] shrink-0 flex-col border-l bg-white" data-testid="watch-panel" aria-label="Watch live">
      {/* Connection */}
      <div className="space-y-2 border-b p-3">
        <div className="flex items-center gap-2">
          <Radio className="h-4 w-4 text-sky-600" />
          <span className="text-xs font-semibold">Watch live</span>
          <span className="ml-auto flex items-center gap-1.5 text-[10px]" data-testid="watch-link">
            <span className={`inline-block h-2 w-2 rounded-full ${LINK_DOT[link]} ${link === "connected" ? "" : working || link === "reconnecting" ? "animate-pulse" : ""}`} />
            {LINK_TEXT[link]}
          </span>
        </div>
        {viaTunnel && (
          <div className="space-y-1.5 rounded border p-2" data-testid="watch-tunnel">
            <div className="flex items-start gap-1.5 text-[11px]">
              <Laptop className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-600" />
              <div className="min-w-0 flex-1">
                <span className="font-semibold">Your computer</span>
                <p
                  className={`text-[11px] ${summary.tone === "good" ? "text-green-700" : summary.tone === "warn" ? "text-amber-800" : "text-muted-foreground"}`}
                  data-testid="tunnel-state"
                  data-tone={summary.tone}
                >
                  {summary.text}
                </p>
              </div>
            </div>
            {!tun.tunnel.registered && tun.tunnel.hosted?.vercel && (
              <p className="text-[10px] text-muted-foreground" data-testid="tunnel-vercel">
                This app is also hosted on Vercel{tun.tunnel.hosted.vercel.url ? ` (${tun.tunnel.hosted.vercel.url})` : ""}. Watching a Vercel-hosted app is not available yet: this connects the copy you run on your own computer.
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant={tun.tunnel.connected ? "outline" : "default"} className="h-7 text-xs" onClick={() => void tun.pair()} disabled={tun.asking}>
                {tun.asking ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                {tun.pairing ? "New code" : tun.tunnel.registered ? "Connect again" : "Connect your computer"}
              </Button>
              {tun.tunnel.registered && (
                <button type="button" className="text-[10px] text-muted-foreground underline" onClick={() => void tun.forget()} data-testid="tunnel-forget">
                  Disconnect this computer
                </button>
              )}
            </div>
            {tun.pairing && (
              <div className="space-y-1.5 rounded bg-slate-50 p-2 text-[10px]" data-testid="tunnel-setup">
                <label className="block text-muted-foreground">
                  The port your app runs on (on your computer)
                  <Input aria-label="App port" className="mt-0.5 h-6 w-24 text-xs" value={portText} onChange={(e) => choosePort(e.target.value)} inputMode="numeric" />
                </label>
                {!port && (
                  <p className="text-red-700" role="alert">
                    That is not a port: use a number from 1 to 65535, like 3000.
                  </p>
                )}
                <p className="text-muted-foreground">
                  In your app&apos;s folder (the one with package.json) run this. It checks your app and the server, connects, and reconnects by itself if the network drops. Leave it running.
                </p>
                {commands && (
                  <>
                    {([["unix", "Mac / Linux", commands.unix], ["windows", "Windows PowerShell", commands.windows]] as const).map(([key, title, text]) => (
                      <div key={key}>
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{title}</span>
                          <button type="button" className="flex items-center gap-1 text-sky-700 underline" onClick={() => void copy(key, text)} data-testid={`copy-${key}`}>
                            <Copy className="h-3 w-3" />
                            {copied === key ? "Copied" : "Copy"}
                          </button>
                        </div>
                        <pre className="mt-0.5 overflow-x-auto whitespace-pre-wrap break-all rounded border bg-white p-1.5 font-mono text-[10px]" data-testid={`command-${key}`}>{text}</pre>
                      </div>
                    ))}
                  </>
                )}
                <p className={left > 0 ? "text-muted-foreground" : "text-red-700"} data-testid="tunnel-code-clock">
                  Code {tun.pairing.code}: {left > 0 ? `works once, for ${clock(left)} more.` : "expired. Press New code."}
                </p>
              </div>
            )}
            {tun.problem && (
              <p className="text-[10px] text-red-700" role="alert" data-testid="tunnel-problem">
                {tun.problem}
              </p>
            )}
          </div>
        )}
        <div className="flex items-end gap-2">
          {!viaTunnel && (
            <label className="flex-1 text-[10px] text-muted-foreground">
              The running app
              <Input
                aria-label="App address"
                className="mt-0.5 h-7 text-xs"
                value={appUrl}
                disabled={connected || working}
                onChange={(e) => setAppUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !connected && !working && connect()}
              />
            </label>
          )}
          {viaTunnel && <span className="flex-1 text-[10px] text-muted-foreground">Then watch the chats on it:</span>}
          {connected || working ? (
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onDisconnect}>
              <Unplug className="mr-1 h-3 w-3" />
              Disconnect
            </Button>
          ) : (
            <Button
              size="sm"
              className="h-7 text-xs"
              onClick={() => connect()}
              disabled={viaTunnel && !tun.tunnel.connected}
              title={viaTunnel && !tun.tunnel.connected ? "Connect your computer first (above)" : undefined}
            >
              Connect
            </Button>
          )}
        </div>
        <label className="block text-[10px] text-muted-foreground">
          Whose chats to watch
          <select
            aria-label="Who to watch"
            className="mt-0.5 block h-7 w-full rounded border bg-transparent px-1 text-xs"
            value={whoValue(who)}
            onChange={(e) => chooseWho(e.target.value)}
          >
            <option value="all">Everyone</option>
            {options.roles.length > 0 && (
              <optgroup label="Anyone with the role">
                {options.roles.map((r) => (
                  <option key={r} value={`role:${r}`}>
                    {r}
                  </option>
                ))}
              </optgroup>
            )}
            {options.people.length > 0 && (
              <optgroup label="One person">
                {options.people.map((p) => (
                  <option key={p.id} value={`user:${p.id}`}>
                    {p.name}
                    {p.role ? ` (${p.role})` : ""}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </label>
        {optionsNote && options.roles.length === 0 && options.people.length === 0 && <p className="text-[10px] text-muted-foreground">{optionsNote}</p>}
        {link === "failed" && reason && (
          <div role="alert" className="flex flex-wrap items-center gap-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-800">
            <span>{reason}</span>
            {suggestedUrl && (
              <Button size="sm" variant="outline" className="h-6 text-[10px]" onClick={() => connect(suggestedUrl)}>
                Use {suggestedUrl}
              </Button>
            )}
          </div>
        )}
        {link === "connected" && state.agents.length > 0 && (
          <p className="text-[10px] text-muted-foreground" data-testid="watch-connected-to">
            Connected to the app's {state.agents.map((a) => a.name).join(", ")}. Verified with this project's key. Watching {watching}.
          </p>
        )}
        <p className="text-[10px] text-muted-foreground">
          Shows real chats from this development app, including what the tools return. It connects as an observer, not as any role or person: the choice above only decides whose chats are sent to you. It only watches: it cannot change or stop a chat.
        </p>
      </div>

      {/* Chats */}
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {!connected && !working && state.order.length === 0 && (
          <p className="text-[11px] text-muted-foreground">Start your app, choose whose chats to watch, press Connect, then chat with the assistant in the app. The flowchart will move as it works.</p>
        )}
        {connected && state.order.length === 0 && (
          <div className="flex items-center gap-2 rounded border border-dashed p-3 text-[11px] text-muted-foreground" data-testid="watch-waiting">
            <Loader2 className="h-3 w-3 animate-spin" />
            Waiting for a chat from {watchedName}. Open the app{state.who.role || state.who.userId ? " signed in as them" : ""} and send the assistant a message.
          </div>
        )}

        {state.order.length > 0 && (
          <div className="flex flex-wrap items-center gap-1" data-testid="watch-runs">
            {state.order.slice(0, 6).map((id) => {
              const r = state.runs[id];
              const sel = id === state.selected;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => onSelect(id)}
                  aria-pressed={sel}
                  className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${sel ? "border-sky-500 bg-sky-50" : "hover:bg-muted"}`}
                >
                  {r.finished ? r.live.status === "done" ? <Check className="h-3 w-3 text-green-600" /> : <XCircle className="h-3 w-3 text-red-600" /> : <Loader2 className="h-3 w-3 animate-spin text-sky-600" />}
                  {r.live.user?.name ?? "Someone"}: “{short(r.live.message ?? "", 24)}”
                </button>
              );
            })}
            {!state.follow && (
              <button type="button" className="text-[10px] text-sky-700 underline" onClick={onFollow}>
                Follow the newest
              </button>
            )}
          </div>
        )}

        {run && <RunView run={run} />}
        <div ref={endRef} />
      </div>
    </aside>
  );
}

// ── one chat ──────────────────────────────────────────────────────────────

const CHECK_ICON: Record<CheckStatus, React.ReactNode> = {
  waiting: <Circle className="h-3.5 w-3.5 text-slate-400" />,
  running: <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-600" />,
  ok: <Check className="h-3.5 w-3.5 text-green-600" />,
  failed: <XCircle className="h-3.5 w-3.5 text-red-600" />,
  held: <PauseCircle className="h-3.5 w-3.5 text-amber-600" />,
};
const CHECK_TEXT: Record<CheckStatus, string> = {
  waiting: "waiting",
  running: "running",
  ok: "done",
  failed: "failed",
  held: "held: waiting for a yes",
};

function RunView({ run }: { run: WatchRun }) {
  const live = run.live;
  const groups = checklist(live);
  const running = !run.finished;

  return (
    <div className="space-y-2" data-testid="watch-run">
      {/* Where it starts: what came in */}
      <div className="rounded-lg border border-sky-200 bg-sky-50 p-2" data-testid="watch-message-in">
        <p className="text-[10px] font-semibold uppercase text-sky-700">
          Message in{live.user?.name ? ` from ${live.user.name}` : ""}
          {live.user?.role ? ` (${live.user.role})` : ""}
        </p>
        <p className="mt-0.5 whitespace-pre-wrap text-xs">{live.message}</p>
      </div>

      <div className="flex items-center gap-2 text-[11px]" data-testid="watch-stage">
        {running ? <Loader2 className="h-3 w-3 animate-spin text-sky-600" /> : live.status === "done" ? <Check className="h-3 w-3 text-green-600" /> : <XCircle className="h-3 w-3 text-red-600" />}
        <span className="font-medium">{stageOf(run)}</span>
      </div>

      {/* What the AI chose */}
      {groups.map((g) => (
        <div key={g.step} className="rounded border bg-slate-50 p-2" data-testid="watch-checklist">
          <p className="text-[10px] font-semibold uppercase text-muted-foreground">The AI chose (call {g.step})</p>
          <ul className="mt-1 space-y-1">
            {g.items.map((it, i) => (
              <li key={i} className="flex items-center gap-2 text-[11px]" data-testid="watch-check-item" data-status={it.status}>
                {CHECK_ICON[it.status]}
                <span className="font-mono">{it.tool}</span>
                <span className="text-[10px] text-muted-foreground">
                  {CHECK_TEXT[it.status]}
                  {it.ms !== undefined ? ` · ${secs(it.ms)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {/* Each step, with the real inputs, requests and data */}
      {live.steps.map((s, i) =>
        s.kind === "model" ? (
          <ModelCard key={i} step={s as ModelStep} last={!running && i === live.steps.length - 1 && live.answer.trim() !== ""} pending={(s as ModelStep).running ? live.pending : undefined} />
        ) : (
          <ToolCard key={i} step={s} />
        ),
      )}

      {/* Where it ends: what went back */}
      {live.status === "done" && live.answer.trim() && (
        <div className="rounded-lg border border-green-300 bg-green-50 p-2" data-testid="watch-reply">
          <p className="text-[10px] font-semibold uppercase text-green-700">Reply handed back</p>
          <p className="mt-0.5 whitespace-pre-wrap text-xs">{live.answer.trim()}</p>
        </div>
      )}
      {live.status === "blocked" && <p className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-700">Refused: {live.blocked}</p>}
      {live.status === "error" && <p role="alert" className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-700">{live.error}</p>}
      {run.finished && live.totals.modelCalls > 0 && (
        <p className="text-[10px] text-muted-foreground" data-testid="watch-totals">
          {secs(live.totals.ms)} in all · {live.totals.modelCalls} AI {live.totals.modelCalls === 1 ? "call" : "calls"} · {live.totals.toolCalls}{" "}
          {live.totals.toolCalls === 1 ? "tool call" : "tool calls"} · {num(live.totals.inputTokens)} tokens in, {num(live.totals.outputTokens)} out
        </p>
      )}
    </div>
  );
}
