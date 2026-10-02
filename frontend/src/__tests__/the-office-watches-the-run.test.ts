/**
 * The office is told what the run is doing, in its own words.
 *
 * The v3 panel showed a build as stages ticking off — linear, and silent
 * about the fan-out, the reviewer, the retries and the API stalls that are
 * most of what happens. The office animates all of those; it only lacked
 * the events. This is the translation, event by event.
 */
import { describe, expect, it } from "vitest";

import { OfficeBridge, REVIEWER } from "@/components/smith/officeBridge";
import { AGENT_REGISTRY } from "@/components/virtual-office/types";

const PLAN = {
  nodes: ["requirements", "data_model", "design_system", "entity_fields", "page_code"],
  agents: { requirements: "requirement", data_model: "data_model", design_system: "accessibility",
            entity_fields: "data_model", page_code: "ui_engineer" },
  levels: [["requirements"], ["data_model", "design_system"], ["entity_fields"], ["page_code"]],
};

function bridge() {
  const b = new OfficeBridge();
  b.translate("plan", PLAN);
  return b;
}

describe("the plan seats the roster and says who works beside whom", () => {
  it("rosters each node's agent once, in levels", () => {
    const [ev] = new OfficeBridge().translate("plan", PLAN);
    expect(ev).toEqual({ type: "run_plan", agents: ["requirement", "data_model", "accessibility", "ui_engineer"],
                         levels: [["requirement"], ["data_model", "accessibility"], ["data_model"], ["ui_engineer"]] });
  });
});

describe("a node's life on the floor", () => {
  it("starts at a desk with the verb, counts its subjects in hand, and finishes", () => {
    const b = bridge();
    expect(b.translate("node:start", { node: "entity_fields" }))
      .toEqual([{ type: "agent_start", agent: "data_model", room: "discovery", action: "Detailing each entity's fields", node: "entity_fields" }]);
    expect(b.translate("node:subject", { node: "entity_fields", subject: "ENTITY-003", done: 2, total: 12 }))
      .toEqual([{ type: "agent_status", agent: "data_model", status: "Detailing each entity's fields (3/12)", subject: "ENTITY-003", node: "entity_fields" }]);
    expect(b.translate("node:done", { node: "entity_fields" })).toEqual([{ type: "agent_complete", agent: "data_model", node: "entity_fields" }]);
  });

  it("is sent back by the reviewer, and tries again", () => {
    const b = bridge();
    expect(b.translate("observer:verdict", { node: "entity_fields", subject: "ENTITY-003", ok: false, findings: 2 })).toEqual([
      { type: "agent_start", agent: REVIEWER, room: "qa", action: "Reviewing Entity fields", node: "entity_fields" },
      { type: "agent_status", agent: REVIEWER, node: "entity_fields", status: "Entity fields · ENTITY-003: 2 findings" },
    ]);
    const [retry] = b.translate("observer:repair", { node: "entity_fields", subject: "ENTITY-003", round: 1, of: 2,
      reason: "The observer reviewed your output…\n\n- [Observer↔Requirement] ENTITY-003: REQ-004: no created-at column" });
    expect(retry).toEqual({ type: "agent_retry", agent: "data_model", attempt: 1, of: 2,
                            reason: "Sent back: ENTITY-003: REQ-004: no created-at column" });
    expect(b.translate("node:retry", { node: "page_code", attempt: 2, of: 3, reason: "CompileError: x" })[0])
      .toMatchObject({ type: "agent_retry", agent: "ui_engineer", attempt: 2, of: 3 });
    expect(b.translate("observer:verdict", { node: "entity_fields", ok: true, findings: 0 })[1])
      .toMatchObject({ status: "Entity fields: passes" });
  });

  it("waits for a busy API, and strikes when the credit runs out — once", () => {
    const b = bridge();
    expect(b.translate("node:stalled", { node: "page_code", reason: "529" })[0])
      .toMatchObject({ type: "agent_status", agent: "ui_engineer", status: "The API is busy — waiting to try again" });
    expect(b.translate("run:paused", { reason: "Your credit balance is too low" }))
      .toEqual([{ type: "credits_exhausted", message: "Your credit balance is too low" }]);
    expect(b.translate("done", { paused: "Your credit balance is too low", failed: [], blocked: [] })).toEqual([]);
  });

  it("ends in a party when nothing failed, and stands down when something did", () => {
    expect(bridge().translate("done", { completed: ["a"], failed: [], blocked: [], skipped: [] }))
      .toEqual([{ type: "build_success" }]);
    expect(bridge().translate("done", { completed: ["a"], failed: [{ node: "page_code" }], blocked: [], skipped: ["x"] }))
      .toEqual([{ type: "run_complete", completed: 1, failed: 1, blocked: 0, skipped: 1 }]);
  });

  it("says nothing about a node the plan did not name", () => {
    expect(bridge().translate("node:start", { node: "not_in_plan" })).toEqual([]);
  });
});

describe("every agent the build can name has a desk", () => {
  it("includes the analytics designer", () => {
    const ids = new Set(AGENT_REGISTRY.map((a) => a.id));
    for (const agent of ["requirement", "product_analysis", "accessibility", "data_model", "page_design", "workflow",
                         "business_rules", "security", "analytics", "ui_director", "ui_engineer", "page_template",
                         "api", "backend", "frontend", "integration", "figma_intelligence", "solution_architecture"]) {
      expect(ids.has(agent), agent).toBe(true);
    }
  });
});
