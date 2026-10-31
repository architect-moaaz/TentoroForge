import { describe, it, expect } from "vitest";
import {
  applyFix, changesDrawing, didNotPass, emptyBlast, estimateCalls, fixKindLabel, fixOutcome, FIX_HINT, isBad, outcomeSentence, reduceBlast, regression, revertFix,
  roundSummary, suspects, tally, toolNames, verdict, type BlastFix, type BlastResult,
} from "./agent-blast";
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

describe("taking a fix back out of the drawing", () => {
  const fix = (over: Partial<BlastFix>): BlastFix => ({ id: "f", kind: "instruction_add", title: "t", why: "w", fixesTests: [], ...over });
  const cfg = (list: AgentNodeSerialized[], i: number) => list[i].data.config as Record<string, unknown>;

  it("undoes an added instruction exactly, leaving the rest of the instructions as they were", () => {
    const f = fix({ nodeId: "sp", text: "Never act on an id you were not given." });
    const applied = applyFix(nodes(), f);
    expect(cfg(revertFix(applied, f), 0).prompt).toBe("You help with tickets.");
    // edited after the fix went in: only that sentence goes
    const edited = applyFix(nodes(), f);
    cfg(edited, 0).prompt = `Start. ${cfg(edited, 0).prompt}\nAnd then more.`;
    expect(cfg(revertFix(edited, f), 0).prompt).toBe("Start. You help with tickets.\n\nAnd then more.");
    expect(revertFix(nodes(), f), "a sentence that is not there: nothing to take out").toEqual(nodes());
  });

  it("puts the old tool description back, and switches ask-first off again", () => {
    const f = fix({ kind: "tool_description", nodeId: "t1", text: "Change a ticket only after a yes.", before: "Change a ticket" });
    expect(cfg(revertFix(applyFix(nodes(), f), f), 1).description).toBe("Change a ticket");
    const none = fix({ kind: "tool_description", nodeId: "t1", text: "New words.", before: "" });
    expect(cfg(revertFix(applyFix(nodes(), none), none), 1)).not.toHaveProperty("description");
    const ask = fix({ kind: "ask_first", nodeId: "t1" });
    expect(cfg(revertFix(applyFix(nodes(), ask), ask), 1).confirm).toBe(false);
  });

  it("is the reverse of applying: apply then undo leaves every box as it was (ask-first aside, which is offered only for one switched off)", () => {
    const f = fix({ nodeId: "sp", text: "Be brief." });
    expect(revertFix(applyFix(nodes(), f), f)).toEqual(nodes());
    const d = fix({ kind: "tool_description", nodeId: "t1", text: "Other words.", before: "Change a ticket" });
    expect(revertFix(applyFix(nodes(), d), d)).toEqual(nodes());
  });

  it("changes nothing for advice, an unknown box or a fix with no box, and never touches another box", () => {
    const before = nodes();
    expect(revertFix(before, fix({ kind: "advice", text: "x" }))).toBe(before);
    expect(revertFix(before, fix({ nodeId: "ghost", text: "x" })).map((n) => n.data.config)).toEqual(before.map((n) => n.data.config));
    const applied = applyFix(before, fix({ kind: "ask_first", nodeId: "t1" }));
    expect(revertFix(applied, fix({ kind: "ask_first", nodeId: "t1" }))[0]).toBe(applied[0]);
  });

  it("knows whether applying a fix would change anything at all", () => {
    const f = fix({ nodeId: "sp", text: "Never act on an id you were not given." });
    expect(changesDrawing(nodes(), f)).toBe(true);
    expect(changesDrawing(applyFix(nodes(), f), f), "already says it").toBe(false);
    expect(changesDrawing(nodes(), fix({ kind: "advice", text: "x" }))).toBe(false);
  });
});

