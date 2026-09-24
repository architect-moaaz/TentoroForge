/**
 * The build as a game board: levels, the steps in play on each, how every
 * subject of a fan-out is faring, what each one IS now that it landed, what
 * the reviewer saw of each page — and a score, a streak and badges earned
 * from it. Derived from the run, never guessed. Pure and cheap: it is
 * recomputed on every event.
 *
 * A list of stages ticking off says how far a build is and nothing about
 * what a build IS: several steps running side by side, a step that is really
 * twelve calls at once, a reviewer sending one of them back, a page
 * screenshotted and scored, a retry, a wait on the API.
 */
import type { BlueprintRun, RunLook, RunMoment, RunNode } from "@/hooks/useBlueprintRun";

import { labelFor } from "./stages";

/** One subject's standing, as its cell is coloured. */
export type CellState = "pending" | "done" | "review" | "sent_back" | "retry" | "passed" | "noted" | "waiting";

export interface Cell {
  subject: string;
  state: CellState;
  note?: string;
  /** What it is, now that it landed ("Doctor — 9 fields: name, …"). */
  summary?: string;
  /** The latest look at it, when it is a page that was looked at. */
  look?: RunLook;
}

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
  /** Points this step earned so far. */
  xp: number;
}

export interface Level { index: number; steps: StepCard[]; state: "done" | "active" | "ahead" }

export interface Ticker { seq: number; tone: "pass" | "back" | "retry" | "wait" | "note" | "look"; text: string }

/** Something taking shape: a subject that landed, with what it is. */
export interface Landed { seq: number; node: string; subject: string; label: string; summary: string }

export interface Badge { id: string; label: string; detail: string }

export interface Rank { name: string; at: number; next: number | null }

/** What the bets a watcher placed resolve against — null until the run ends. */
export interface Outcomes {
  /** Every page passed the reviewer's FIRST look. */
  allFirstLook: boolean | null;
  /** The fan-out step sent back (by the observer or the reviewer) or retried the most. */
  mostSentBack: string | null;
}

export interface QuestModel {
  levels: Level[];
  current: number;                 // 1-based furthest level in play, 0 before the plan
  cleared: number;                 // levels every step of which is done
  stats: {
    calls: number; repairs: number; retries: number; inFlight: number; passRate: number | null;
    xp: number; streak: number; bestStreak: number;
    looks: { passed: number; total: number };
  };
  rank: Rank;
  ticker: Ticker[];
  landed: Landed[];
  /** The latest look at each page, in the order the pages were first seen. */
  looks: RunLook[];
  badges: Badge[];
  outcomes: Outcomes;
  paused?: string;
}

const TICKER = 5;
const LANDED = 6;

/** Points. Landing is worth something; passing first time is worth more;
 *  coming back from a send-back is worth the most — the loop working. */
export const XP = {
  landed: 10, passFirst: 15, passAfterRepair: 20, lookPassFirst: 20, lookPassAfter: 10, levelCleared: 25,
} as const;

export const RANKS: { name: string; at: number }[] = [
  { name: "Apprentice", at: 0 }, { name: "Builder", at: 200 }, { name: "Architect", at: 600 },
  { name: "Master builder", at: 1200 }, { name: "Legend", at: 2400 },
];

