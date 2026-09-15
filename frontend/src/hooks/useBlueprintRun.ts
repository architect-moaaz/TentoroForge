"use client";

/**
 * The Blueprint engine's run, as React state.
 *
 * `POST /api/projects/{id}/generate/blueprint` has streamed a complete SDLC
 * feed since it was written — `started`, `plan`, `node:start`, `node:done`,
 * `forecast`, `usage`, `done`, `error` — and nothing has ever consumed it. The
 * product UI drives `routers/generate.py`, which does not import
 * `services.blueprint` at all, so the 20-node DAG, its verification edges and
 * its projections were unreachable from anything a user touches (§1, §115).
 * This hook is the reader that closes that gap.
 *
 * Two units, never conflated. `nodesDone/nodesTotal` is progress through the
 * graph; `callsDone` counts executor calls, which a fan-out node multiplies —
 * `page_layouts` alone makes one call per page. Reporting calls as nodes is
 * what made an earlier progress bar read "44 of 22" and keep climbing.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

/** What the orchestrator says about one node, as the run unfolds. */
export type NodeState = "waiting" | "running" | "done" | "failed";

export interface RunNode {
  key: string;
  state: NodeState;
  /** Fan-out nodes report the subject they are working on (a page id). */
  subject?: string;
  /** Executor calls attributed to this node — >1 only for fan-out. */
  calls: number;
}

export interface RunForecast {
  requirements?: number;
  pages?: number;
  entities?: number;
  workflows?: number;
  businessRules?: number;
  apis?: number;
  expectedTests?: number;
  [k: string]: number | undefined;
}

export interface RunUsage {
  nodes?: number;
  tokens?: number;
  cost_usd?: number;
  elapsed_s?: number;
  [k: string]: unknown;
}

/** One event as it arrived, so nothing the engine says is invisible. */
export interface RunEvent {
  seq: number;
  event: string;
  detail: string;
}

/**
 * One line of Smith working, as it worked.
 *
 * `reasoning` is the model thinking. `step` is deterministic work naming
 * itself — "Regenerating the frontend" — which is not something anybody
 * thought, and rendering the two alike would be a small lie told on every
 * turn. §111 wants build progress shown as observable status; `node` carries
 * the DAG key so a step can be labelled from the same table the stage list
 * uses.
 */
export interface RunThought {
  kind: "reasoning" | "step";
  text: string;
  node?: string;
}

/** Something Smith said, in the order it said it. */
export interface RunMessage {
  text: string;
  options?: string[];
  diffSummary?: string;
}

/**
 * Smith's post-build render review, live. The screenshots it took, the vision
 * critic's analysis, and which pages it is re-composing — the utility window
 * that comes up while Smith looks at what it built and narrates in chat.
 * `null` until a review starts; carries no history (it means something only
 * while it is happening), so it is never rebuilt from the run registry.
 */
export interface ReviewShot { route: string; image: string }
export interface ReviewFinding {
  route: string; kind: string; severity: string; note: string;
}
export interface ReviewState {
  phase: "start" | "shots" | "analysis" | "fixing" | "done";
  active: boolean;
  round: number;
  shots: ReviewShot[];
  findings: ReviewFinding[];
  fixing: string[];
  converged?: boolean;
  recomposed?: string[];
  remaining?: string[];
}

