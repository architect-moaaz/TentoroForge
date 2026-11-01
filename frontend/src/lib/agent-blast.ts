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
  /** The one tool a tool test is about, how the simulated app behaves for it, and the secret planted in its records. */
  tool?: string;
  sim?: string;
  canary?: string;
}

/** One thing a tool was asked for during a test: what, whether the app held it, and what came back. */
export interface BlastToolCall {
  name: string;
  input?: Record<string, unknown>;
  held?: boolean;
  kind?: "lookup" | "change" | "handoff";
  /** What the assistant was handed back (the start of it). */
  output?: string;
}

/** What an AI worked out about the one tool it was asked to examine. */
export interface ToolStudy {
  tool: string;
  whatItDoes: string;
  needs: string[];
  risks: string[];
}

/** One way a tool is examined ("Bad input", "Secrets and privacy"...). */
export interface ToolAngle {
  key: string;
  title: string;
}

/** The names the platform gives the tools drawn on a canvas: what the AI is told, and what a test is about. */
export function toolNames(graph: { nodes?: unknown }): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const n of (Array.isArray(graph.nodes) ? graph.nodes : []) as Array<{ data?: { nodeType?: string; label?: string; config?: Record<string, unknown> } }>) {
    if (n?.data?.nodeType !== "tool") continue;
    const raw = String(n.data.config?.tool_name || n.data.label || "").trim();
    const base = raw.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60);
    if (!base) continue;
    let name = base;
    for (let i = 2; seen.has(name); i++) name = `${base}_${i}`;
    seen.add(name);
    out.push(name);
  }
  return out;
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
  toolCalls: BlastToolCall[];
  blocked?: boolean;
  /** For a tool test: what sort of test, which tool, and how the simulated app behaved. */
  kind?: string;
  tool?: string;
  sim?: string;
  /** What the app's own guardrails did during the test (a field hidden, a credential removed, a reply stopped). */
  notes?: string[];
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
  kind: "instruction_add" | "tool_description" | "ask_first" | "response_filter" | "advice";
  title: string;
  why: string;
  fixesTests: string[];
  nodeId?: string;
  tool?: string;
  text?: string;
  before?: string;
  after?: string;
  /** For "response_filter": the fields the tool will hand the assistant, and the ones it handed over before. */
  keys?: string[];
  beforeKeys?: string[];
}

export interface BlastState {
  /** idle → inventing (the AI is writing the bombs) → running (they are being thrown) → fixing → done. */
  phase: "idle" | "inventing" | "running" | "fixing" | "done" | "error";
  total: number;
  repeats: number;
  results: Record<string, BlastResult>;
  /** Result ids in the order they finished. */
  order: string[];
  /** How many tests have finished in THIS run (a re-run adds to the results above, so they cannot say). */
  ran: number;
  summary?: BlastSummary;
  error?: string;
}

export const emptyBlast = (): BlastState => ({ phase: "idle", total: 0, repeats: 1, results: {}, order: [], ran: 0 });

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
        ran: 0,
        ...(opts.merge ? {} : { results: {}, order: [] }),
      };
    case "result": {
      const r = e.result as BlastResult;
      return { ...state, ran: (state.ran ?? 0) + 1, results: { ...state.results, [r.id]: r }, order: state.order.includes(r.id) ? state.order : [...state.order, r.id] };
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
    } else if (fix.kind === "response_filter" && fix.keys?.length && n.data.nodeType === "tool") {
      config.response_filter = [...fix.keys];
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
    } else if (fix.kind === "response_filter" && n.data.nodeType === "tool") {
      if (fix.beforeKeys?.length) config.response_filter = [...fix.beforeKeys];
      else delete config.response_filter;
    } else {
      return n;
    }
    return { ...n, data: { ...n.data, config } as AgentNodeSerialized["data"] };
  });
}

/** What a fix does, in a phrase. */
export function fixKindLabel(kind: BlastFix["kind"]): string {
  return {
    instruction_add: "Add to the instructions", tool_description: "Clearer tool description", ask_first: "Ask the person first",
    response_filter: "Show fewer fields", advice: "Worth a look",
  }[kind];
}

/** Said on every proposed fix: it is a guess until it has been tried. */
export const FIX_HINT = "An AI's guess: it may or may not work. “Apply and test” tries it on the tests that failed and tells you; you can undo it.";

/** Everything that did not pass, and so is worth running again: exploded, unstable, or could not be run. */
export const didNotPass = (r: BlastResult) => r.status !== "passed";

