/**
 * Watching the app's real chats live: the logic behind the animated flowchart. No React, no network.
 *
 * The app streams every chat as it happens (see backend/templates/runtime/agents/watch.ts); the platform adds a
 * first event, `platform_map`, saying which box on the canvas each tool and step belongs to. This turns that stream
 * into: one tracked run per chat, which boxes are lighting up right now, and a checklist of the tools the AI chose.
 *
 * The runtime works in a fixed order (check the message, load memory, ask the AI, run tools one by one, ask again,
 * check the answer, reply) and does not walk the arrows the builder drew. What is lit is what really happens, put on
 * the box that stands for it.
 */
import { applyEvent, emptyRun, type LiveEvent, type LiveRun, type ModelStep, type ToolInfo, type ToolStep } from "./agent-live";

export interface FlowMap {
  /** A tool's compiled name -> its box. */
  tools: Record<string, string>;
  /** The boxes of every other kind: system_prompt, guardrail, memory, human_handoff, router. */
  kinds: Record<string, string[]>;
  /** What each tool accepts, as drawn, so a tool call's input can be checked. */
  toolInfo?: Record<string, Omit<ToolInfo, "name">>;
}

export interface WatchRun {
  id: string;
  agentId?: string;
  agentName?: string;
  /** Who and what, from the moment the chat began. */
  live: LiveRun;
  finished: boolean;
  /** When it began, as the watcher first heard of it. */
  seenAt: number;
}

/** Whose chats are being watched, as the app itself confirmed: everyone's (empty), a role's, or one person's. */
export interface WatchWho {
  role?: string;
  userId?: string;
}

export interface WatchState {
  /** The app said hello: the connection is verified and open. */
  ready: boolean;
  agents: Array<{ id: string; name: string }>;
  /** Whose chats the app says it is sending. */
  who: WatchWho;
  map?: FlowMap;
  runs: Record<string, WatchRun>;
  /** Newest first. */
  order: string[];
  /** The chat shown. */
  selected: string | null;
  /** A new chat takes over the view, unless the builder picked an older one. */
  follow: boolean;
  /** Why it could not connect or broke. */
  error?: string;
}

export const initialWatch = (): WatchState => ({ ready: false, agents: [], who: {}, runs: {}, order: [], selected: null, follow: true });

const MAX_RUNS = 30;

export function applyWatch(state: WatchState, e: LiveEvent, now: number = Date.now()): WatchState {
  switch (e.type) {
    case "platform_map":
      return { ...state, map: { tools: e.tools ?? {}, kinds: e.kinds ?? {}, toolInfo: e.toolInfo ?? {} } };
    case "watch_ready":
      return { ...state, ready: true, agents: e.agents ?? [], who: { ...(e.filter?.role ? { role: e.filter.role } : {}), ...(e.filter?.userId ? { userId: e.filter.userId } : {}) }, error: undefined };
    case "error":
      if (!e.runId) return { ...state, ready: false, error: String(e.message ?? "The connection failed.") };
      break;
    default:
      break;
  }
  const id = typeof e.runId === "string" ? e.runId : null;
  if (!id) return state;

  const existing = state.runs[id];
  let order = state.order;
  let selected = state.selected;
  let run: WatchRun;
  if (!existing) {
    const tools = state.map?.toolInfo ? Object.entries(state.map.toolInfo).map(([name, info]) => ({ name, ...info })) : undefined;
    run = { id, live: { ...emptyRun(), status: "running", ...(tools ? { tools } : {}) }, finished: false, seenAt: now };
    order = [id, ...order].slice(0, MAX_RUNS);
    if (state.follow || !selected) selected = id;
  } else {
    run = existing;
  }
  if (e.type === "run_start") run = { ...run, agentId: e.agentId, agentName: e.agentName };

  const live = applyEvent(run.live, e);
  run = { ...run, live, finished: live.status !== "running" && live.status !== "idle" };

  const runs = { ...state.runs, [id]: run };
  for (const gone of Object.keys(runs)) if (!order.includes(gone)) delete runs[gone];
  return { ...state, runs, order, selected };
}

/** The builder picked a chat: stop following new ones, unless they picked the newest. */
export function selectRun(state: WatchState, id: string): WatchState {
  return { ...state, selected: id, follow: id === state.order[0] };
}

export function followLatest(state: WatchState): WatchState {
  return { ...state, selected: state.order[0] ?? null, follow: true };
}

// ── which boxes are lit ───────────────────────────────────────────────────

export type NodeState = "active" | "done" | "failed" | "held";

const HANDOFF_TOOL = "request_human";

/**
 * The state of each box for one chat: lit while its step is happening, green once done, red if it failed, amber if
 * a change is waiting for a yes or the chat is with a person. A box the chat has not reached has no entry.
 */