describe("did a fix work", () => {
  const results = (rows: Array<[string, BlastResult["status"]]>) => Object.fromEntries(rows.map(([id, s]) => [id, result(id, s)]));

  it("says worked only when every test it was for now passes, partly when some do, no when none do", () => {
    expect(fixOutcome(["a", "b"], results([["a", "passed"], ["b", "passed"]]))).toEqual({ state: "worked", fixed: 2, total: 2 });
    expect(fixOutcome(["a", "b"], results([["a", "passed"], ["b", "failed"]]))).toEqual({ state: "partly", fixed: 1, total: 2 });
    expect(fixOutcome(["a", "b"], results([["a", "failed"], ["b", "failed"]]))).toEqual({ state: "no", fixed: 0, total: 2 });
  });

  it("counts a test that is only unstable as not fixed, and one that could not be run as saying nothing", () => {
    expect(fixOutcome(["a"], results([["a", "flaky"]])).state).toBe("no");
    expect(fixOutcome(["a", "b"], results([["a", "error"], ["b", "error"]])).state).toBe("unknown");
    expect(fixOutcome(["a", "b"], results([["a", "passed"], ["b", "error"]])).state).toBe("partly");
    expect(fixOutcome(["ghost"], {}).state, "no results at all").toBe("unknown");
    expect(fixOutcome(["a", "ghost"], results([["a", "passed"]])), "only tests that were run count").toEqual({ state: "worked", fixed: 1, total: 1 });
  });

  it("says each outcome in a sentence a builder can act on", () => {
    expect(outcomeSentence({ state: "worked", fixed: 1, total: 1 })).toBe("It worked: the test it was for is defused now.");
    expect(outcomeSentence({ state: "worked", fixed: 3, total: 3 })).toBe("It worked: all 3 tests it was for are defused now.");
    expect(outcomeSentence({ state: "partly", fixed: 1, total: 2 })).toBe("Partly: 1 of 2 tests defused now, the rest still go off.");
    expect(outcomeSentence({ state: "no", fixed: 0, total: 1 })).toContain("the test still goes off. Undo it, or try another fix.");
    expect(outcomeSentence({ state: "no", fixed: 0, total: 2 })).toContain("all 2 tests still go off");
    expect(outcomeSentence({ state: "unknown", fixed: 0, total: 0 })).toContain("could not be tested");
  });

  it("counts everything that did not pass as worth running again, and warns that a fix is a guess", () => {
    expect((["passed", "failed", "flaky", "error"] as const).map((s) => didNotPass(result("x", s)))).toEqual([false, true, true, true]);
    expect(FIX_HINT).toContain("may or may not work");
    expect(FIX_HINT).toContain("Apply and test");
  });
});


describe("a fix that narrows what a tool shows the assistant", () => {
  const filter: BlastFix = { id: "f", kind: "response_filter", title: "Hide internals", why: "", fixesTests: [], nodeId: "t1", tool: "update_ticket", keys: ["id", "subject"], beforeKeys: [] };
  const config = (ns: AgentNodeSerialized[]) => ns.find((n) => n.id === "t1")!.data.config as Record<string, unknown>;

  it("sets the fields the tool hands over, and taking it back out puts the old ones back, or none at all", () => {
    const applied = applyFix(nodes(), filter);
    expect(config(applied).response_filter).toEqual(["id", "subject"]);
    expect(config(applied).description, "nothing else in the box changes").toBe("Change a ticket");
    expect(config(revertFix(applied, filter)).response_filter, "it had none before: the key goes, not an empty list").toBeUndefined();
    const had = nodes();
    (had[1].data.config as Record<string, unknown>).response_filter = ["id", "status", "internal_note"];
    const back = { ...filter, beforeKeys: ["id", "status", "internal_note"] };
    expect(config(revertFix(applyFix(had, back), back)).response_filter).toEqual(["id", "status", "internal_note"]);
  });

  it("changes nothing without fields, never touches another box, and knows when the tool already says it", () => {
    expect(applyFix(nodes(), { ...filter, keys: [] })).toEqual(nodes());
    expect(applyFix(nodes(), { ...filter, nodeId: "sp" })[0].data.config).toEqual({ prompt: "You help with tickets." });
    expect(changesDrawing(nodes(), filter)).toBe(true);
    expect(changesDrawing(applyFix(nodes(), filter), filter)).toBe(false);
    expect(fixKindLabel("response_filter")).toBe("Show fewer fields");
  });
});

