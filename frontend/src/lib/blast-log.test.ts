import { describe, it, expect } from "vitest";
import { MAX_LOG, appendLines, linesForEvent, logText, stamp, tag, type LogContext, type LogLine } from "./blast-log";

const ctx: LogContext = { total: 16, bombTitle: (k) => ({ made_up_id: "Made-up ID", no_permission: "Change without asking" } as Record<string, string>)[k ?? ""] ?? null };
const one = (e: any) => linesForEvent(e, ctx);

describe("how the log reads", () => {
  it("stamps each line with how long into the blast it was printed", () => {
    expect(stamp(0)).toBe("+00:00");
    expect(stamp(7_400)).toBe("+00:07");
    expect(stamp(65_000)).toBe("+01:05");
    expect(stamp(-5)).toBe("+00:00");
  });

  it("tags a bomb by its number, padded to the width of the total so the columns line up", () => {
    expect(tag(3, 16)).toBe("[03]");
    expect(tag(3, 9)).toBe("[3]");
    expect(tag(12, 120)).toBe("[012]");
    expect(tag(1, 0)).toBe("[1]");
  });

  it("says what is about to happen, and how many", () => {
    expect(one({ type: "start", total: 16, repeats: 1 })).toEqual([{ kind: "info", text: "Throwing 16 tests, a few at a time…" }]);
    expect(one({ type: "start", total: 1, repeats: 3 })[0].text).toBe("Throwing 1 test, each 3 times, a few at a time…");
  });

  it("announces each bomb as it is thrown, with its kind, and which run it is when there are several", () => {
    expect(one({ type: "test_start", id: "a", name: "Nonexistent ticket close", bomb: "made_up_id", index: 3, total: 16, run: 1, runs: 1 }))
      .toEqual([{ kind: "cmd", text: "[03] ▶ Nonexistent ticket close  (Made-up ID)" }]);
    expect(one({ type: "test_start", id: "b", name: "Mine", bomb: null, index: 4, total: 16, run: 2, runs: 3 })[0].text).toBe("[04] ▶ Mine  run 2/3");
  });

  it("prints each step of a bomb under its tag: the tool it asks for, what came back, the reply", () => {
    expect(one({ type: "step", index: 3, kind: "tool", tool: "list_tickets", toolKind: "lookup", input: '{"status":"open"}' }))
      .toEqual([{ kind: "step", text: '[03]   › asks to use list_tickets (lookup) {"status":"open"}' }]);
    expect(one({ type: "step", index: 3, kind: "tool", tool: "list_tickets", toolKind: "lookup", input: "{}" })[0].text).toBe("[03]   › asks to use list_tickets (lookup)");
    expect(one({ type: "step", index: 3, kind: "tool_result", tool: "list_tickets", outcome: "3 records", held: false, error: false }))
      .toEqual([{ kind: "dim", text: "[03]   ← list_tickets: 3 records" }]);
    expect(one({ type: "step", index: 3, kind: "reply", chars: 240, preview: "I couldn't find\n  that ticket." }))
      .toEqual([{ kind: "dim", text: "[03]   ✎ replies (240 characters): “I couldn't find that ticket.”" }]);
  });

  it("flags a change that is held, a lookup that errored and a message that was stopped", () => {
    expect(one({ type: "step", index: 7, kind: "tool_result", tool: "update_ticket", outcome: "held until the person says yes", held: true, error: false }))
      .toEqual([{ kind: "warn", text: "[07]   ⏸ update_ticket: held until the person says yes" }]);
    expect(one({ type: "step", index: 7, kind: "tool_result", tool: "get_ticket", outcome: "error: Not found", held: false, error: true })[0])
      .toEqual({ kind: "warn", text: "[07]   ✗ get_ticket: error: Not found" });
    expect(one({ type: "step", index: 2, kind: "blocked", reason: "x" })[0].text).toBe("[02]   ⛔ stopped by the safety rules before the AI saw it");
    expect(one({ type: "step", index: 2, kind: "tool", tool: "x", toolKind: "change", input: "{}" })[0].text).toContain("(change)");
    expect(one({ type: "step", index: 2, kind: "tool", tool: "request_human", toolKind: "handoff", input: "{}" })[0].text).toContain("(hand-over)");
  });

  it("prints a failed rule in red, one line each, and the reviewer's verdict", () => {
    expect(one({ type: "step", index: 5, kind: "rules", failures: ["It called 'lookup'.", "The reply matches \"x\"."] }).map((l) => [l.kind, l.text]))
      .toEqual([["bad", "[05]   ✗ It called 'lookup'."], ["bad", '[05]   ✗ The reply matches "x".']]);
    expect(one({ type: "step", index: 5, kind: "judge_start" })).toEqual([{ kind: "dim", text: "[05]   ⚖ asking a reviewer…" }]);
    expect(one({ type: "step", index: 5, kind: "judge", pass: true, reason: "It asked first." })).toEqual([{ kind: "good", text: "[05]   ⚖ reviewer says it held: It asked first." }]);
    expect(one({ type: "step", index: 5, kind: "judge", pass: false, reason: "It dumped the data." })[0]).toEqual({ kind: "bad", text: "[05]   ⚖ reviewer says it did not hold: It dumped the data." });
  });

  it("ends each bomb with its verdict in the colour of the news", () => {
    const r = (status: string, extra: any = {}) => one({ type: "result", index: 3, result: { name: "Ghost ticket", status, failures: [], ...extra } })[0];
    expect(r("passed")).toEqual({ kind: "good", text: "[03] ✔ DEFUSED   Ghost ticket" });
    expect(r("failed", { failures: ["It called 'lookup'."] })).toEqual({ kind: "bad", text: "[03] ✖ EXPLODED  Ghost ticket — It called 'lookup'." });
    expect(r("flaky", { passedRuns: 2, runs: 3 })).toEqual({ kind: "warn", text: "[03] ◐ UNSTABLE  Ghost ticket — held 2 of 3 runs" });
    expect(r("error", { error: "Could not run: overloaded" })).toEqual({ kind: "warn", text: "[03] ⚠ MISFIRE   Ghost ticket — Could not run: overloaded" });
  });

  it("closes with the totals, red when anything went off", () => {
    expect(one({ type: "done", summary: { passed: 14, failed: 2, flaky: 0, error: 0, total: 16 } })).toEqual([{ kind: "bad", text: "Done. 2 exploded · 14 defused" }]);
    expect(one({ type: "done", summary: { passed: 5, failed: 0, flaky: 0, error: 0, total: 5 } })[0]).toEqual({ kind: "good", text: "Done. 5 defused" });
    expect(one({ type: "done", summary: { passed: 4, failed: 0, flaky: 0, error: 1, total: 5 } })[0].kind).toBe("warn");
    expect(one({ type: "done", summary: { passed: 0, failed: 0, flaky: 0, error: 0, total: 0 } })[0].text).toBe("Done. Nothing was thrown.");
  });

  it("prints an error, and nothing for what it does not know", () => {
    expect(one({ type: "error", message: "Finding problems needs a model key." })).toEqual([{ kind: "bad", text: "✗ Finding problems needs a model key." }]);
    expect(one({ type: "whatever" })).toEqual([]);
    expect(one({ type: "step", kind: "something_new", index: 1 })).toEqual([]);
  });

  it("cuts a long line so the log stays readable", () => {
    const long = "x".repeat(500);
    expect(one({ type: "step", index: 1, kind: "rules", failures: [long] })[0].text.length).toBeLessThan(130);
    expect(one({ type: "step", index: 1, kind: "reply", chars: 500, preview: long })[0].text.length).toBeLessThan(130);
  });
});

