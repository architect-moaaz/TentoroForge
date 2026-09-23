/**
 * The build as a game board: levels, the steps in play on each, and how
 * every subject of a fan-out is faring — derived from the run, never guessed.
 *
 * A list of stages ticking off says how far a build is and nothing about
 * what a build IS: several steps running side by side, a step that is really
 * twelve calls at once, a reviewer sending one of them back, a retry, a wait
 * on the API. This model is what the level map draws. Pure and cheap: it is
 * recomputed on every event.
 */
import type { BlueprintRun, RunMoment, RunNode } from "@/hooks/useBlueprintRun";

import { labelFor } from "./stages";

/** One subject's standing, as its cell is coloured. */
export type CellState = "pending" | "done" | "review" | "sent_back" | "retry" | "passed" | "noted" | "waiting";

export interface Cell { subject: string; state: CellState; note?: string }

export interface StepCard {
  key: string;
  label: string;
  state: RunNode["state"];
  /** Subjects seen so far, or the declared total when the node fans out. */
  cells: Cell[];
  total: number;
  done: number;
  repairs: number;
  retries: number;
  /** A fan-out step that finished with every subject passing first time. */
  cleanSweep: boolean;
}

export interface Level { index: number; steps: StepCard[]; state: "done" | "active" | "ahead" }

export interface Ticker { seq: number; tone: "pass" | "back" | "retry" | "wait" | "note"; text: string }

export interface Badge { id: string; label: string; detail: string }

export interface QuestModel {
  levels: Level[];
  current: number;                 // 1-based furthest level in play, 0 before the plan
  cleared: number;                 // levels every step of which is done
  stats: { calls: number; repairs: number; retries: number; inFlight: number; passRate: number | null };
  ticker: Ticker[];
  badges: Badge[];
  paused?: string;
}

const TICKER = 5;

function shortReason(reason?: string): string {
  const lines = (reason ?? "").split("\n").map((l) => l.trim()).filter((l) => l.startsWith("- ["));
  const first = (lines[0] ?? reason ?? "").replace(/^- \[[^\]]*\]\s*/, "").replace(/\s+/g, " ").trim();
  return first.length > 70 ? `${first.slice(0, 69)}…` : first;
}