export function rankFor(xp: number): Rank {
  let i = 0;
  while (i + 1 < RANKS.length && xp >= RANKS[i + 1].at) i++;
  return { name: RANKS[i].name, at: RANKS[i].at, next: RANKS[i + 1]?.at ?? null };
}

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
  const sentBack = new Map<string, number>();            // node -> observer + reviewer send-backs + retries
  const firstTime = new Map<string, boolean>();          // node -> every subject passed untouched
  const touched = new Set<string>();                     // "node/subject" sent back or retried
  const xpByNode = new Map<string, number>();
  const ticker: Ticker[] = [];
  const landed: Landed[] = [];
  const looksByPage = new Map<string, RunLook>();
  let calls = 0, passes = 0, verdicts = 0, paused: string | undefined;
  let streak = 0, bestStreak = 0, looksPassed = 0, looksTotal = 0;
  let firstLookFailed = false;

  const cell = (node: string, subject: string): Cell => {
    const m = cells.get(node) ?? new Map<string, Cell>();
    cells.set(node, m);
    const c = m.get(subject) ?? { subject, state: "pending" };
    m.set(subject, c);
    return c;
  };
  const name = (m: RunMoment) => (m.subject ? `${labelFor(m.node)} · ${m.subject}` : labelFor(m.node));
  const earn = (node: string, points: number) => xpByNode.set(node, (xpByNode.get(node) ?? 0) + points);
  const good = () => { streak += 1; bestStreak = Math.max(bestStreak, streak); };
  const bad = (node: string) => { streak = 0; sentBack.set(node, (sentBack.get(node) ?? 0) + 1); };

  moments.forEach((m, seq) => {
    const key = `${m.node}/${m.subject}`;
    switch (m.kind) {
      case "subject": {
        calls += 1;
        const c = cell(m.node, m.subject);
        if (c.state === "pending" || c.state === "retry" || c.state === "waiting") c.state = m.ok ? "done" : "retry";
        if (m.summary) c.summary = m.summary;
        if (m.ok) {
          earn(m.node, XP.landed);
          good();
          if (m.summary) landed.push({ seq, node: m.node, subject: m.subject, label: labelFor(m.node), summary: m.summary });
        }
        break;
      }
      case "verdict": {
        verdicts += 1;
        const c = cell(m.node, m.subject);
        if (m.ok) {
          passes += 1;
          c.state = "passed";
          if (!firstTime.has(m.node)) firstTime.set(m.node, true);
          earn(m.node, touched.has(key) ? XP.passAfterRepair : XP.passFirst);
          good();
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
        touched.add(key);
        bad(m.node);
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
        touched.add(key);
        bad(m.node);
        const c = cell(m.node, m.subject);
        c.state = "retry";
        c.note = shortReason(m.reason);
        ticker.push({ seq, tone: "retry", text: `${name(m)} asked again (${m.attempt}/${m.of})` });
        break;
      }
      case "look": {
        if (!m.look) break;
        const c = cell(m.node, m.subject);
        c.look = m.look;
        looksByPage.set(m.subject, m.look);
        looksTotal += 1;
        const route = m.look.route || m.subject;
        if (m.look.verdict === "pass") {
          looksPassed += 1;
          c.state = "passed";
          earn(m.node, m.look.attempt <= 1 ? XP.lookPassFirst : XP.lookPassAfter);
          good();
          ticker.push({ seq, tone: "look", text: `${route} looked at: ${m.look.score}/10 — passed` });
        } else {
          if (m.look.attempt <= 1) firstLookFailed = true;
          touched.add(key);
          bad(m.node);
          c.state = "sent_back";
          c.note = m.look.issues[0] ?? `${m.look.score}/10`;
          ticker.push({ seq, tone: "look", text: `${route} looked at: ${m.look.score}/10 — ${m.look.issues[0] ?? "sent back"}` });
        }
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
    // A plain step that finished earned its landing too.
    const xp = (xpByNode.get(key) ?? 0) + (node.state === "done" && seen.length === 0 ? XP.landed : 0);
    return {
      key, label: labelFor(key), state: node.state, cells: padded, total, done,
      repairs: repairs.get(key) ?? 0, retries: retries.get(key) ?? 0,
      cleanSweep: node.state === "done" && total > 1 && firstTime.get(key) === true
        && !(repairs.get(key) ?? 0) && !(retries.get(key) ?? 0),
      xp,
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

  const xp = levels.reduce((sum, l) => sum + l.steps.reduce((a, s) => a + s.xp, 0), 0) + cleared * XP.levelCleared;

  const badges: Badge[] = [];
  for (const l of levels) for (const s of l.steps) {
    if (s.cleanSweep) badges.push({ id: `clean:${s.key}`, label: "Clean sweep", detail: `${s.label}: ${s.total} passed first time` });
  }
  const comebacks = [...cells.entries()].flatMap(([node, m]) => [...m.values()].filter((c) => c.state === "passed")
    .filter((c) => moments.some((x) => (x.kind === "repair" || (x.kind === "look" && x.look?.verdict === "revise"))
                                        && x.node === node && x.subject === c.subject))
    .map((c) => ({ node, c })));
  if (comebacks.length) badges.push({ id: "comeback", label: "Comeback", detail: `${comebacks.length} sent back and then passed` });
  const firstLook = moments.find((m) => m.kind === "look" && m.look?.verdict === "pass" && (m.look?.attempt ?? 1) <= 1);
  if (firstLook?.look) badges.push({ id: "first-look", label: "First look", detail: `${firstLook.look.route} passed the reviewer at first sight` });
  if (bestStreak >= 10) badges.push({ id: "unbroken", label: "Unbroken", detail: `${bestStreak} in a row without a send-back` });
  const complete = run.status === "complete";
  if (complete && looksTotal >= 3 && looksPassed === looksByPage.size && [...looksByPage.values()].every((l) => l.verdict === "pass")) {
    badges.push({ id: "full-house", label: "Full house", detail: `every page passed the reviewer` });
  }
  const inFlight = run.nodes.filter((n) => n.state === "running").length;

  const most = [...sentBack.entries()].sort((a, b) => b[1] - a[1])[0];
  const outcomes: Outcomes = {
    allFirstLook: complete ? (looksTotal > 0 && !firstLookFailed) : null,
    mostSentBack: complete ? (most ? most[0] : "none") : null,
  };

  return {
    levels, current, cleared,
    stats: { calls: Math.max(calls, run.callsDone), repairs: [...repairs.values()].reduce((a, b) => a + b, 0),
             retries: [...retries.values()].reduce((a, b) => a + b, 0), inFlight,
             passRate: verdicts ? passes / verdicts : null,
             xp, streak, bestStreak, looks: { passed: looksPassed, total: looksTotal } },
    rank: rankFor(xp),
    ticker: ticker.slice(-TICKER).reverse(),
    landed: landed.slice(-LANDED).reverse(),
    looks: [...looksByPage.values()],
    badges, outcomes, paused,
  };
}