/** A test, by id and name, as the sentences about a fix mention it. */
export interface Named {
  id: string;
  name: string;
}

/** What a fix did to the tests that were NOT about it: the ones that held before and now go off, or only sometimes hold. */
export interface Regression {
  broke: Named[];
  shaky: Named[];
  /** How many other tests that held before were run again (a test that was already failing cannot have been broken). */
  checked: number;
}

export interface FixOutcome {
  /** "broke": it may have fixed its own tests, but tests that held before now go off. */
  state: "worked" | "partly" | "no" | "broke" | "unknown";
  /** How many of the re-tested tests now hold. */
  fixed: number;
  total: number;
  /** Present when everything else was checked again too. */
  broke?: Named[];
  shaky?: Named[];
  checked?: number;
}

/** Tests that held before and do not hold now: worth running once more before saying they broke (one run can be bad luck). */
export function suspects(before: Record<string, BlastResult>, after: Record<string, BlastResult>, ids: string[]): string[] {
  return ids.filter((id) => before[id]?.status === "passed" && (after[id]?.status === "failed" || after[id]?.status === "flaky"));
}

/** What a change did to the other tests: broke = held before and goes off every time now; shaky = held before and only sometimes now. */
export function regression(before: Record<string, BlastResult>, after: Record<string, BlastResult>, ids: string[]): Regression {
  // only a test that held before and has been run again can have been broken: those are the ones "checked"
  const held = ids.filter((id) => before[id]?.status === "passed" && after[id]);
  const named = (id: string): Named => ({ id, name: after[id]?.name ?? before[id]?.name ?? id });
  return {
    broke: held.filter((id) => after[id]?.status === "failed").map(named),
    shaky: held.filter((id) => after[id]?.status === "flaky").map(named),
    checked: held.length,
  };
}

/**
 * Did a fix work? Looks at the tests it was meant to help, after they were run again. A test that is only unstable still
 * counts as not fixed, and a test that could not be run says nothing either way.
 */
export function fixOutcome(testIds: string[], results: Record<string, BlastResult>, others?: Regression): FixOutcome {
  const seen = testIds.map((id) => results[id]).filter(Boolean);
  const fixed = seen.filter((r) => r.status === "passed").length;
  const extra = others ? { broke: others.broke, shaky: others.shaky, checked: others.checked } : {};
  // a fix that broke something that held is not a success whatever else it did
  if (others && others.broke.length > 0) return { state: "broke", fixed, total: seen.length, ...extra };
  if (seen.length === 0 || seen.every((r) => r.status === "error")) return { state: "unknown", fixed, total: seen.length, ...extra };
  return { state: fixed === seen.length ? "worked" : fixed === 0 ? "no" : "partly", fixed, total: seen.length, ...extra };
}

/** The outcome of a fix in a sentence. */
export function outcomeSentence(o: FixOutcome): string {
  const n = (k: number) => `${k} test${k === 1 ? "" : "s"}`;
  const names = (list: Named[]) => `${list.slice(0, 3).map((x) => `“${x.name}”`).join(", ")}${list.length > 3 ? ` and ${list.length - 3} more` : ""}`;
  // the rest of the tests were run again too: say so when they held, and say which ones when they did not
  const shaky = o.shaky?.length ? ` ${n(o.shaky.length)} that held before now hold only some of the time: ${names(o.shaky)}.` : "";
  const checked = o.checked && !o.broke?.length ? ` Nothing else broke: ${o.checked === 1 ? "the one other test" : `the ${o.checked} other tests`} still hold${o.checked === 1 ? "s" : ""}.` : "";
  switch (o.state) {
    case "worked": return `It worked: ${o.total === 1 ? "the test it was for is" : `all ${n(o.total)} it was for are`} defused now.${checked}${shaky}`;
    case "partly": return `Partly: ${o.fixed} of ${n(o.total)} defused now, the rest still go off.${checked}${shaky}`;
    case "no": return `It did not help: ${o.total === 1 ? "the test still goes" : `all ${n(o.total)} still go`} off. Undo it, or try another fix.${checked}${shaky}`;
    case "broke":
      return `${o.fixed > 0 ? `It fixed ${o.fixed} of ${n(o.total)}, but` : "It did not fix what it was for, and"} it made ${n(o.broke?.length ?? 0)} that held before go off: ${names(o.broke ?? [])}. Undo it, or try another fix.${shaky}`;
    default: return "It could not be tested: the tests could not be run. Try again.";
  }
}