export interface BlueprintRun {
  /** Smith's own words — it decides what to do, and says so. */
  messages: RunMessage[];
  /**
   * How Smith got to what it said, while it is getting there.
   *
   * A turn that composes a screen runs for a minute behind a single
   * `message`, and until it lands the panel shows a spinner — a long turn and
   * a stuck one look exactly alike. These arrive as the model produces them.
   *
   * Cleared per run, not accumulated across the conversation: this is the
   * reasoning behind the turn in flight, and the transcript keeps only what
   * Smith actually said.
   */
  thoughts: RunThought[];
  /** Every event, in order. The engine's own account of the run. */
  events: RunEvent[];
  /** Ordered as the orchestrator planned them, not as they finish. */
  nodes: RunNode[];
  nodesDone: number;
  nodesTotal: number;
  callsDone: number;
  /** Nodes the orchestrator skipped because they were already complete (§72). */
  alreadyComplete: string[];
  awaitingApproval: boolean;
  /**
   * Pages the run declared and never composed — routes that will 404.
   *
   * Every node can complete and a page still have no layout: composition is
   * per-page, and a page that fails is one the run carries on without. The
   * outcome said "built" and the route was simply absent until somebody
   * opened it.
   */
  unbuilt: { page?: string; detail?: string }[];
  forecast: RunForecast | null;
  usage: RunUsage | null;
  status: "idle" | "running" | "complete" | "error";
  error: string | null;
  /** Smith's live render review, or null when none is happening. */
  review: ReviewState | null;
  /**
   * The stage name a REATTACHED run is on, when this client did not watch the
   * stream that produced it and so has no `nodes` to read a label from.
   */
  reattachedStage?: string | null;
  /** How long the reattached run has ACTUALLY been going, per the server. */
  reattachedElapsedMs?: number | null;
}

const EMPTY: BlueprintRun = {
  messages: [],
  thoughts: [],
  events: [],
  nodes: [],
  nodesDone: 0,
  nodesTotal: 0,
  callsDone: 0,
  alreadyComplete: [],
  awaitingApproval: false,
  unbuilt: [],
  forecast: null,
  usage: null,
  status: "idle",
  error: null,
  review: null,
};

export interface StartOptions {
  description: string;
  /** Earlier turns, oldest first — what Smith asked and what was answered. */
  history?: Array<{ role: "user" | "smith"; text: string }>;
  domain?: string;
  /** §14 — text of documents the user supplied rather than typed. */
  evidence?: string[];
  /** §25 — false stops after the definition and waits to be accepted. */
  approved?: boolean;
  defineOnly?: boolean;
  /** Start over rather than resuming an existing Blueprint. */
  fresh?: boolean;
}

