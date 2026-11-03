/**
 * A build the person stopped must not read as a build that broke.
 *
 * On forge-v3, 2026-11-02, a person paused a 28-node build. The orchestrator
 * recorded every unreached node as `node:skipped` with the reason "paused:
 * stopped by the person", and the panel drew a red cross on all 28 while
 * ticking each level green — because `skipped` was folded into `failed`, and
 * a level counted as done when its steps were done OR failed. The banner
 * underneath said "Nothing is lost; the next build continues from here",
 * which is the truth these tests pin down.
 */
import { describe, it, expect } from "vitest";
import { questModel } from "@/components/smith/questModel";
import type { BlueprintRun, RunNode } from "@/hooks/useBlueprintRun";

function run(nodes: RunNode[], levels?: string[][]): BlueprintRun {
  return {
    status: "running", nodes, levels: levels ?? [nodes.map((n) => n.key)],
    events: [], thoughts: [], moments: [], looks: [],
    nodesDone: nodes.filter((n) => n.state === "done").length,
    nodesTotal: nodes.length, callsDone: 0, alreadyComplete: [],
    awaitingApproval: false,
  } as unknown as BlueprintRun;
}

const node = (key: string, state: RunNode["state"]): RunNode => ({ key, state, calls: 0 });

describe("a paused build", () => {
  it("does not mark its skipped levels done", () => {
    const m = questModel(run([node("backend", "skipped"), node("page_code", "skipped")]));
    expect(m.levels[0].state).not.toBe("done");
  });

  it("keeps skipped distinct from failed on the card", () => {
    const m = questModel(run([node("backend", "skipped"), node("page_code", "failed")]));
    const states = m.levels[0].steps.map((s) => s.state);
    expect(states).toEqual(["skipped", "failed"]);
  });

  it("is still ahead, not active, when nothing has run", () => {
    const m = questModel(run([node("backend", "skipped"), node("page_code", "skipped")]));
    expect(m.levels[0].state).toBe("ahead");
  });
});

describe("a level that genuinely finished", () => {
  it("is done when every step is done", () => {
    const m = questModel(run([node("backend", "done"), node("page_code", "done")]));
    expect(m.levels[0].state).toBe("done");
  });

  it("is done when a step failed — a failure settles it, a pause does not", () => {
    const m = questModel(run([node("backend", "done"), node("page_code", "failed")]));
    expect(m.levels[0].state).toBe("done");
  });

  it("is active while one step is still running", () => {
    const m = questModel(run([node("backend", "done"), node("page_code", "running")]));
    expect(m.levels[0].state).toBe("active");
  });

  it("is active once some steps are settled and the rest were skipped", () => {
    const m = questModel(run([node("backend", "done"), node("page_code", "skipped")]));
    expect(m.levels[0].state).toBe("active");
  });
});
