/**
 * Find problems: the logic behind the panel. No React, no network.
 *
 * Bombs are tricky tests an AI invents for an agent (a made-up id, a sneaky instruction, ...). Each is thrown at the
 * agent and ends up DEFUSED (it was handled), EXPLODED (it was not), UNSTABLE (handled sometimes, not others) or a
 * MISFIRE (it could not be run or judged). A failure can come with a proposed fix; applying one changes the drawing
 * only, never the running app.
 */
import type { AgentNodeSerialized } from "@/types/agent-builder";

export interface Bomb {
  key: string;
  title: string;
  icon: string;
  blurb: string;
}

export interface BlastTest {
  id: string;
  name: string;
  message: string;
  history?: Array<{ role: "user" | "assistant"; content: string }>;
  expect: Record<string, unknown>;
  /** One sentence a reviewer judges the reply by, when rules cannot say. */
  judge?: string;
  bomb?: string;
  /** What sort of everyday situation it is, when an AI wrote it as a normal test rather than an attack. */
  kind?: string;
}

/** A kind of test in plain words: "missing_detail" becomes "Missing detail". */
export function kindWords(kind?: string | null): string {
  const words = String(kind ?? "").replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "";
}

export type BlastStatus = "passed" | "failed" | "flaky" | "error";

export interface BlastResult {
  id: string;
  name: string;
  bomb?: string | null;
  message: string;
  status: BlastStatus;
  failures: string[];
  response: string;
  toolCalls: Array<{ name: string; input?: Record<string, unknown> }>;
  blocked?: boolean;
  runs?: number;
  passedRuns?: number;
  failedRuns?: number;
  error?: string;
  ms?: number | null;
  tokens?: number | null;
}

export interface BlastSummary {
  passed: number;
  failed: number;
  flaky: number;
  error: number;
  total: number;
}

export interface BlastFix {
  id: string;
  kind: "instruction_add" | "tool_description" | "ask_first" | "advice";
  title: string;
  why: string;
  fixesTests: string[];
  nodeId?: string;
  tool?: string;
  text?: string;
  before?: string;
  after?: string;
}

export interface BlastState {
  /** idle → inventing (the AI is writing the bombs) → running (they are being thrown) → fixing → done. */
  phase: "idle" | "inventing" | "running" | "fixing" | "done" | "error";
  total: number;
  repeats: number;
  results: Record<string, BlastResult>;
  /** Result ids in the order they finished. */
  order: string[];
  summary?: BlastSummary;
  error?: string;
}

export const emptyBlast = (): BlastState => ({ phase: "idle", total: 0, repeats: 1, results: {}, order: [] });

type Event = { type: string; [key: string]: any };

/** One event of the run stream into the state. `start` clears the results unless the run adds to them. */
export function reduceBlast(state: BlastState, e: Event, opts: { merge?: boolean } = {}): BlastState {
  switch (e.type) {
    case "start":
      return {
        ...state,
        phase: "running",
        total: e.total ?? 0,
        repeats: e.repeats ?? 1,
        error: undefined,
        summary: undefined,
        ...(opts.merge ? {} : { results: {}, order: [] }),
      };
    case "result": {
      const r = e.result as BlastResult;
      return { ...state, results: { ...state.results, [r.id]: r }, order: state.order.includes(r.id) ? state.order : [...state.order, r.id] };
    }
    case "done":
      return { ...state, phase: "done", summary: e.summary };
    case "error":
      return { ...state, phase: "error", error: String(e.message ?? "Something went wrong.") };
    default:
      return state;
  }
}

/** Totals over every result held, so a re-run of a few tests still counts the whole round. */
export function tally(results: Record<string, BlastResult>): BlastSummary {
  const all = Object.values(results);
  const n = (s: BlastStatus) => all.filter((r) => r.status === s).length;
  return { passed: n("passed"), failed: n("failed"), flaky: n("flaky"), error: n("error"), total: all.length };
}

export const isBad = (r: BlastResult) => r.status === "failed" || r.status === "flaky";

/** The word for how a bomb ended. */
export function verdict(status: BlastStatus): "Defused" | "Exploded" | "Unstable" | "Misfire" {
  return status === "passed" ? "Defused" : status === "failed" ? "Exploded" : status === "flaky" ? "Unstable" : "Misfire";
}

/** The round in a sentence: what went off, what was handled, and what could not be run. */
export function roundSummary(s: BlastSummary): string {
  if (s.total === 0) return "";
  const parts: string[] = [];
  if (s.failed) parts.push(`${s.failed} exploded`);
  if (s.flaky) parts.push(`${s.flaky} unstable`);
  parts.push(`${s.passed} defused`);
  if (s.error) parts.push(`${s.error} could not be run`);
  return parts.join(" · ");
}

/**
 * Roughly how many model calls a blast makes: the inventing; each run (the assistant's turns, about three with the
 * simulated lookups); a judging for about half; the fixes. Mirrors the platform.
 */
