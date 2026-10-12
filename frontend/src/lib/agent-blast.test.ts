import { describe, it, expect } from "vitest";
import { applyFix, emptyBlast, estimateCalls, fixKindLabel, isBad, reduceBlast, roundSummary, tally, verdict, type BlastFix, type BlastResult } from "./agent-blast";
import type { AgentNodeSerialized } from "@/types/agent-builder";

const result = (id: string, status: BlastResult["status"], over: Partial<BlastResult> = {}): BlastResult => ({
  id, name: id, message: "m", status, failures: status === "passed" ? [] : ["It called update_ticket."], response: "", toolCalls: [], ...over,
});

const nodes = (): AgentNodeSerialized[] => [
  { id: "sp", type: "system_prompt", position: { x: 0, y: 0 }, data: { label: "P", nodeType: "system_prompt", config: { prompt: "You help with tickets." } } },
  { id: "t1", type: "tool", position: { x: 0, y: 0 }, data: { label: "update", nodeType: "tool", config: { tool_name: "update_ticket", description: "Change a ticket" } } },
];

describe("the stream of a blast", () => {
  it("starts by saying how many are coming, then gathers each result as it finishes, then the totals", () => {
    let s = reduceBlast(emptyBlast(), { type: "start", total: 3, repeats: 2 });
    expect(s).toMatchObject({ phase: "running", total: 3, repeats: 2, results: {}, order: [] });
    s = reduceBlast(s, { type: "result", result: result("b", "failed") });
    s = reduceBlast(s, { type: "result", result: result("a", "passed") });
    expect(s.order).toEqual(["b", "a"]);
    expect(Object.keys(s.results)).toEqual(["b", "a"]);
    s = reduceBlast(s, { type: "done", summary: { passed: 1, failed: 1, flaky: 0, error: 0, total: 2 } });
    expect(s).toMatchObject({ phase: "done", summary: { failed: 1 } });
  });

  it("a new round starts clean, and a re-run of a few adds to what is there", () => {
    const old = reduceBlast(reduceBlast(emptyBlast(), { type: "start", total: 1, repeats: 1 }), { type: "result", result: result("a", "failed") });
    expect(reduceBlast(old, { type: "start", total: 5, repeats: 1 }).results).toEqual({});
    const merged = reduceBlast(old, { type: "start", total: 1, repeats: 1 }, { merge: true });
    expect(Object.keys(merged.results)).toEqual(["a"]);
    const again = reduceBlast(merged, { type: "result", result: result("a", "passed") }, { merge: true });
    expect(again.results.a.status).toBe("passed");
    expect(again.order).toEqual(["a"]);
  });

  it("carries an error and ignores what it does not know", () => {
    expect(reduceBlast(emptyBlast(), { type: "error", message: "Finding problems needs a model key." })).toMatchObject({ phase: "error", error: "Finding problems needs a model key." });
    expect(reduceBlast(emptyBlast(), { type: "whatever" })).toEqual(emptyBlast());
  });
});

describe("how a round reads", () => {
  it("names how each bomb ended", () => {
    expect([verdict("passed"), verdict("failed"), verdict("flaky"), verdict("error")]).toEqual(["Defused", "Exploded", "Unstable", "Misfire"]);
    expect(isBad(result("a", "failed")) && isBad(result("a", "flaky"))).toBe(true);
    expect(isBad(result("a", "passed")) || isBad(result("a", "error"))).toBe(false);
  });

  it("totals what is held and puts it in a sentence, worst first", () => {
    const t = tally({ a: result("a", "failed"), b: result("b", "passed"), c: result("c", "passed"), d: result("d", "flaky"), e: result("e", "error") });
    expect(t).toEqual({ passed: 2, failed: 1, flaky: 1, error: 1, total: 5 });
    expect(roundSummary(t)).toBe("1 exploded · 1 unstable · 2 defused · 1 could not be run");
    expect(roundSummary({ passed: 4, failed: 0, flaky: 0, error: 0, total: 4 })).toBe("4 defused");
    expect(roundSummary({ passed: 0, failed: 0, flaky: 0, error: 0, total: 0 })).toBe("");
  });

  it("estimates the cost before anything is spent, the same way the platform does", () => {
    expect(estimateCalls(16, 1)).toBe(1 + 16 * 3 + 8 + 1);
    expect(estimateCalls(16, 3)).toBe(1 + 16 * 3 * 3 + 24 + 1);
    expect(estimateCalls(0, 1)).toBe(2);
    expect(estimateCalls(10, 1, 0)).toBe(1 + 30 + 0 + 1);
  });
});

describe("applying a fix to the drawing", () => {
  const fix = (over: Partial<BlastFix>): BlastFix => ({ id: "f", kind: "instruction_add", title: "t", why: "w", fixesTests: [], ...over });

  it("adds a sentence to the instructions, once, on top of what is there now", () => {
    const f = fix({ nodeId: "sp", text: "Never act on an id you were not given." });
    const once = applyFix(nodes(), f);
    expect((once[0].data.config as any).prompt).toBe("You help with tickets.\nNever act on an id you were not given.");
    expect((applyFix(once, f)[0].data.config as any).prompt).toBe((once[0].data.config as any).prompt);
    const moved = nodes();
    (moved[0].data.config as any).prompt = "A prompt edited since.";
    expect((applyFix(moved, f)[0].data.config as any).prompt).toBe("A prompt edited since.\nNever act on an id you were not given.");
  });

  it("sets a clearer tool description, and switches ask-first on", () => {
    const d = applyFix(nodes(), fix({ kind: "tool_description", nodeId: "t1", text: "Change a ticket only after a yes." }));
    expect((d[1].data.config as any).description).toBe("Change a ticket only after a yes.");
    expect((d[1].data.config as any).tool_name).toBe("update_ticket");
    expect((applyFix(nodes(), fix({ kind: "ask_first", nodeId: "t1" }))[1].data.config as any).confirm).toBe(true);
  });

  it("changes nothing for advice, an unknown box, or a fix with no box, and never touches another box", () => {
    const before = nodes();
    expect(applyFix(before, fix({ kind: "advice", text: "Look at the guardrails." }))).toBe(before);
    expect(applyFix(before, fix({ nodeId: "ghost", text: "x" })).map((n) => n.data.config)).toEqual(before.map((n) => n.data.config));
    const touched = applyFix(before, fix({ kind: "ask_first", nodeId: "t1" }));
    expect(touched[0]).toBe(before[0]);
    expect(before[1].data.config).not.toHaveProperty("confirm");
  });

  it("labels each kind in words", () => {
    expect(["instruction_add", "tool_description", "ask_first", "advice"].map((k) => fixKindLabel(k as BlastFix["kind"]))).toEqual([
      "Add to the instructions", "Clearer tool description", "Ask the person first", "Worth a look",
    ]);
  });
});