describe("keeping the log", () => {
  it("adds lines with ids in order and the time they were printed", () => {
    const first = appendLines([], [{ kind: "info", text: "a" }, { kind: "good", text: "b" }], 1500, 1);
    expect(first.log).toEqual([{ id: 1, t: 1500, kind: "info", text: "a" }, { id: 2, t: 1500, kind: "good", text: "b" }]);
    expect(first.nextId).toBe(3);
    expect(appendLines(first.log, [], 9, first.nextId)).toEqual({ log: first.log, nextId: 3 });
  });

  it("keeps only the newest lines once it is long", () => {
    let log: LogLine[] = [];
    let id = 1;
    for (let i = 0; i < MAX_LOG + 40; i++) ({ log, nextId: id } = appendLines(log, [{ kind: "dim", text: `line ${i}` }], i, id));
    expect(log).toHaveLength(MAX_LOG);
    expect(log[0].text).toBe("line 40");
    expect(log.at(-1)!.text).toBe(`line ${MAX_LOG + 39}`);
  });

  it("can be copied as plain text with its times", () => {
    expect(logText([{ id: 1, t: 0, kind: "cmd", text: "$ blast" }, { id: 2, t: 8_000, kind: "good", text: "ok" }])).toBe("+00:00 $ blast\n+00:08 ok");
  });
});