describe("did a fix break anything else", () => {
  const held = { a: result("a", "passed"), b: result("b", "passed"), c: result("c", "passed"), d: result("d", "failed") };

  it("suspects only what held before and does not now, and not what could not be run", () => {
    const after = { a: result("a", "passed"), b: result("b", "failed"), c: result("c", "flaky"), d: result("d", "failed") };
    expect(suspects(held, after, ["a", "b", "c", "d"])).toEqual(["b", "c"]);
    expect(suspects(held, { ...after, b: result("b", "error") }, ["b"]), "a test that could not be run says nothing").toEqual([]);
    expect(suspects(held, after, ["zzz"]), "a test with no result says nothing").toEqual([]);
  });

  it("says broke when it still goes off, shaky when it only sometimes holds, and counts how many were checked", () => {
    const after = { a: result("a", "passed"), b: result("b", "failed", { name: "Closes a ghost" }), c: result("c", "flaky"), d: result("d", "passed") };
    expect(regression(held, after, ["a", "b", "c", "d"])).toEqual({
      broke: [{ id: "b", name: "Closes a ghost" }], shaky: [{ id: "c", name: "c" }], checked: 3,
    });
    expect(regression(held, { a: result("a", "passed") }, ["a", "b"]).checked, "b was not run again: nothing to say about it").toBe(1);
    expect(regression(held, after, ["d"]).broke, "d did not hold before, so it cannot have been broken").toEqual([]);
  });

  it("a fix that broke something is not a success, whatever else it did, and the sentence names what it broke", () => {
    const after = { x: result("x", "passed"), b: result("b", "failed", { name: "Closes a ghost" }) };
    const regress = regression(held, after, ["b"]);
    const o = fixOutcome(["x"], after, regress);
    expect(o).toMatchObject({ state: "broke", fixed: 1, total: 1, checked: 1 });
    expect(regression(held, { ...after, d: result("d", "failed") }, ["b", "d"]).checked, "d was already failing: it cannot be broken, so it is not counted").toBe(1);
    expect(outcomeSentence(o)).toBe("It fixed 1 of 1 test, but it made 1 test that held before go off: “Closes a ghost”. Undo it, or try another fix.");
    expect(outcomeSentence(fixOutcome(["d"], { d: result("d", "failed") }, regress))).toContain("It did not fix what it was for, and it made 1 test that held before go off");
    expect(outcomeSentence({ state: "broke", fixed: 0, total: 1, broke: ["a", "b", "c", "d", "e"].map((id) => ({ id, name: id })) })).toContain("“a”, “b”, “c” and 2 more");
  });

  it("says nothing else broke when it checked and nothing did, and says what only sometimes holds now", () => {
    const clean = fixOutcome(["a"], { a: result("a", "passed") }, { broke: [], shaky: [], checked: 3 });
    expect(clean.state).toBe("worked");
    expect(outcomeSentence(clean)).toBe("It worked: the test it was for is defused now. Nothing else broke: the 3 other tests still hold.");
    expect(outcomeSentence(fixOutcome(["a"], { a: result("a", "passed") }, { broke: [], shaky: [], checked: 1 }))).toContain("the one other test still holds");
    const wobble = fixOutcome(["a"], { a: result("a", "passed") }, { broke: [], shaky: [{ id: "c", name: "Lists tickets" }], checked: 2 });
    expect(wobble.state, "still a success: it did not go off every time").toBe("worked");
    expect(outcomeSentence(wobble)).toContain("1 test that held before now hold only some of the time: “Lists tickets”.");
    expect(outcomeSentence(fixOutcome(["d"], { d: result("d", "failed") }, { broke: [], shaky: [], checked: 2 }))).toContain("Nothing else broke");
  });

  it("keeps the old sentences exactly when nothing else was checked", () => {
    expect(outcomeSentence(fixOutcome(["a"], { a: result("a", "passed") }))).toBe("It worked: the test it was for is defused now.");
    expect(fixOutcome(["a"], { a: result("a", "passed") })).toEqual({ state: "worked", fixed: 1, total: 1 });
    expect(outcomeSentence(fixOutcome(["a"], { a: result("a", "passed") }, { broke: [], shaky: [], checked: 0 }))).toBe("It worked: the test it was for is defused now.");
  });
});

describe("how many have finished in this run", () => {
  it("counts the results of this run only, so a re-run of three says three of three and not nine of three", () => {
    let s = reduceBlast(reduceBlast(emptyBlast(), { type: "start", total: 2, repeats: 1 }), { type: "result", result: result("a", "passed") });
    s = reduceBlast(s, { type: "result", result: result("b", "passed") });
    expect(s.ran).toBe(2);
    const again = reduceBlast(s, { type: "start", total: 1, repeats: 1 }, { merge: true });
    expect(again.ran).toBe(0);
    expect(reduceBlast(again, { type: "result", result: result("a", "failed") }, { merge: true })).toMatchObject({ ran: 1, order: ["a", "b"] });
    expect(emptyBlast().ran).toBe(0);
  });
});

describe("the tools of a drawing", () => {
  const drawn = (...tools: Array<[string | undefined, string | undefined]>) => ({
    nodes: [{ data: { nodeType: "system_prompt" } }, ...tools.map(([tool_name, label]) => ({ data: { nodeType: "tool", label, config: { tool_name } } })), { data: { nodeType: "memory", label: "Memory" } }],
  });

  it("names each tool the way the platform does: its own name, else its label, made safe, and made unique", () => {
    expect(toolNames(drawn(["list_tickets", "x"], [undefined, "Update ticket!"], ["list_tickets", "y"], ["", "  "]))).toEqual(["list_tickets", "Update_ticket", "list_tickets_2"]);
    expect(toolNames(drawn())).toEqual([]);
    expect(toolNames({})).toEqual([]);
    expect(toolNames({ nodes: "not a list" })).toEqual([]);
  });
});
