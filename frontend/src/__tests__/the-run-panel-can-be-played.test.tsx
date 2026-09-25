/**
 * The run panel shows the application taking shape, and can be opened.
 *
 * What landed is read in words; the product's areas carry real counts in
 * its own terms; milestones and the review line come from the record; a
 * page's review is shown with the screenshot it was scored on; a step opens
 * to what it makes and a subject to what the reviewer said.
 */
// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { QuestMap } from "@/components/smith/QuestMap";
import { AREAS, MILESTONES, questModel } from "@/components/smith/questModel";
import { reduce, type BlueprintRun } from "@/hooks/useBlueprintRun";

const EMPTY: BlueprintRun = {
  messages: [], thoughts: [], events: [], nodes: [], nodesDone: 0, nodesTotal: 0, callsDone: 0,
  alreadyComplete: [], awaitingApproval: false, unbuilt: [], forecast: null, usage: null,
  status: "idle", error: null, review: null,
};
const play = (steps: [string, Record<string, unknown>][], from: BlueprintRun = EMPTY) =>
  steps.reduce((s, [e, d]) => reduce(s, e, d), from);

const PLAN: [string, Record<string, unknown>] = ["plan", {
  nodes: ["requirements", "data_model", "entity_fields", "page_code"], total: 4,
  levels: [["requirements"], ["data_model"], ["entity_fields"], ["page_code"]],
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
    expect(m.levels[2].steps[0].cells[0].summary).toBe("Doctor — 5 fields");
  });
});

describe("the application's areas", () => {
  it("count progress in the product's terms and only over the steps in the plan", () => {
    const run = play([PLAN, ["node:start", { node: "requirements" }], ["node:done", { node: "requirements" }],
      ["node:start", { node: "data_model" }], ["node:done", { node: "data_model" }],
      ["node:start", { node: "entity_fields", subjects: 4 }],
      ["node:subject", { node: "entity_fields", subject: "A", total: 4, done: 1, ok: true }],
      ["node:subject", { node: "entity_fields", subject: "B", total: 4, done: 2, ok: true }]]);
    const m = questModel(run);
    expect(m.areas.map((a) => a.key)).toEqual(["data", "screens"]);
    const data = m.areas[0];
    expect(data.items.map((i) => [i.key, i.done, i.total])).toEqual([["data_model", 1, 1], ["entity_fields", 2, 4]]);
    expect(data.progress).toBe(3 / 5);
    expect(data.note).toBe("2 of 4 entities detailed");
    expect(data.state).toBe("active");
    expect(m.areas[1].state).toBe("ahead");
    expect(m.milestones.map((x) => [x.key, x.state])).toEqual([["requirements", "done"], ["data_model", "done"], ["page_code", "ahead"]]);
    expect(AREAS.flatMap((a) => a.steps)).toContain("page_code");
    expect(MILESTONES.map((x) => x.key)).toContain("assemble");
  });

  it("say what the screens are, from the pages written and reviewed", () => {
    const run = play([PLAN, ["node:start", { node: "page_code", subjects: 3 }],
      ["node:subject", { node: "page_code", subject: "PAGE-001", total: 3, done: 1, ok: true }],
      LOOK("PAGE-001", 8, "pass")]);
    const screens = questModel(run).areas.find((a) => a.key === "screens")!;
    expect(screens.note).toBe("1 of 3 pages written · 1 passed review");
  });
});

describe("a page's review", () => {
  it("scores the page, feeds the gallery and the review line", () => {
    const run = play([PLAN, ["node:start", { node: "page_code", subjects: 2 }],
      ["node:subject", { node: "page_code", subject: "PAGE-001", total: 2, done: 1, ok: true }],
      LOOK("PAGE-001", 5, "revise", 1, ["no sort affordance"]),
      LOOK("PAGE-001", 8, "pass", 2),
      ["node:subject", { node: "page_code", subject: "PAGE-002", total: 2, done: 2, ok: true }],
      LOOK("PAGE-002", 9, "pass")]);
    const m = questModel(run);
    const page = m.levels[3].steps[0];
    expect(page.cells.map((c) => [c.subject, c.state, c.look?.score])).toEqual([["PAGE-001", "passed", 8], ["PAGE-002", "passed", 9]]);
    expect(m.looks.map((l) => [l.route, l.score, l.attempt])).toEqual([["/page-001", 8, 2], ["/page-002", 9, 1]]);
    expect(m.stats.looks).toEqual({ passed: 2, total: 3 });
    expect(m.stats.review).toEqual({ passed: 2, fixed: 1, open: 0 });
    expect(m.ticker[0].text).toBe("/page-002 reviewed: 9/10 — passed");
    expect(m.highlights.map((h) => h.label)).toEqual(["1 fixed on review"]);
  });
});

describe("highlights are facts", () => {
  it("name a step whose every subject passed first review", () => {
    const run = play([PLAN, ["node:start", { node: "entity_fields", subjects: 2 }],
      ["node:subject", { node: "entity_fields", subject: "A", total: 2, done: 1, ok: true }],
      ["observer:verdict", { node: "entity_fields", subject: "A", ok: true }],
      ["node:subject", { node: "entity_fields", subject: "B", total: 2, done: 2, ok: true }],
      ["observer:verdict", { node: "entity_fields", subject: "B", ok: true }],
      ["node:done", { node: "entity_fields" }]]);
    const m = questModel(run);
    expect(m.highlights.map((h) => h.label)).toEqual(["Entity fields: all 2 passed first review"]);
    expect(m.stats.review).toEqual({ passed: 2, fixed: 0, open: 0 });
  });
});

describe("the panel is opened, not read", () => {
  it("opens an area to its steps, a step to what it makes and a subject to what the reviewer said", async () => {
    const run = play([["started", {}], PLAN, ["node:start", { node: "page_code", subjects: 2 }],
      ["node:subject", { node: "page_code", subject: "PAGE-001", total: 2, done: 1, ok: true, summary: "Manage Doctors · /admin/doctors" }],
      LOOK("PAGE-001", 5, "revise", 1, ["no sort affordance", "status dropped on mobile"])]);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(<QuestMap run={run} projectId="p1" />); });
    expect(host.querySelector('[data-testid="quest-areas"]')?.textContent).toContain("Screens");
    expect(host.querySelector('[data-testid="quest-milestones"]')?.textContent).toContain("Pages written");
    expect(host.querySelector('[data-testid="quest-review"]')?.textContent).toContain("1 open");
    expect(host.querySelector('[data-testid="quest-gallery"]')).not.toBeNull();
    expect(host.querySelector('[data-testid="quest-landed"]')?.textContent).toContain("Manage Doctors");
    expect(host.textContent).not.toContain("XP");
    // Open the area: its steps and counts.
    await act(async () => { (host.querySelector('[data-area="screens"] button') as HTMLButtonElement).click(); });
    expect(host.querySelector('[data-area="screens"]')?.textContent).toContain("1/2");
    // Open the build detail, then the step: what it makes.
    await act(async () => { (host.querySelector('[data-testid="quest-detail-toggle"]') as HTMLButtonElement).click(); });
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
