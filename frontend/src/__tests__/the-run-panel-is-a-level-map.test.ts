/**
 * The run panel draws the build as a level map, from what the run recorded.
 *
 * A list of stages ticking off said how far a build was and nothing about
 * what it is: steps running side by side, a step that is twelve calls at
 * once, the reviewer sending one back, a retry, a wait on the API. The map
 * is derived from structured moments the reducer now keeps — never from
 * summary text.
 */
import { describe, expect, it } from "vitest";

import { questModel } from "@/components/smith/questModel";
import { reduce, type BlueprintRun } from "@/hooks/useBlueprintRun";

const EMPTY: BlueprintRun = {
  messages: [], thoughts: [], events: [], nodes: [], nodesDone: 0, nodesTotal: 0, callsDone: 0,
  alreadyComplete: [], awaitingApproval: false, unbuilt: [], forecast: null, usage: null,
  status: "idle", error: null, review: null,
};

function play(steps: [string, Record<string, unknown>][]): BlueprintRun {
  return steps.reduce((s, [e, d]) => reduce(s, e, d), EMPTY);
}

const PLAN: [string, Record<string, unknown>] = ["plan", {
  nodes: ["requirements", "data_model", "design_system", "entity_fields"], total: 4,
  levels: [["requirements"], ["data_model", "design_system"], ["entity_fields"]],
}];

describe("levels and the step cards", () => {
  it("lays the plan out in its levels, with parallel steps side by side", () => {
    const m = questModel(play([PLAN]));
    expect(m.levels.map((l) => l.steps.map((s) => s.label))).toEqual([
      ["Requirements"], ["Entities", "Design system"], ["Entity fields"]]);
    expect(m.current).toBe(0);
  });

  it("knows which level is in play, folds the done ones and dims the ones ahead", () => {
    const m = questModel(play([PLAN, ["node:start", { node: "requirements" }], ["node:done", { node: "requirements" }],
                               ["node:start", { node: "data_model" }], ["node:start", { node: "design_system" }]]));
    expect(m.levels.map((l) => l.state)).toEqual(["done", "active", "ahead"]);
    expect(m.current).toBe(2);
    expect(m.cleared).toBe(1);
    expect(m.stats.inFlight).toBe(2);
  });
});

describe("a fan-out step's cells", () => {
  const FAN: [string, Record<string, unknown>][] = [PLAN,
    ["node:start", { node: "entity_fields", subjects: 3 }],
    ["node:subject", { node: "entity_fields", subject: "ENTITY-001", index: 1, total: 3, done: 1, ok: true }],
    ["observer:verdict", { node: "entity_fields", subject: "ENTITY-001", ok: true, findings: 0 }],
    ["node:subject", { node: "entity_fields", subject: "ENTITY-002", index: 2, total: 3, done: 2, ok: true }],
    ["observer:verdict", { node: "entity_fields", subject: "ENTITY-002", ok: false, findings: 2 }],
    ["observer:repair", { node: "entity_fields", subject: "ENTITY-002", round: 1, of: 2,
      reason: "The observer reviewed…\n\n- [Observer↔Requirement] ENTITY-002: REQ-004: no created-at column" }],
    ["node:retry", { node: "entity_fields", subject: "ENTITY-003", attempt: 2, of: 2, reason: "InvalidEntityFields: labelField" }],
  ];

  it("colours each subject by its standing and counts the repairs and retries", () => {
    const m = questModel(play(FAN));
    const card = m.levels[2].steps[0];
    expect(card.cells.map((c) => [c.subject, c.state])).toEqual([
      ["ENTITY-001", "passed"], ["ENTITY-002", "sent_back"], ["ENTITY-003", "retry"]]);
    expect(card.cells[1].note).toBe("ENTITY-002: REQ-004: no created-at column");
    expect([card.total, card.done, card.repairs, card.retries]).toEqual([3, 2, 1, 1]);
    expect(m.stats).toMatchObject({ calls: 2, repairs: 1, retries: 1, passRate: 0.5 });
  });

  it("tells what the reviewer said, newest first", () => {
    const m = questModel(play(FAN));
    expect(m.ticker.map((t) => [t.tone, t.text])).toEqual([
      ["retry", "Entity fields · ENTITY-003 asked again (2/2)"],
      ["back", "Entity fields · ENTITY-002 sent back: ENTITY-002: REQ-004: no created-at column"],
      ["pass", "Entity fields · ENTITY-001 passed review"],
    ]);
  });

  it("awards a clean sweep only to a fan-out that passed untouched, and a comeback to a repaired pass", () => {
    const clean = play([PLAN, ["node:start", { node: "entity_fields" }],
      ["node:subject", { node: "entity_fields", subject: "A", total: 2, done: 1, ok: true }],
      ["node:subject", { node: "entity_fields", subject: "B", total: 2, done: 2, ok: true }],
      ["observer:verdict", { node: "entity_fields", subject: "A", ok: true }],
      ["observer:verdict", { node: "entity_fields", subject: "B", ok: true }],
      ["node:done", { node: "entity_fields" }]]);
    expect(questModel(clean).badges.map((b) => b.label)).toEqual(["Clean sweep"]);
    const back = play([...FAN, ["observer:verdict", { node: "entity_fields", subject: "ENTITY-002", ok: true }]]);
    expect(questModel(back).badges.map((b) => b.label)).toEqual(["Comeback"]);
  });

  it("shows a wait on the API and a pause for credit", () => {
    const m = questModel(play([PLAN, ["node:start", { node: "entity_fields" }],
      ["node:stalled", { node: "entity_fields", subject: "ENTITY-001", reason: "529" }],
      ["run:paused", { reason: "Your credit balance is too low" }]]));
    expect(m.levels[2].steps[0].cells[0].state).toBe("waiting");
    expect(m.paused).toBe("Your credit balance is too low");
    expect(m.ticker[0].text).toBe("Paused: Your credit balance is too low");
  });
});

describe("several levels open at once", () => {
  it("names the furthest level in play, not the first", () => {
    const m = questModel(play([PLAN, ["node:start", { node: "requirements" }],
      ["node:start", { node: "data_model" }], ["node:done", { node: "data_model" }],
      ["node:start", { node: "entity_fields" }]]));
    expect(m.levels.map((l) => l.state)).toEqual(["active", "active", "active"]);
    expect(m.current).toBe(3);
  });
});

describe("without levels from the engine", () => {
  it("still draws one level per stage", () => {
    const m = questModel(play([["plan", { nodes: ["requirements", "data_model"], total: 2 }]]));
    expect(m.levels.map((l) => l.steps.map((s) => s.key))).toEqual([["requirements"], ["data_model"]]);
  });
});
