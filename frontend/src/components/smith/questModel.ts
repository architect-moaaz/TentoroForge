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
 * screenshotted and scored, a retry, a wait on the API. And above the map,
 * the application taking shape: its data, screens, workflows and design as
 * counts of what is decided, written and reviewed — progress a person can
 * trust, in the product's own terms.
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
}

export interface Level { index: number; steps: StepCard[]; state: "done" | "active" | "ahead" }

export interface Ticker { seq: number; tone: "pass" | "back" | "retry" | "wait" | "note" | "look"; text: string }

/** Something taking shape: a subject that landed, with what it is. */
export interface Landed { seq: number; node: string; subject: string; label: string; summary: string }

/** A fact about the build worth pointing at — in the product's terms. */
export interface Highlight { id: string; label: string; detail: string }

/** One line of an area: a step, with how far it is. */
export interface AreaItem {
  key: string;
  label: string;
  state: RunNode["state"];
  done: number;
  total: number;
}

/** A part of the application taking shape: its data, its screens, its
 *  workflows, its design, and the build itself. */
export interface Area {
  key: "data" | "screens" | "workflows" | "design" | "build";
  label: string;
  items: AreaItem[];
  /** 0..1 over the area's steps, weighted by their subjects. */
  progress: number;
  state: "ahead" | "active" | "done";
  /** One line on where it stands ("5 entities · 38 fields"). */
  note: string;
}

/** A milestone of the build, in the order they are reached. */
export interface Milestone { key: string; label: string; state: "ahead" | "active" | "done" }

export interface QuestModel {
  levels: Level[];
  current: number;                 // 1-based furthest level in play, 0 before the plan
  cleared: number;                 // levels every step of which is done
  stats: {
    calls: number; repairs: number; retries: number; inFlight: number; passRate: number | null;
    /** Reviews: how many checks passed, how many were fixed after a send-back, how many are open. */
    review: { passed: number; fixed: number; open: number };
    looks: { passed: number; total: number };
  };
  areas: Area[];
  milestones: Milestone[];
  ticker: Ticker[];
  landed: Landed[];
  /** The latest look at each page, in the order the pages were first seen. */
  looks: RunLook[];
  highlights: Highlight[];
  paused?: string;
}

const TICKER = 5;
const LANDED = 6;

/** The application's areas, and the steps that build each. */
export const AREAS: { key: Area["key"]; label: string; steps: string[] }[] = [
  { key: "data", label: "Data", steps: ["data_model", "entity_fields", "content_fields", "database"] },
  { key: "screens", label: "Screens", steps: ["ux_architecture", "page_contracts", "page_details", "auth_pages", "page_layouts", "page_code"] },
  { key: "workflows", label: "Workflows", steps: ["workflows", "workflow_steps", "business_rules", "security", "apis", "integrations"] },
  { key: "design", label: "Design", steps: ["design_system", "brand_design_system", "figma_design_system", "imagery", "ui_direction"] },
  { key: "build", label: "Build", steps: ["backend", "frontend", "integration", "assemble", "verification", "testing"] },
];