export function questModel(run: BlueprintRun): QuestModel {
  const nodes = new Map(run.nodes.map((n) => [n.key, n]));
  const moments = run.moments ?? [];

  // Per node, per subject: the latest standing and how it got there.
  const cells = new Map<string, Map<string, Cell>>();
  const repairs = new Map<string, number>();
  const retries = new Map<string, number>();
  const firstTime = new Map<string, boolean>();          // node -> every subject passed untouched
  const ticker: Ticker[] = [];
  let calls = 0, passes = 0, verdicts = 0, paused: string | undefined;

  const cell = (node: string, subject: string): Cell => {
    const m = cells.get(node) ?? new Map<string, Cell>();
    cells.set(node, m);
    const c = m.get(subject) ?? { subject, state: "pending" };
    m.set(subject, c);
    return c;
  };
  const name = (m: RunMoment) => (m.subject ? `${labelFor(m.node)} · ${m.subject}` : labelFor(m.node));

  moments.forEach((m, seq) => {
    switch (m.kind) {
      case "subject": {
        calls += 1;
        const c = cell(m.node, m.subject);
        if (c.state === "pending" || c.state === "retry" || c.state === "waiting") c.state = m.ok ? "done" : "retry";
        break;
      }
      case "verdict": {
        verdicts += 1;
        const c = cell(m.node, m.subject);
        if (m.ok) {
          passes += 1;
          c.state = "passed";
          if (!firstTime.has(m.node)) firstTime.set(m.node, true);
          ticker.push({ seq, tone: "pass", text: `${name(m)} passed review` });
        } else {
          c.state = "review";
          c.note = `${m.findings ?? 0} finding${m.findings === 1 ? "" : "s"}`;
          firstTime.set(m.node, false);
        }
        break;
      }
      case "repair": {
        repairs.set(m.node, (repairs.get(m.node) ?? 0) + 1);
        const c = cell(m.node, m.subject);
        c.state = "sent_back";
        c.note = shortReason(m.reason);
        ticker.push({ seq, tone: "back", text: `${name(m)} sent back: ${shortReason(m.reason)}` });
        break;
      }
      case "unrepaired": {
        const c = cell(m.node, m.subject);
        c.state = "noted";
        c.note = shortReason(m.reason);
        ticker.push({ seq, tone: "note", text: `${name(m)}: noted for later` });
        break;
      }
      case "retry": {
        retries.set(m.node, (retries.get(m.node) ?? 0) + 1);
        firstTime.set(m.node, false);
        const c = cell(m.node, m.subject);
        c.state = "retry";
        c.note = shortReason(m.reason);
        ticker.push({ seq, tone: "retry", text: `${name(m)} asked again (${m.attempt}/${m.of})` });
        break;
      }
      case "stalled": {
        const c = cell(m.node, m.subject);
        c.state = "waiting";
        ticker.push({ seq, tone: "wait", text: `${name(m)} waiting for the API` });
        break;
      }
      case "paused":
        paused = m.reason;
        ticker.push({ seq, tone: "wait", text: `Paused: ${shortReason(m.reason)}` });
        break;
    }
  });

  const card = (key: string): StepCard => {
    const node = nodes.get(key) ?? { key, state: "waiting" as const, calls: 0 };
    const seen = [...(cells.get(key)?.values() ?? [])];
    const declared = /^(\d+) of (\d+)$/.exec(node.subject ?? "");
    const total = declared ? Number(declared[2]) : Math.max(seen.length, node.state === "done" ? 1 : 0);
    const done = seen.filter((c) => c.state !== "pending" && c.state !== "retry" && c.state !== "waiting").length;
    const padded = [...seen, ...Array.from({ length: Math.max(0, total - seen.length) },
                                          (_, i) => ({ subject: `#${seen.length + i + 1}`, state: "pending" as CellState }))];
    return {
      key, label: labelFor(key), state: node.state, cells: padded, total, done,
      repairs: repairs.get(key) ?? 0, retries: retries.get(key) ?? 0,
      cleanSweep: node.state === "done" && total > 1 && firstTime.get(key) === true
        && !(repairs.get(key) ?? 0) && !(retries.get(key) ?? 0),
    };
  };

  const planned = run.levels?.length ? run.levels : run.nodes.map((n) => [n.key]);
  const levels: Level[] = planned.map((keys, i) => {
    const steps = keys.map(card);
    const state: Level["state"] = steps.every((s) => s.state === "done" || s.state === "failed") ? "done"
      : steps.some((s) => s.state === "running") ? "active"
      : steps.some((s) => s.state === "done") ? "active" : "ahead";
    return { index: i + 1, steps, state };
  });
  // THE FURTHEST LEVEL IN PLAY. The scheduler starts a step the moment its
  // own inputs are ready, so several levels are open at once; "Level 1 of
  // 13" while level 5 is running read as stuck. The header names how far
  // the build has reached and how many levels are cleared.
  const active = levels.filter((l) => l.state === "active").map((l) => l.index);
  const current = active.length ? Math.max(...active)
    : (levels.length && levels.every((l) => l.state === "done") ? levels.length : 0);
  const cleared = levels.filter((l) => l.state === "done").length;

  const badges: Badge[] = [];
  for (const l of levels) for (const s of l.steps) {
    if (s.cleanSweep) badges.push({ id: `clean:${s.key}`, label: "Clean sweep", detail: `${s.label}: ${s.total} passed first time` });
  }
  const comebacks = [...cells.entries()].flatMap(([node, m]) => [...m.values()].filter((c) => c.state === "passed")
    .filter((c) => moments.some((x) => x.kind === "repair" && x.node === node && x.subject === c.subject))
    .map((c) => ({ node, c })));
  if (comebacks.length) badges.push({ id: "comeback", label: "Comeback", detail: `${comebacks.length} sent back and then passed` });
  const inFlight = run.nodes.filter((n) => n.state === "running").length;

  return {
    levels, current, cleared,
    stats: { calls: Math.max(calls, run.callsDone), repairs: [...repairs.values()].reduce((a, b) => a + b, 0),
             retries: [...retries.values()].reduce((a, b) => a + b, 0), inFlight,
             passRate: verdicts ? passes / verdicts : null },
    ticker: ticker.slice(-TICKER).reverse(),
    badges, paused,
  };
}