export function useBlueprintRun(projectId: string | null) {
  const [run, setRun] = useState<BlueprintRun>(EMPTY);
  const abortRef = useRef<AbortController | null>(null);
  // True while this hook is driving its own stream. A reattached run must not
  // be overwritten by polling, and polling must stop the moment we start one.
  const ownStreamRef = useRef(false);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollCancelRef = useRef(false);

  // REATTACH BY POLLING. The run's progress arrives over SSE, but that stream
  // is not the only way it reaches the panel: a reload, an expired-then-restored
  // session, OR a stream that simply dropped mid-run (a proxy idle-timeout, a
  // sleep, a flaky network) all leave the DAG running server-side with nobody
  // listening. The registry keeps every node's state from the same events this
  // reducer folds, so polling `/run` rebuilds the true state and keeps it
  // current until the run is no longer active — this is what makes the status
  // reliable when the stream is not.
  const pollOnce = useCallback(async () => {
    if (!projectId || pollCancelRef.current || ownStreamRef.current) return;
    try {
      const snap = await api.get<{
        active?: boolean;
        phase?: string;
        stage?: string | null;
        nodesDone?: number;
        nodesTotal?: number;
        callsDone?: number;
        nodes?: { key: string; state: NodeState; subject?: string; calls?: number }[];
        elapsedMs?: number;
        awaitingApproval?: boolean;
        status?: string;
        error?: string | null;
      }>(`/api/projects/${projectId}/run`);
      if (pollCancelRef.current || ownStreamRef.current) return;

      if (snap.active) {
        setRun((prev) => ({
          ...prev,
          nodesDone: snap.nodesDone ?? 0,
          nodesTotal: snap.nodesTotal ?? 0,
          callsDone: snap.callsDone ?? prev.callsDone,
          nodes:
            Array.isArray(snap.nodes) && snap.nodes.length > 0
              ? snap.nodes.map((n) => ({
                  key: n.key,
                  state: n.state,
                  subject: n.subject,
                  calls: n.calls ?? 0,
                }))
              : prev.nodes,
          awaitingApproval: Boolean(snap.awaitingApproval),
          reattachedStage: snap.stage ?? null,
          reattachedElapsedMs: snap.elapsedMs ?? null,
          status: "running",
          // Polling took over — a stream that dropped is no longer an error.
          error: null,
        }));
        pollTimerRef.current = setTimeout(pollOnce, 4000);
      } else if (snap.status === "error") {
        setRun((prev) => ({ ...prev, status: "error", error: snap.error ?? null }));
      } else if (snap.status === "complete") {
        // Apply the FINAL node states the snapshot carries — every node done,
        // preview included. Flipping only `status` left the last active poll's
        // nodes frozen, and that poll caught the run on its last node
        // (`preview`) still running, so the panel stayed stuck at preview after
        // the run had actually ended.
        setRun((prev) =>
          prev.status === "running"
            ? {
                ...prev,
                nodes:
                  Array.isArray(snap.nodes) && snap.nodes.length > 0
                    ? snap.nodes.map((n) => ({
                        key: n.key,
                        state: n.state,
                        subject: n.subject,
                        calls: n.calls ?? 0,
                      }))
                    : prev.nodes,
                nodesDone: snap.nodesDone ?? prev.nodesDone,
                nodesTotal: snap.nodesTotal ?? prev.nodesTotal,
                callsDone: snap.callsDone ?? prev.callsDone,
                awaitingApproval: Boolean(snap.awaitingApproval),
                status: "complete",
                // The `review` events never reach a polling client (the run
                // registry does not carry them), so a review window caught
                // mid-phase would spin forever after the run ended. Settle it.
                review: finalizeReview(prev.review),
              }
            : prev,
        );
      }
    } catch {
      // A project with no run answers plainly; a transient failure is retried
      // rather than surfaced — the panel must not flicker to an error because
      // one poll missed.
      if (!pollCancelRef.current && !ownStreamRef.current) {
        pollTimerRef.current = setTimeout(pollOnce, 4000);
      }
    }
  }, [projectId]);

  // Hand control back to polling — the stream dropped or detached, but the run
  // is (or may be) still going. Clears any pending poll and starts a fresh one.
  const resumePolling = useCallback(() => {
    ownStreamRef.current = false;
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    void pollOnce();
  }, [pollOnce]);

  useEffect(() => {
    if (!projectId) return;
    pollCancelRef.current = false;
    void pollOnce();
    return () => {
      pollCancelRef.current = true;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, [projectId, pollOnce]);

  // CATCH UP WHEN THE TAB WAKES. `smith/chat` streams the build over one
  // connection; Chrome suspends a backgrounded/asleep tab's network I/O
  // (net::ERR_NETWORK_IO_SUSPENDED), dropping the stream — and a suspended tab
  // also throttles/pauses the 4s poll timer, so after a wake the run can sit
  // stale for seconds (or look stuck) before the poll catches it up. On the tab
  // becoming visible or the browser reporting `online`, poll once immediately.
  // Safe: `pollOnce` no-ops while a live stream is still owned (its own guard),
  // and only advances state once polling has taken over from a dropped stream.
  useEffect(() => {
    if (!projectId) return;
    const onWake = () => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      void pollOnce();
    };
    document.addEventListener("visibilitychange", onWake);
    window.addEventListener("online", onWake);
    return () => {
      document.removeEventListener("visibilitychange", onWake);
      window.removeEventListener("online", onWake);
    };
  }, [projectId, pollOnce]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    ownStreamRef.current = false;
  }, []);

  const start = useCallback(
    async (opts: StartOptions) => {
      if (!projectId) {
        setRun({ ...EMPTY, status: "error", error: "No project selected." });
        return;
      }
      stop();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      ownStreamRef.current = true;
      setRun({ ...EMPTY, status: "running" });

      const token =
        typeof window !== "undefined" ? localStorage.getItem("token") : null;
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      let res: Response;
      try {
        res = await fetch(
          // SMITH DECIDES, NOT THIS HOOK. The routing — first build, consult
          // the architect, does a verdict start the graph — used to live in
          // the panel, where a second client would have to reimplement it.
          // §6 puts it in Smith; this reads one stream and renders it.
          `${API_BASE}/api/projects/${projectId}/smith/chat`,
          {
            method: "POST",
            headers,
            credentials: "include",
            signal: ctrl.signal,
            body: JSON.stringify({
              message: opts.description,
              // §8 layer 1. Smith asks "is that right?" and the next request
              // used to arrive as the bare word "yes" — nothing for it to be
              // a yes to, so it asked what the message meant. The server
              // persists no turn, so the transcript this client is already
              // holding is the only place the exchange exists.
              history: opts.history ?? [],
              approved: opts.approved ?? false,
            }),
          },
        );
      } catch (e) {
        if (ctrl.signal.aborted) return;
        setRun((r) => ({ ...r, status: "error", error: String(e) }));
        return;
      }

      // A redirect is not a result. An expired session answers 307 to /login
      // and `fetch` follows it, so `res.ok` is true and the body is HTML —
      // which parses as zero events and looks exactly like a run that did
      // nothing. The same blindness cost a generated app its form submits.
      if (res.redirected || !res.ok || !res.body) {
        setRun((r) => ({
          ...r,
          status: "error",
          error: res.redirected
            ? `Not signed in — the request was redirected to ${res.url}.`
            : `The engine refused the run (HTTP ${res.status}).`,
        }));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";
      // A terminal `done` means the turn is genuinely over; anything else that
      // ends the stream is a drop, and the run may still be going.
      let gotTerminal = false;

      const apply = (event: string, data: Record<string, unknown>) => {
        if (event === "done" && data.status === "timeout") {
          // The turn was released because it ran long — but the DAG is STILL
          // running server-side. Do not mark it complete; hand back to polling,
          // which tracks it to the real end and updates the panel the whole way.
          gotTerminal = true;
          resumePolling();
          return;
        }
        if (event === "done") gotTerminal = true;
        setRun((prev) => reduce(prev, event, data));
      };

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (line.startsWith(":")) continue;
            if (line.startsWith("event:")) {
              currentEvent = line.slice(6).trim();
            } else if (line.startsWith("data:") && currentEvent) {
              try {
                apply(currentEvent, JSON.parse(line.slice(5).trim()));
              } catch {
                /* a partial frame — the next chunk completes it */
              }
              currentEvent = "";
            }
          }
        }
      } catch (e) {
        if (!ctrl.signal.aborted) {
          setRun((r) => ({ ...r, status: "error", error: String(e) }));
        }
        return;
      }

      // The stream ended without a terminal `done`: the connection dropped
      // mid-run (proxy idle-timeout, sleep, flaky network). The DAG is almost
      // certainly still running, so DO NOT call it an error and DO NOT leave the
      // panel frozen at the last event — hand back to polling, which reads the
      // registry and tracks the run to its real end. This is the fix for a
      // status that used to stop updating whenever the stream blinked.
      if (!gotTerminal) resumePolling();
    },
    [projectId, stop, resumePolling],
  );

  return { run, start, stop };
}