/** The milestones, by the step whose completion reaches each. */
export const MILESTONES: { key: string; label: string }[] = [
  { key: "requirements", label: "Understood" },
  { key: "data_model", label: "Data modelled" },
  { key: "design_system", label: "Design decided" },
  { key: "page_contracts", label: "Screens planned" },
  { key: "workflow_steps", label: "Workflows written" },
  { key: "page_code", label: "Pages written" },
  { key: "assemble", label: "Built" },
];

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
  const touched = new Set<string>();                     // "node/subject" sent back or retried
  const ticker: Ticker[] = [];
  const landed: Landed[] = [];
  const looksByPage = new Map<string, RunLook>();
  let calls = 0, passes = 0, verdicts = 0, paused: string | undefined;
  let fixed = 0, looksPassed = 0, looksTotal = 0;

  const cell = (node: string, subject: string): Cell => {
    const m = cells.get(node) ?? new Map<string, Cell>();
    cells.set(node, m);
    const c = m.get(subject) ?? { subject, state: "pending" };
    m.set(subject, c);
    return c;
  };
  const name = (m: RunMoment) => (m.subject ? `${labelFor(m.node)} · ${m.subject}` : labelFor(m.node));

  moments.forEach((m, seq) => {
    const key = `${m.node}/${m.subject}`;
    switch (m.kind) {
      case "subject": {
        calls += 1;
        const c = cell(m.node, m.subject);
        if (c.state === "pending" || c.state === "retry" || c.state === "waiting") c.state = m.ok ? "done" : "retry";
        if (m.summary) c.summary = m.summary;
        if (m.ok && m.summary) landed.push({ seq, node: m.node, subject: m.subject, label: labelFor(m.node), summary: m.summary });
        break;
      }
      case "verdict": {
        verdicts += 1;
        const c = cell(m.node, m.subject);
        if (m.ok) {
          passes += 1;
          c.state = "passed";
          if (!firstTime.has(m.node)) firstTime.set(m.node, true);
          if (touched.has(key)) fixed += 1;
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
          if (touched.has(key)) fixed += 1;
          ticker.push({ seq, tone: "look", text: `${route} reviewed: ${m.look.score}/10 — passed` });
        } else {
          touched.add(key);
          c.state = "sent_back";
          c.note = m.look.issues[0] ?? `${m.look.score}/10`;
          ticker.push({ seq, tone: "look", text: `${route} reviewed: ${m.look.score}/10 — ${m.look.issues[0] ?? "sent back"}` });
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

  const steps = new Map(levels.flatMap((l) => l.steps).map((s) => [s.key, s]));
  const complete = run.status === "complete";

  // THE APPLICATION TAKING SHAPE. Each area is the steps that build it,
  // weighted by their subjects: "Screens 12 of 27 pages written" is progress
  // in the product's terms, where "node 9 of 14" is progress in the
  // generator's. A step not in this plan does not count against the area.
  const areas: Area[] = AREAS.map((a) => {
    const items: AreaItem[] = a.steps.filter((k) => steps.has(k)).map((k) => {
      const s = steps.get(k)!;
      const total = Math.max(1, s.total);
      const done = s.state === "done" ? total : Math.min(total, s.done);
      return { key: k, label: s.label, state: s.state, done, total };
    });
    const weight = items.reduce((n, i) => n + i.total, 0);
    const progress = weight ? items.reduce((n, i) => n + i.done, 0) / weight : 0;
    const state: Area["state"] = items.length && items.every((i) => i.state === "done" || i.state === "failed") ? "done"
      : items.some((i) => i.state === "running" || i.done > 0) ? "active" : "ahead";
    return { key: a.key, label: a.label, items, progress, state, note: areaNote(a.key, items, run, looksPassed, looksTotal) };
  }).filter((a) => a.items.length > 0);

  const milestones: Milestone[] = MILESTONES.filter((m) => steps.has(m.key)).map((m) => {
    const s = steps.get(m.key)!;
    return { key: m.key, label: m.label, state: s.state === "done" ? "done" : s.state === "running" || s.done > 0 ? "active" : "ahead" };
  });

  const highlights: Highlight[] = [];
  for (const s of steps.values()) {
    if (s.cleanSweep) highlights.push({ id: `clean:${s.key}`, label: `${s.label}: all ${s.total} passed first review`, detail: "No send-backs, no retries." });
  }
  if (fixed) highlights.push({ id: "fixed", label: `${fixed} fixed on review`, detail: "Sent back by the reviewer and passed on the rewrite." });
  if (complete && looksTotal >= 3 && [...looksByPage.values()].every((l) => l.verdict === "pass")) {
    highlights.push({ id: "all-pages", label: "Every page passed review", detail: `${looksByPage.size} pages, each reviewed on a desk and a phone.` });
  }
  const inFlight = run.nodes.filter((n) => n.state === "running").length;
  const open = [...cells.values()].flatMap((m) => [...m.values()]).filter((c) => c.state === "sent_back" || c.state === "review" || c.state === "noted").length;

  return {
    levels, current, cleared,
    stats: { calls: Math.max(calls, run.callsDone), repairs: [...repairs.values()].reduce((a, b) => a + b, 0),
             retries: [...retries.values()].reduce((a, b) => a + b, 0), inFlight,
             passRate: verdicts ? passes / verdicts : null,
             review: { passed: passes + looksPassed, fixed, open },
             looks: { passed: looksPassed, total: looksTotal } },
    areas, milestones,
    ticker: ticker.slice(-TICKER).reverse(),
    landed: landed.slice(-LANDED).reverse(),
    looks: [...looksByPage.values()],
    highlights, paused,
  };
}

/** Where an area stands, in one line of the product's terms. */
function areaNote(key: Area["key"], items: AreaItem[], run: BlueprintRun, looksPassed: number, looksTotal: number): string {
  const by = new Map(items.map((i) => [i.key, i]));
  const f = run.forecast ?? {};
  const n = (k: string) => by.get(k);
  switch (key) {
    case "data": {
      const fields = n("entity_fields");
      const ents = fields ? fields.total : f.entities ?? 0;
      return fields ? `${fields.done} of ${ents} entities detailed` : ents ? `${ents} entities` : "";
    }
    case "screens": {
      const code = n("page_code"), contracts = n("page_details");
      if (code && code.done) return `${code.done} of ${code.total} pages written` + (looksTotal ? ` · ${looksPassed} passed review` : "");
      if (contracts && contracts.done) return `${contracts.done} of ${contracts.total} page contracts`;
      return f.pages ? `${f.pages} pages planned` : "";
    }
    case "workflows": {
      const stepsItem = n("workflow_steps");
      return stepsItem && stepsItem.done ? `${stepsItem.done} of ${stepsItem.total} workflows written` : f.workflows ? `${f.workflows} workflows` : "";
    }
    case "design":
      return items.filter((i) => i.state === "done").map((i) => i.label.toLowerCase()).join(" · ");
    case "build":
      return items.filter((i) => i.state === "done").map((i) => i.label.toLowerCase()).join(" · ");
  }
}
