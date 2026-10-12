/**
 * A REAL run, captured from ResolveDesk's chat while a watcher was connected, replayed through the screen's logic one
 * event at a time (src/lib/__fixtures__/watch-real-run.json: the platform's real box map for that agent, then every
 * event the app sent).
 *
 * The other tests use events written by hand. This one pins that the screen understands what the app REALLY sends,
 * and that the animation tells the story in the right order: message in, checks, the AI called, the tools it chose,
 * each tool running then done, the AI again, the answer.
 */
import { describe, it, expect } from "vitest";
import fixture from "./__fixtures__/watch-real-run.json";
import { applyWatch, checklist, initialWatch, nodeStates, stageOf, type WatchState } from "./agent-watch";
import type { LiveEvent } from "./agent-live";

const events = fixture.events as LiveEvent[];
const map = fixture.map as LiveEvent;

const after = (n: number): WatchState => {
  let s = applyWatch(initialWatch(), map);
  for (const e of events.slice(0, n)) s = applyWatch(s, e, 1000);
  return s;
};
const run = (s: WatchState) => s.runs[s.order[0]];

describe("a real run, replayed", () => {
  it("is understood as one finished chat, from who asked what to the reply", () => {
    const s = after(events.length);
    expect(s.ready).toBe(true);
    expect(s.order).toHaveLength(1);
    const r = run(s);
    expect(r.finished).toBe(true);
    expect(r.live.status).toBe("done");
    expect(r.live.user?.name).toBeTruthy();
    expect(r.live.message).toContain("open tickets");
    expect(r.live.answer).toContain("open tickets");
    expect(r.live.steps.map((x) => x.kind)).toEqual(["model", "tool", "model"]);
    expect(r.live.phases.map((p) => p.phase)).toEqual(["input_check", "memory", "output_check"]);
    expect(r.live.totals.modelCalls).toBe(2);
    expect(r.live.totals.toolCalls).toBe(1);
  });

  it("shows the real request behind the tool, with its method, route and status", () => {
    const tool = run(after(events.length)).live.steps.find((x) => x.kind === "tool") as any;
    expect(tool.tool).toBe("list_tickets");
    expect(tool.calls).toHaveLength(1);
    expect(tool.calls[0]).toMatchObject({ kind: "request", method: "GET", label: "/api/data/tickets", status: 200, ok: true });
    expect(tool.status).toBe("ok");
    expect(tool.chars).toBeGreaterThan(0);
    expect(tool.result).toBeTruthy();
  });

  it("checks the real tool call against the tool as drawn, and finds nothing wrong with a good one", () => {
    const r = run(after(events.length));
    expect(r.live.tools?.length).toBeGreaterThan(20);
    const tool = r.live.steps.find((x) => x.kind === "tool") as any;
    expect(tool.problems, JSON.stringify(tool.problems)).toEqual([]);
    expect(Object.keys((fixture.map as any).toolInfo)).toContain("list_tickets");
  });

  it("ends with every box the chat touched green and nothing still lit", () => {
    const s = after(events.length);
    const states = nodeStates(run(s), s.map);
    expect(Object.values(states).length).toBeGreaterThanOrEqual(4);
    expect(Object.values(states).every((v) => v === "done")).toBe(true);
    expect(states[map.tools.list_tickets]).toBe("done");
    expect(states[map.kinds.guardrail[0]]).toBe("done");
    expect(states[map.kinds.memory[0]]).toBe("done");
    expect(states[map.kinds.system_prompt[0]]).toBe("done");
  });

  it("makes the checklist as soon as the AI chooses, and ticks it off when the tool finishes", () => {
    const chosenAt = events.findIndex((e) => e.type === "model_call" && (e.toolsRequested as string[]).length > 0) + 1;
    const atChoice = checklist(run(after(chosenAt)).live);
    expect(atChoice).toHaveLength(1);
    expect(atChoice[0].items.map((i) => [i.tool, i.status])).toEqual([["list_tickets", "waiting"]]);
    expect(checklist(run(after(events.length)).live)[0].items[0]).toMatchObject({ tool: "list_tickets", status: "ok" });
  });

  it("tells the story in order as the events arrive", () => {
    const stages: string[] = [];
    const lit: string[][] = [];
    for (let i = 1; i <= events.length; i++) {
      const s = after(i);
      if (!s.order.length) continue;
      const stage = stageOf(run(s));
      if (stages[stages.length - 1] !== stage) {
        stages.push(stage);
        lit.push(Object.entries(nodeStates(run(s), s.map)).filter(([, v]) => v === "active").map(([k]) => k));
      }
    }
    const want = ["Message received", "Checking the message", "Memory loaded", "Calling the AI (call 1)", "The AI chose: list_tickets", "Running list_tickets", "Reading the result", "Calling the AI (call 2)", "Answer sent"];
    let at = -1;
    for (const w of want) {
      const found = stages.indexOf(w, at + 1);
      expect(found, `"${w}" should come after the one before it; got: ${stages.join(" > ")}`).toBeGreaterThan(at);
      at = found;
    }
    // the box that is pulsing moves with the story: the AI's box while it is called, the tool's box while it runs
    expect(lit[stages.indexOf("Calling the AI (call 1)")]).toEqual(map.kinds.system_prompt);
    expect(lit[stages.indexOf("Running list_tickets")]).toEqual([map.tools.list_tickets]);
    expect(lit[stages.indexOf("Answer sent")]).toEqual([]);
  });

  it("never throws, whatever point the stream is cut at", () => {
    for (let i = 0; i <= events.length; i++) {
      const s = after(i);
      if (s.order.length) {
        const r = run(s);
        expect(() => { nodeStates(r, s.map); checklist(r.live); stageOf(r); }).not.toThrow();
      }
    }
  });
});
