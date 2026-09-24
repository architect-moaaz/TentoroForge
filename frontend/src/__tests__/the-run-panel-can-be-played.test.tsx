/**
 * The run panel can be played: what landed is read in words, a page's look
 * is shown and scored, points and badges are earned from the record, and a
 * bet placed before the pages are written resolves when the build ends.
 */
// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { BETS, QuestMap, betBonus } from "@/components/smith/QuestMap";
import { RANKS, XP, questModel, rankFor } from "@/components/smith/questModel";
import { reduce, type BlueprintRun } from "@/hooks/useBlueprintRun";

const EMPTY: BlueprintRun = {
  messages: [], thoughts: [], events: [], nodes: [], nodesDone: 0, nodesTotal: 0, callsDone: 0,
  alreadyComplete: [], awaitingApproval: false, unbuilt: [], forecast: null, usage: null,
  status: "idle", error: null, review: null,
};
const play = (steps: [string, Record<string, unknown>][], from: BlueprintRun = EMPTY) =>
  steps.reduce((s, [e, d]) => reduce(s, e, d), from);

const PLAN: [string, Record<string, unknown>] = ["plan", {
  nodes: ["entity_fields", "page_code"], total: 2, levels: [["entity_fields"], ["page_code"]],
}];
const LOOK = (subject: string, score: number, verdict: "pass" | "revise", attempt = 1, issues: string[] = []) =>
  ["page:look", { node: "page_code", subject, route: `/${subject.toLowerCase()}`, attempt, score, verdict, issues, broken: 0, shots: ["desktop", "mobile"] }] as [string, Record<string, unknown>];

describe("what landed", () => {
  it("is read in words, newest first", () => {
    const run = play([PLAN, ["node:start", { node: "entity_fields", subjects: 2 }],
      ["node:subject", { node: "entity_fields", subject: "ENTITY-001", total: 2, done: 1, ok: true, summary: "Doctor — 5 fields" }],
      ["node:subject", { node: "entity_fields", subject: "ENTITY-002", total: 2, done: 2, ok: true, summary: "Patient — 8 fields" }]]);
    const m = questModel(run);
    expect(m.landed.map((l) => l.summary)).toEqual(["Patient — 8 fields", "Doctor — 5 fields"]);
    expect(m.levels[0].steps[0].cells[0].summary).toBe("Doctor — 5 fields");
  });
});

describe("a page's look", () => {
  it("scores the page, feeds the gallery and colours the cell", () => {
    const run = play([PLAN, ["node:start", { node: "page_code", subjects: 2 }],
      ["node:subject", { node: "page_code", subject: "PAGE-001", total: 2, done: 1, ok: true }],
      LOOK("PAGE-001", 5, "revise", 1, ["no sort affordance"]),
      LOOK("PAGE-001", 8, "pass", 2),
      ["node:subject", { node: "page_code", subject: "PAGE-002", total: 2, done: 2, ok: true }],
      LOOK("PAGE-002", 9, "pass")]);
    const m = questModel(run);
    const page = m.levels[1].steps[0];
    expect(page.cells.map((c) => [c.subject, c.state, c.look?.score])).toEqual([["PAGE-001", "passed", 8], ["PAGE-002", "passed", 9]]);
    expect(m.looks.map((l) => [l.route, l.score, l.attempt])).toEqual([["/page-001", 8, 2], ["/page-002", 9, 1]]);
    expect(m.stats.looks).toEqual({ passed: 2, total: 3 });
    expect(m.ticker[0].text).toBe("/page-002 looked at: 9/10 — passed");
    expect(m.ticker[2].text).toBe("/page-001 looked at: 5/10 — no sort affordance");
    expect(m.badges.map((b) => b.id)).toEqual(expect.arrayContaining(["comeback", "first-look"]));
  });
});