/** Close out a review left mid-phase. The render review streams its phases —
 *  shots, analysis, fixing, done — over the same connection as everything else;
 *  a long re-compose drops the stream, the panel falls back to polling the run
 *  registry (which carries node state but NOT `review` events), and the window
 *  never receives its terminal `review:done`, so it spins on "fixing… round 2"
 *  forever even though the turn ended. When the run itself completes, settle the
 *  window: stop the spinner, mark it done, keep it up only if it did work. */
export function finalizeReview(review: ReviewState | null): ReviewState | null {
  if (!review || review.phase === "done") return review;
  return { ...review, phase: "done", fixing: [], active: review.round > 0 };
}

/** One event → the next run state. Pure, so the reducer is testable alone. */
export function reduce(
  prev: BlueprintRun,
  event: string,
  data: Record<string, unknown>,
): BlueprintRun {
  // Recorded FIRST and unconditionally. A reducer that only keeps what it
  // understands makes an unrecognised event indistinguishable from one that
  // never arrived — and the engine is free to emit more than this file knows.
  prev = {
    ...prev,
    events: [
      ...prev.events,
      { seq: prev.events.length, event, detail: describe(event, data) },
    ],
  };

  switch (event) {
    case "started":
      return { ...prev, status: "running" };

    case "thought":
      // Smith's reasoning, as it arrives. Not folded into `messages`: it is
      // how the answer was reached, not part of the conversation, and the
      // server does not write it to the transcript either.
      if (!String(data.text ?? "").trim()) return prev;
      return {
        ...prev,
        thoughts: [...prev.thoughts, {
          kind: data.kind === "step" ? "step" : "reasoning",
          text: String(data.text),
          node: String(data.node ?? "") || undefined,
        }],
      };

    case "message":
      // What Smith is doing, in its words. `asked` turns arrive this way too,
      // carrying the options §16 wants offered instead of a guess.
      //
      // The thinking that led here has served its purpose — the answer is now
      // on screen and says it better. Clearing keeps the reasoning from one
      // turn out of the next.
      return {
        ...prev,
        thoughts: [],
        messages: [...prev.messages, {
          text: String(data.text ?? ""),
          options: (data.options as string[]) ?? undefined,
          diffSummary: (data.diffSummary as string) || undefined,
        }].filter((m) => m.text),
      };

    case "review": {
      // The live render review. Each phase folds into one running ReviewState
      // so the window is a single evolving view, not a stack of events.
      const phase = String(data.phase ?? "");
      const cur: ReviewState = prev.review ?? {
        phase: "start", active: true, round: 0,
        shots: [], findings: [], fixing: [],
      };
      if (phase === "start") {
        return { ...prev, review: {
          phase: "start", active: true, round: 0,
          shots: [], findings: [], fixing: [] } };
      }
      if (phase === "shots") {
        return { ...prev, review: {
          ...cur, phase: "shots", active: true, fixing: [],
          shots: (data.pages as ReviewShot[]) ?? [] } };
      }
      if (phase === "analysis") {
        return { ...prev, review: {
          ...cur, phase: "analysis", active: true,
          findings: (data.findings as ReviewFinding[]) ?? [] } };
      }
      if (phase === "fixing") {
        return { ...prev, review: {
          ...cur, phase: "fixing", active: true,
          round: cur.round + 1,
          fixing: (data.pages as string[]) ?? [] } };
      }
      if (phase === "done") {
        return { ...prev, review: {
          ...cur, phase: "done",
          // A review that found nothing, or could not run, closes itself; one
          // that did work stays up so the user can see what changed.
          active: !data.skipped && (cur.round > 0),
          fixing: [],
          converged: Boolean(data.converged),
          recomposed: (data.recomposed as string[]) ?? [],
          remaining: (data.remaining as string[]) ?? [] } };
      }
      return prev;
    }

    case "plan": {
      const keys = (data.nodes as string[]) ?? [];
      return {
        ...prev,
        nodes: keys.map((key) => ({ key, state: "waiting", calls: 0 })),
        nodesTotal: (data.total as number) ?? keys.length,
        alreadyComplete: (data.alreadyComplete as string[]) ?? [],
        awaitingApproval: Boolean(data.awaitingApproval),
      };
    }

    case "node:start":
      return {
        ...prev,
        nodes: prev.nodes.map((n) =>
          n.key === data.node ? { ...n, state: "running", subject: undefined } : n,
        ),
      };

    // ONE PAGE OF A FAN-OUT FINISHED; THE NODE HAS NOT. The stream reads the
    // run ledger, which says so in two different lines: a subject per page,
    // and one `node:done` when the node itself is complete. Ticking on the
    // first subject is what showed Page Design complete while fourteen more
    // pages were still composing.
    case "node:subject":
      return {
        ...prev,
        nodes: prev.nodes.map((n) =>
          n.key === data.node
            ? {
                ...n,
                state: "running",
                calls: n.calls + 1,
                subject:
                  data.index != null && data.total
                    ? `${data.index} of ${data.total}`
                    : (data.subject as string | undefined),
              }
            : n,
        ),
        nodesDone: (data.nodesDone as number) ?? prev.nodesDone,
        nodesTotal: (data.nodesTotal as number) ?? prev.nodesTotal,
        callsDone: (data.callsDone as number) ?? prev.callsDone,
      };

    case "node:done":
      return {
        ...prev,
        nodes: prev.nodes.map((n) =>
          n.key === data.node ? { ...n, state: "done", subject: undefined } : n,
        ),
        nodesDone: (data.nodesDone as number) ?? prev.nodesDone,
        nodesTotal: (data.nodesTotal as number) ?? prev.nodesTotal,
        callsDone: (data.callsDone as number) ?? prev.callsDone,
      };

    case "node:failed":
    case "node:blocked":
    case "node:skipped":
      return {
        ...prev,
        nodes: prev.nodes.map((n) =>
          n.key === data.node ? { ...n, state: "failed", subject: undefined } : n,
        ),
      };

    case "forecast":
      return { ...prev, forecast: data as RunForecast };

    case "usage":
      return { ...prev, usage: data as RunUsage };

    case "done": {
      const rep = (data.report ?? {}) as Record<string, unknown>;
      const awaiting = Boolean(data.awaitingApproval);
      return {
        ...prev,
        status: "complete",
        awaitingApproval: awaiting,
        unbuilt: (rep.unbuilt as BlueprintRun["unbuilt"]) ?? [],
        // A completed run (not a pause at the approval gate) has no node still
        // running. Mark any lingering one done so the panel never freezes on
        // the last node — `preview` — if its `node:done` was missed on a stream
        // that blinked just before the terminal event.
        nodes: awaiting
          ? prev.nodes
          : prev.nodes.map((n) =>
              n.state === "running" ? { ...n, state: "done", subject: undefined } : n,
            ),
        // The turn ended; a review still mid-phase never got its own terminal
        // event — settle it so its window stops spinning.
        review: awaiting ? prev.review : finalizeReview(prev.review),
      };
    }

    case "error":
      return {
        ...prev,
        status: "error",
        error: (data.message as string) ?? "The run failed.",
      };

    default:
      return prev;
  }
}