export function nodeStates(run: WatchRun, map?: FlowMap): Record<string, NodeState> {
  const out: Record<string, NodeState> = {};
  if (!map) return out;
  const live = run.live;
  const set = (ids: string[] | undefined, state: NodeState) => ids?.forEach((id) => (out[id] = state));
  const running = live.status === "running";

  // checking the message and the answer: the guardrail boxes
  const guards = map.kinds.guardrail;
  const input = live.phases.find((p) => p.phase === "input_check");
  const output = live.phases.find((p) => p.phase === "output_check");
  if (input) set(guards, input.ok === false ? "failed" : "done");
  if (output) set(guards, output.ok === false ? "failed" : "done");

  // memory
  if (live.phases.some((p) => p.phase === "memory")) set(map.kinds.memory, "done");

  // the AI
  const models = live.steps.filter((s): s is ModelStep => s.kind === "model");
  if (models.length) {
    const last = models[models.length - 1];
    set(map.kinds.system_prompt, last.failed ? "failed" : last.running ? "active" : "done");
  }

  // the tools, one by one: a later call of the same tool replaces an earlier one
  for (const s of live.steps) {
    if (s.kind !== "tool") continue;
    const id = s.tool === HANDOFF_TOOL ? map.kinds.human_handoff?.[0] : map.tools[s.tool];
    if (!id) continue;
    out[id] = s.status === "running" ? "active" : s.status === "failed" ? "failed" : s.status === "held" ? "held" : "done";
  }

  // a chat that is with a person
  if (live.phases.some((p) => p.phase === "with_person")) set(map.kinds.human_handoff, "held");

  // a run that broke: whatever was still lit has failed
  if (live.status === "error") for (const k of Object.keys(out)) if (out[k] === "active") out[k] = "failed";
  // a run that is over has nothing lit
  if (!running) for (const k of Object.keys(out)) if (out[k] === "active") out[k] = "done";
  return out;
}

/** Classes for a box: the canvas draws these as a ring, pulsing while it works. */
export function nodeRing(state: NodeState | undefined): string | undefined {
  switch (state) {
    case "active":
      return "[&>div]:!ring-4 [&>div]:!ring-sky-500 [&>div]:!ring-offset-2 [&>div]:animate-pulse";
    case "done":
      return "[&>div]:!ring-2 [&>div]:!ring-green-500 [&>div]:!ring-offset-1";
    case "failed":
      return "[&>div]:!ring-4 [&>div]:!ring-red-500 [&>div]:!ring-offset-2";
    case "held":
      return "[&>div]:!ring-4 [&>div]:!ring-amber-400 [&>div]:!ring-offset-2";
    default:
      return undefined;
  }
}

/** How an arrow looks: moving while either end is working, green once the chat has passed along it, as drawn otherwise. */
export function edgeLook(source: NodeState | undefined, target: NodeState | undefined): { animated: boolean; stroke?: string; width?: number } {
  if (source === "active" || target === "active") return { animated: true, stroke: "#0ea5e9", width: 3 };
  if (source && target) return { animated: false, stroke: source === "failed" || target === "failed" ? "#ef4444" : "#22c55e", width: 2 };
  return { animated: false };
}

// ── the checklist ─────────────────────────────────────────────────────────

export type CheckStatus = "waiting" | "running" | "ok" | "failed" | "held";

export interface CheckItem {
  tool: string;
  status: CheckStatus;
  /** Milliseconds it took, once it has finished. */
  ms?: number;
}

export interface CheckGroup {
  /** Which call of the AI chose these. */
  step: number;
  items: CheckItem[];
}

/**
 * What the AI chose to use, as a list that ticks off as each tool finishes. Each call of the AI that asks for tools
 * makes one group; its tools are matched, in order, to the tool calls that follow it.
 */
export function checklist(live: LiveRun): CheckGroup[] {
  const groups: CheckGroup[] = [];
  const steps = live.steps;
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    if (s.kind !== "model" || s.running || s.toolsRequested.length === 0) continue;
    const following: ToolStep[] = [];
    for (let j = i + 1; j < steps.length && steps[j].kind !== "model"; j++) {
      const t = steps[j];
      if (t.kind === "tool") following.push(t);
    }
    const used = new Set<ToolStep>();
    const items: CheckItem[] = s.toolsRequested.map((name) => {
      const hit = following.find((t) => t.tool === name && !used.has(t));
      if (!hit) return { tool: name, status: "waiting" };
      used.add(hit);
      return { tool: name, status: hit.status, ...(hit.ms !== undefined ? { ms: hit.ms } : {}) };
    });
    groups.push({ step: s.n, items });
  }
  return groups;
}

/** Where the chat has got to, in a few words the panel can show. */
export function stageOf(run: WatchRun): string {
  const live = run.live;
  if (live.status === "blocked") return `Refused: ${live.blocked ?? "blocked"}`;
  if (live.status === "error") return `Failed: ${live.error ?? "something went wrong"}`;
  if (live.phases.some((p) => p.phase === "with_person")) return "With a person on the team: the assistant stays quiet";
  if (live.status === "done") return "Answer sent";
  const lastStep = live.steps[live.steps.length - 1];
  if (!live.phases.length && !lastStep) return "Message received";
  if (lastStep?.kind === "model" && lastStep.running) return `Calling the AI (call ${lastStep.n})`;
  if (lastStep?.kind === "tool" && lastStep.status === "running") return `Running ${lastStep.tool}`;
  if (lastStep?.kind === "model") return lastStep.toolsRequested.length ? `The AI chose: ${lastStep.toolsRequested.join(", ")}` : "Answer ready: checking it";
  if (lastStep?.kind === "tool") return "Reading the result";
  if (live.phases.some((p) => p.phase === "output_check")) return "Answer checked";
  if (live.phases.some((p) => p.phase === "memory")) return "Memory loaded";
  return "Checking the message";
}