describe("points, streaks and rank", () => {
  it("are earned from the record and never guessed", () => {
    const run = play([PLAN, ["node:start", { node: "entity_fields", subjects: 2 }],
      ["node:subject", { node: "entity_fields", subject: "A", total: 2, done: 1, ok: true }],
      ["observer:verdict", { node: "entity_fields", subject: "A", ok: true }],
      ["node:subject", { node: "entity_fields", subject: "B", total: 2, done: 2, ok: true }],
      ["observer:verdict", { node: "entity_fields", subject: "B", ok: false, findings: 1 }],
      ["observer:repair", { node: "entity_fields", subject: "B", round: 1, of: 2, reason: "- [x] missing column" }],
      ["observer:verdict", { node: "entity_fields", subject: "B", ok: true }],
      ["node:done", { node: "entity_fields" }]]);
    const m = questModel(run);
    const expected = XP.landed * 2 + XP.passFirst + XP.passAfterRepair + XP.levelCleared;
    expect(m.stats.xp).toBe(expected);
    expect(m.levels[0].steps[0].xp).toBe(expected - XP.levelCleared);
    expect(m.stats.streak).toBe(1);        // the send-back broke a streak of 3
    expect(m.stats.bestStreak).toBe(3);
    expect(m.rank.name).toBe(RANKS[0].name);
    expect(rankFor(650)).toEqual({ name: "Architect", at: 600, next: 1200 });
    expect(rankFor(9999).next).toBeNull();
  });
});

describe("bets", () => {
  const complete = play([PLAN, ["node:start", { node: "page_code", subjects: 1 }],
    ["node:subject", { node: "page_code", subject: "P", total: 1, done: 1, ok: true }],
    LOOK("P", 6, "revise"), LOOK("P", 8, "pass", 2),
    ["node:done", { node: "page_code" }], ["done", {}]]);

  it("resolve only when the build ends, against what happened", () => {
    const running = questModel(play([PLAN, LOOK("P", 6, "revise")]));
    expect(running.outcomes).toEqual({ allFirstLook: null, mostSentBack: null });
    const m = questModel(complete);
    expect(m.outcomes).toEqual({ allFirstLook: false, mostSentBack: "page_code" });
    expect(betBonus({ allFirstLook: "No", mostSentBack: "page_code" }, m.outcomes)).toBe(BETS.allFirstLook.bonus + BETS.mostSentBack.bonus);
    expect(betBonus({ allFirstLook: "Yes", mostSentBack: "entity_fields" }, m.outcomes)).toBe(0);
    expect(betBonus({ allFirstLook: "Yes" }, running.outcomes)).toBe(0);
  });
});

describe("the map is played, not read", () => {
  it("opens a step to what it makes and a subject to what the reviewer said", async () => {
    const run = play([["started", {}], PLAN, ["node:start", { node: "page_code", subjects: 2 }],
      ["node:subject", { node: "page_code", subject: "PAGE-001", total: 2, done: 1, ok: true, summary: "Manage Doctors · /admin/doctors" }],
      LOOK("PAGE-001", 5, "revise", 1, ["no sort affordance", "status dropped on mobile"])]);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(<QuestMap run={run} projectId="p1" />); });
    expect(host.querySelector('[data-testid="quest-xp"]')?.textContent).toBe(`${XP.landed} XP`);
    expect(host.querySelector('[data-testid="quest-gallery"]')).not.toBeNull();
    expect(host.querySelector('[data-testid="quest-bets"]')).not.toBeNull();
    expect(host.querySelector('[data-testid="quest-landed"]')?.textContent).toContain("Manage Doctors");
    // Open the step: what it makes.
    await act(async () => { (host.querySelector('[data-step="page_code"]') as HTMLButtonElement).click(); });
    expect(host.textContent).toContain("Every page as React");
    // Open the subject: what the reviewer said.
    await act(async () => { (host.querySelector('[data-cell="PAGE-001"]') as HTMLButtonElement).click(); });
    const detail = host.querySelector('[data-testid="quest-detail"]');
    expect(detail?.textContent).toContain("no sort affordance");
    expect(detail?.textContent).toContain("5/10");
    await act(async () => { root.unmount(); });
  });
});