/** One line a person can read, per event. */
function describe(event: string, data: Record<string, unknown>): string {
  switch (event) {
    case "started":
      return "Run started";
    case "plan": {
      const n = (data.nodes as string[])?.length ?? 0;
      const skipped = (data.alreadyComplete as string[])?.length ?? 0;
      return `Planned ${n} stage${n === 1 ? "" : "s"}` +
        (skipped ? ` · ${skipped} already complete` : "");
    }
    case "node:start":
      return `${data.node}${data.subject ? ` · ${data.subject}` : ""} started`;
    case "node:done":
      return `${data.node}${data.subject ? ` · ${data.subject}` : ""} done` +
        ` (${data.nodesDone}/${data.nodesTotal})`;
    case "forecast":
      return "Forecast received";
    case "usage": {
      const cost = data.cost_usd as number | undefined;
      const secs = data.elapsed_s as number | undefined;
      return `Usage: ${cost !== undefined ? `$${cost.toFixed(2)}` : "?"}` +
        (secs !== undefined ? ` · ${Math.round(secs)}s` : "");
    }
    case "done": {
      const missed =
        ((data.report as { unbuilt?: unknown[] })?.unbuilt ?? []).length;
      if (data.awaitingApproval) return "Definition ready";
      return missed
        ? `Run complete · ${missed} page${missed === 1 ? "" : "s"} not built`
        : "Run complete";
    }
    case "error":
      return `Error: ${data.message ?? "unknown"}`;
    default:
      // An event this file does not model still gets a line.
      return `${event}: ${JSON.stringify(data).slice(0, 120)}`;
  }
}