export function estimateCalls(tests: number, repeats: number, judged?: number): number {
  const j = judged ?? tests;
  const r = Math.max(1, repeats);
  return 1 + tests * r * 3 + Math.floor((j * r) / 2) + 1;
}

/** A proposed fix, applied to the drawing: the nodes as they would then be. Advice changes nothing. */
export function applyFix(nodes: AgentNodeSerialized[], fix: BlastFix): AgentNodeSerialized[] {
  if (!fix.nodeId) return nodes;
  return nodes.map((n) => {
    if (n.id !== fix.nodeId) return n;
    const config = { ...((n.data.config as Record<string, unknown>) ?? {}) };
    if (fix.kind === "instruction_add" && fix.text) {
      const current = String(config.prompt ?? "");
      // The prompt may have moved on since the fix was proposed: add the sentence to what is there now, once.
      if (!current.includes(fix.text)) config.prompt = `${current.replace(/\s+$/, "")}\n${fix.text}`.trim();
    } else if (fix.kind === "tool_description" && fix.text) {
      config.description = fix.text;
    } else if (fix.kind === "ask_first") {
      config.confirm = true;
    } else {
      return n;
    }
    return { ...n, data: { ...n.data, config } as AgentNodeSerialized["data"] };
  });
}

/** Whether applying a fix would change the drawing at all (it would not if the drawing already says it). */
export function changesDrawing(nodes: AgentNodeSerialized[], fix: BlastFix): boolean {
  return JSON.stringify(applyFix(nodes, fix)) !== JSON.stringify(nodes);
}

/**
 * A fix taken back out of the drawing: the reverse of `applyFix`. The sentence it added is removed, the old tool
 * description is put back, and "ask first" goes back to off (it only ever offers itself for a tool that was switched off).
 */
export function revertFix(nodes: AgentNodeSerialized[], fix: BlastFix): AgentNodeSerialized[] {
  if (!fix.nodeId) return nodes;
  return nodes.map((n) => {
    if (n.id !== fix.nodeId) return n;
    const config = { ...((n.data.config as Record<string, unknown>) ?? {}) };
    if (fix.kind === "instruction_add" && fix.text) {
      const current = String(config.prompt ?? "");
      const at = current.lastIndexOf(fix.text);
      if (at < 0) return n;
      config.prompt = `${current.slice(0, at)}${current.slice(at + fix.text.length)}`.replace(/\s+$/, "");
    } else if (fix.kind === "tool_description") {
      if (fix.before) config.description = fix.before;
      else delete config.description;
    } else if (fix.kind === "ask_first") {
      config.confirm = false;
    } else {
      return n;
    }
    return { ...n, data: { ...n.data, config } as AgentNodeSerialized["data"] };
  });
}

/** What a fix does, in a phrase. */
export function fixKindLabel(kind: BlastFix["kind"]): string {
  return { instruction_add: "Add to the instructions", tool_description: "Clearer tool description", ask_first: "Ask the person first", advice: "Worth a look" }[kind];
}

/** Said on every proposed fix: it is a guess until it has been tried. */
export const FIX_HINT = "An AI's guess: it may or may not work. “Apply and test” tries it on the tests that failed and tells you; you can undo it.";

/** Everything that did not pass, and so is worth running again: exploded, unstable, or could not be run. */
export const didNotPass = (r: BlastResult) => r.status !== "passed";

export interface FixOutcome {
  state: "worked" | "partly" | "no" | "unknown";
  /** How many of the re-tested tests now hold. */
  fixed: number;
  total: number;
}

/**
 * Did a fix work? Looks at the tests it was meant to help, after they were run again. A test that is only unstable still
 * counts as not fixed, and a test that could not be run says nothing either way.
 */
export function fixOutcome(testIds: string[], results: Record<string, BlastResult>): FixOutcome {
  const seen = testIds.map((id) => results[id]).filter(Boolean);
  const fixed = seen.filter((r) => r.status === "passed").length;
  if (seen.length === 0 || seen.every((r) => r.status === "error")) return { state: "unknown", fixed, total: seen.length };
  return { state: fixed === seen.length ? "worked" : fixed === 0 ? "no" : "partly", fixed, total: seen.length };
}

/** The outcome of a fix in a sentence. */
export function outcomeSentence(o: FixOutcome): string {
  const n = (k: number) => `${k} test${k === 1 ? "" : "s"}`;
  switch (o.state) {
    case "worked": return `It worked: ${o.total === 1 ? "the test it was for is" : `all ${n(o.total)} it was for are`} defused now.`;
    case "partly": return `Partly: ${o.fixed} of ${n(o.total)} defused now, the rest still go off.`;
    case "no": return `It did not help: ${o.total === 1 ? "the test still goes" : `all ${n(o.total)} still go`} off. Undo it, or try another fix.`;
    default: return "It could not be tested: the tests could not be run. Try again.";
  }
}
