/**
 * Watching the app's real chat live — the feed. Forge runtime — do not remove.
 *
 * The builder (in TTF) can connect to a running development app and see every chat the app's own people have, as
 * it happens: who wrote what, each step the runtime takes, each model call, each tool and the real request behind it.
 * This file is the small in-memory feed between the real chat route and that connection.
 *
 * It is INERT unless it should not be: it does nothing in production, and it records nothing unless a watcher is
 * connected right now. When the last watcher leaves everything it kept is thrown away. It only ever COPIES events;
 * the chat itself behaves exactly as it would without it (see `observeDeps`).
 *
 * Because this shows real people's messages and what the tools returned, the only way to subscribe is the debug
 * route, which needs the platform's secret (api-agent/debug-route.ts).
 */
import { wireResult, type DebugEvent } from "./debug";
import type { AgentDeps, AgentEvent, TraceEvent } from "./types";

/** What the feed carries: the chat's own events, a debug run's extras, and the runtime's phases. */
export type WatchEvent =
  | AgentEvent
  | DebugEvent
  | TraceEvent
  /** `workflow` is present when the run is an assistant step of a workflow (no person is chatting): which workflow, which run, which step. */
  | { type: "run_start"; agentId: string; agentName: string; user: { id: string; name: string | null; role: string | null; email: string | null }; message: string; conversationId: string | null; workflow?: { id: string; runId: string; stepId: string } }
  | { type: "model_start"; n: number; messages: number; tools: number; systemChars: number }
  | { type: "model_failed"; n: number; ms: number; error: string };

/** An event as it travels: which run it belongs to and when (ms since that run began). */
export type Stamped = WatchEvent & { runId: string; t: number; at?: number };

export interface WatchRun {
  id: string;
  startedAt: number;
  finished: boolean;
  events: Stamped[];
}

const MAX_RUNS = 12;
const MAX_EVENTS_PER_RUN = 600;

class Feed {
  runs = new Map<string, WatchRun>();
  subs = new Set<(e: Stamped) => void>();
}

/** One feed for the whole server, however many bundles import this file. */
const g = globalThis as unknown as { __forgeWatchFeed?: Feed };
const feed = (): Feed => (g.__forgeWatchFeed ??= new Feed());

/** Whether anything may be recorded right now: development only, and only with a watcher connected. */
export function watching(): boolean {
  return process.env.NODE_ENV !== "production" && feed().subs.size > 0;
}

export function newRunId(): string {
  return `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Record and pass on one event. A no-op when nobody watches. */
export function publish(runId: string, startedAt: number, e: WatchEvent): void {
  if (!watching()) return;
  const f = feed();
  const stamped = { ...e, runId, t: Date.now() - startedAt } as Stamped;
  let run = f.runs.get(runId);
  if (!run) {
    run = { id: runId, startedAt, finished: false, events: [] };
    f.runs.set(runId, run);
    if (f.runs.size > MAX_RUNS) {
      const oldest = [...f.runs.values()].sort((a, b) => a.startedAt - b.startedAt)[0];
      if (oldest) f.runs.delete(oldest.id);
    }
  }
  if (run.events.length < MAX_EVENTS_PER_RUN) run.events.push(stamped);
  if (e.type === "done" || e.type === "error" || e.type === "blocked") run.finished = true;
  for (const fn of f.subs) {
    try {
      fn(stamped);
    } catch {
      /* one watcher's trouble is not another's */
    }
  }
}

/** Whose chats to watch: everyone's (no filter), those of everyone holding a role, or one person's. A person outranks a
 *  role. A role matches whatever its capitals, as the app's own access checks do. */
export interface WatchFilter {
  role?: string;
  userId?: string;
}

export function matchesFilter(user: { id?: string | null; role?: string | null } | null | undefined, filter: WatchFilter): boolean {
  if (filter.userId) return !!user && String(user.id ?? "") === filter.userId;
  if (filter.role) return !!user?.role && user.role.toLowerCase() === filter.role.toLowerCase();
  return true;
}

/**
 * Start watching. `onEvent` gets everything recorded so far (so a watcher that connects mid-chat sees it from its
 * start) and then every new event. The returned function stops watching; when the last watcher stops, the feed
 * forgets everything it kept.
 *
 * With a `filter`, only the chats of that role or person are ever passed on: a chat is judged by who began it (its
 * `run_start`, always the first event of a chat) and the rest of its events follow it. The builder watching one role
 * is never sent another's.
 */
export function subscribe(onEvent: (e: Stamped) => void, filter: WatchFilter = {}): () => void {
  const f = feed();
  const everyone = !filter.role && !filter.userId;
  const allowed = new Set<string>();
  const deliver = (e: Stamped) => {
    if (everyone) return onEvent(e);
    if (e.type === "run_start") {
      if (!matchesFilter((e as { user?: { id?: string; role?: string | null } }).user, filter)) return;
      allowed.add(e.runId);
      return onEvent(e);
    }
    if (allowed.has(e.runId)) onEvent(e);
  };
  for (const run of [...f.runs.values()].sort((a, b) => a.startedAt - b.startedAt)) for (const e of run.events) deliver(e);
  f.subs.add(deliver);
  return () => {
    f.subs.delete(deliver);
    if (f.subs.size === 0) f.runs.clear();
  };
}

/** For tests: forget everything. */
export function resetFeed(): void {
  const f = feed();
  f.runs.clear();
  f.subs.clear();
}

// ── an observer, not a participant ────────────────────────────────────────

/**
 * `base` with its model calls announced and timed and its phases reported. Everything it returns is what `base`
 * returned, and a failure is rethrown, so the chat behaves exactly as without it.
 */
export function observeDeps(base: AgentDeps, send: (e: WatchEvent) => void): AgentDeps {
  let n = 0;
  return {
    ...base,
    trace: (e) => send(e),
    async callModel(req, onText) {
      const call = ++n;
      send({ type: "model_start", n: call, messages: req.messages.length, tools: req.tools.length, systemChars: req.system.length });
      const started = Date.now();
      try {
        const out = await base.callModel(req, onText);
        send({
          type: "model_call",
          n: call,
          ms: Date.now() - started,
          inputTokens: out.usage.inputTokens,
          outputTokens: out.usage.outputTokens,
          messages: req.messages.length,
          toolsRequested: out.content.filter((b) => b.type === "tool_use").map((b) => (b as { name: string }).name),
        });
        return out;
      } catch (e) {
        send({ type: "model_failed", n: call, ms: Date.now() - started, error: e instanceof Error ? e.message : String(e) });
        throw e;
      }
    },
  };
}

/** What a chat event looks like on the feed: a tool's result goes whole (cut if huge), unlike the customer's own stream. */
export function feedEvent(e: AgentEvent): WatchEvent {
  return e.type === "tool_result" ? ({ ...e, ...wireResult(e.result) } as WatchEvent) : e;
}

