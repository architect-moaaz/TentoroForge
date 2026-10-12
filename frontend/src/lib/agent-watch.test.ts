import { describe, it, expect } from "vitest";
import { applyWatch, checklist, edgeLook, followLatest, initialWatch, nodeRing, nodeStates, selectRun, stageOf, type FlowMap, type WatchState } from "./agent-watch";
import type { LiveEvent } from "./agent-live";

const MAP: FlowMap = {
  tools: { list_tickets: "tool-list", update_ticket: "tool-update" },
  kinds: { system_prompt: ["sp"], guardrail: ["guard"], memory: ["mem"], human_handoff: ["hand"] },
};
const ev = (e: LiveEvent): LiveEvent => ({ runId: "r1", t: 1, ...e });
const play = (events: LiveEvent[], from: WatchState = { ...initialWatch(), map: MAP }) => events.reduce((s, e) => applyWatch(s, e, 1000), from);
const only = (s: WatchState, id = "r1") => s.runs[id];

const START = ev({ type: "run_start", agentId: "app_assistant", agentName: "Assistant", user: { id: "u1", name: "Lena", role: "Support", email: null }, message: "how many open tickets?", conversationId: null });
const CHECKS = [ev({ type: "phase", phase: "input_check", ok: true }), ev({ type: "phase", phase: "memory", messages: 0, summarised: false })];
const startOf = (id: string, name: string) => ({ runId: id, t: 1, type: "run_start", agentId: "a", agentName: "A", user: { id: "u", name, role: null, email: null }, message: "m", conversationId: null });
const callStart = (n: number) => ev({ type: "model_start", n, messages: 1, tools: 2, systemChars: 1 });

describe("the connection", () => {
  it("is ready when the app says hello, and carries the map the platform sent", () => {
    const s = play([{ type: "platform_map", ...MAP }, { type: "watch_ready", agents: [{ id: "app_assistant", name: "Assistant" }] }], initialWatch());
    expect(s.ready).toBe(true);
    expect(s.map).toEqual({ ...MAP, toolInfo: {} });
    expect(s.agents[0].name).toBe("Assistant");
  });

  it("does not warn about a tool call when it knows nothing of the tool (no bogus 'unknown tool')", () => {
    const s = play([START, ev({ type: "tool_call", id: "c", tool: "list_tickets", input: { status: "open" } })], { ...initialWatch(), map: MAP });
    expect((only(s).live.steps[0] as any).problems).toEqual([]);
  });

  it("checks a tool call against the tool as drawn, when the platform sent its definition", () => {
    const withInfo = { ...initialWatch(), map: { ...MAP, toolInfo: { update_ticket: { inputSchema: { type: "object", properties: { id: { type: "string" }, data: { type: "object" } }, required: ["id", "data"], additionalProperties: true } } } } };
    const s = play([START, ev({ type: "tool_call", id: "c", tool: "update_ticket", input: { id: "t-1" } })], withInfo);
    expect((only(s).live.steps[0] as any).problems.map((p: any) => [p.code, p.field])).toEqual([["missing", "data"], ["unseen_id", "id"]]);
    const other = play([START, ev({ type: "tool_call", id: "c", tool: "list_tickets", input: {} })], withInfo);
    expect((only(other).live.steps[0] as any).problems).toEqual([]);
  });

  it("knows whose chats the app says it is sending: everyone's, a role's, or one person's", () => {
    expect(play([{ type: "watch_ready", agents: [] }], initialWatch()).who).toEqual({});
    expect(play([{ type: "watch_ready", agents: [], filter: { role: "Admin" } }], initialWatch()).who).toEqual({ role: "Admin" });
    expect(play([{ type: "watch_ready", agents: [], filter: { userId: "u-1" } }], initialWatch()).who).toEqual({ userId: "u-1" });
  });

  it("says why when it cannot connect, and is no longer ready", () => {
    const s = play([{ type: "watch_ready", agents: [] }, { type: "error", message: "Could not reach the app" }], initialWatch());
    expect(s).toMatchObject({ ready: false, error: "Could not reach the app" });
  });

  it("an error inside a chat belongs to that chat, not to the connection", () => {
    const s = play([START, ev({ type: "error", message: "model overloaded" })]);
    expect(s.error).toBeUndefined();
    expect(only(s).live.status).toBe("error");
  });
});

describe("tracking chats", () => {
  it("starts a chat at its first event, with who and what", () => {
    const s = play([START]);
    expect(s.order).toEqual(["r1"]);
    expect(s.selected).toBe("r1");
    expect(only(s)).toMatchObject({ agentName: "Assistant", finished: false });
    expect(only(s).live).toMatchObject({ message: "how many open tickets?", user: { name: "Lena" }, status: "running" });
  });

  it("finishes on done, blocked or error", () => {
    expect(only(play([START, ev({ type: "done", conversationId: "c" })])).finished).toBe(true);
    expect(only(play([START, ev({ type: "blocked", stage: "input", reason: "Too long" })])).finished).toBe(true);
    expect(only(play([START, ev({ type: "error", message: "x" })])).finished).toBe(true);
  });

  it("follows the newest chat, until the builder picks an older one", () => {
    let s = play([START, ev({ type: "done" }), startOf("r2", "Pat")]);
    expect(s.order).toEqual(["r2", "r1"]);
    expect(s.selected).toBe("r2");
    s = selectRun(s, "r1");
    expect(s).toMatchObject({ selected: "r1", follow: false });
    s = play([startOf("r3", "Sam")], s);
    expect(s.selected).toBe("r1");
    s = followLatest(s);
    expect(s).toMatchObject({ selected: "r3", follow: true });
  });

  it("keeps only the latest chats", () => {
    let s = initialWatch();
    for (let i = 0; i < 40; i++) s = applyWatch(s, startOf(`r${i}`, "x"));
    expect(s.order).toHaveLength(30);
    expect(Object.keys(s.runs)).toHaveLength(30);
    expect(s.order[0]).toBe("r39");
  });

  it("ignores an event that belongs to no chat", () => {
    expect(play([{ type: "text", content: "x" }]).order).toEqual([]);
  });
});

describe("which boxes are lit", () => {
  it("lights the guardrail and memory boxes as the checks pass, then the AI box while it is called", () => {
    const early = play([START, ev({ type: "phase", phase: "input_check", ok: true })]);
    expect(nodeStates(only(early), MAP)).toEqual({ guard: "done" });
    const calling = play([...CHECKS, callStart(1)], early);
    expect(nodeStates(only(calling), MAP)).toEqual({ guard: "done", mem: "done", sp: "active" });
  });

  it("moves to the tool the AI chose while it runs, then marks it done and moves on", () => {
    const running = play([START, ...CHECKS, callStart(1),
      ev({ type: "model_call", n: 1, ms: 10, inputTokens: 1, outputTokens: 1, messages: 1, toolsRequested: ["list_tickets"] }),
      ev({ type: "tool_call", id: "c1", tool: "list_tickets", input: {} })]);
    expect(nodeStates(only(running), MAP)).toMatchObject({ sp: "done", "tool-list": "active" });
    const after = play([ev({ type: "tool_result", id: "c1", tool: "list_tickets", ok: true, result: {} }), callStart(2)], running);
    expect(nodeStates(only(after), MAP)).toMatchObject({ "tool-list": "done", sp: "active" });
  });

  it("shows a failed tool red, a held change amber, and a chat with a person on the handoff box", () => {
    const failed = play([START, ev({ type: "tool_call", id: "c1", tool: "list_tickets", input: {} }), ev({ type: "tool_result", id: "c1", tool: "list_tickets", ok: false, error: "x" })]);
    expect(nodeStates(only(failed), MAP)["tool-list"]).toBe("failed");
    const held = play([START, ev({ type: "tool_call", id: "c2", tool: "update_ticket", input: {} }), ev({ type: "tool_result", id: "c2", tool: "update_ticket", ok: true, result: { held: true } })]);
    expect(nodeStates(only(held), MAP)["tool-update"]).toBe("held");
    const person = play([START, ev({ type: "phase", phase: "with_person", ref: "HO-1" })]);
    expect(nodeStates(only(person), MAP).hand).toBe("held");
    const handoff = play([START, ev({ type: "tool_call", id: "c3", tool: "request_human", input: {} })]);
    expect(nodeStates(only(handoff), MAP).hand).toBe("active");
  });

  it("marks a failed check red, and finishes with nothing still lit", () => {
    const refused = play([START, ev({ type: "phase", phase: "input_check", ok: false, reason: "Too long" }), ev({ type: "blocked", stage: "input", reason: "Too long" })]);
    expect(nodeStates(only(refused), MAP)).toEqual({ guard: "failed" });
    const broke = play([START, callStart(1), ev({ type: "error", message: "boom" })]);
    expect(nodeStates(only(broke), MAP).sp).toBe("failed");
    const over = play([START, ev({ type: "tool_call", id: "c", tool: "list_tickets", input: {} }), ev({ type: "done", conversationId: "c" })]);
    expect(Object.values(nodeStates(only(over), MAP)).includes("active")).toBe(false);
  });

  it("lights nothing without a map, and ignores a tool it has no box for", () => {
    expect(nodeStates(only(play([START, ev({ type: "phase", phase: "input_check", ok: true })], initialWatch())), undefined)).toEqual({});
    expect(nodeStates(only(play([START, ev({ type: "tool_call", id: "c", tool: "mystery", input: {} })])), MAP)).toEqual({});
  });

  it("draws rings by state and arrows by how the chat passed along them", () => {
    expect(nodeRing("active")).toContain("animate-pulse");
    expect(nodeRing("done")).toContain("green");
    expect(nodeRing("failed")).toContain("red");
    expect(nodeRing("held")).toContain("amber");
    expect(nodeRing(undefined)).toBeUndefined();
    expect(edgeLook("done", "active")).toMatchObject({ animated: true });
    expect(edgeLook("done", "done")).toMatchObject({ animated: false, stroke: "#22c55e" });
    expect(edgeLook("done", "failed")).toMatchObject({ stroke: "#ef4444" });
    expect(edgeLook(undefined, "done")).toEqual({ animated: false });
  });
});

describe("the checklist", () => {
  const chose = (names: string[], n = 1) => [callStart(n), ev({ type: "model_call", n, ms: 1, inputTokens: 1, outputTokens: 1, messages: 1, toolsRequested: names })];

  it("appears the moment the AI chooses, every item waiting", () => {
    const g = checklist(only(play([START, ...chose(["list_tickets", "update_ticket"])])).live);
    expect(g).toEqual([{ step: 1, items: [{ tool: "list_tickets", status: "waiting" }, { tool: "update_ticket", status: "waiting" }] }]);
  });

  it("is not there while the AI is still thinking, or when it chose nothing", () => {
    expect(checklist(only(play([START, callStart(1)])).live)).toEqual([]);
    expect(checklist(only(play([START, ...chose([])])).live)).toEqual([]);
  });

  it("ticks off as each tool runs and finishes, in order", () => {
    const mid = play([START, ...chose(["list_tickets", "update_ticket"]),
      ev({ type: "tool_call", id: "c1", tool: "list_tickets", input: {}, t: 300 }),
      ev({ type: "tool_result", id: "c1", tool: "list_tickets", ok: true, result: {}, t: 301 }),
      ev({ type: "tool_call", id: "c2", tool: "update_ticket", input: {}, t: 302 })]);
    const items = checklist(only(mid).live)[0].items;
    expect(items[0]).toMatchObject({ tool: "list_tickets", status: "ok" });
    expect(items[0].ms).toBe(1);
    expect(items[1]).toMatchObject({ tool: "update_ticket", status: "running" });
  });

  it("keeps a group for each time the AI asked for tools", () => {
    const s = play([START, ...chose(["list_tickets"], 1),
      ev({ type: "tool_call", id: "c1", tool: "list_tickets", input: {} }),
      ev({ type: "tool_result", id: "c1", tool: "list_tickets", ok: true, result: {} }),
      ...chose(["update_ticket"], 2),
      ev({ type: "tool_call", id: "c2", tool: "update_ticket", input: {} })]);
    const g = checklist(only(s).live);
    expect(g.map((x) => [x.step, x.items.map((i) => [i.tool, i.status])])).toEqual([[1, [["list_tickets", "ok"]]], [2, [["update_ticket", "running"]]]]);
  });

  it("shows the same tool asked for twice as two items, each matched to its own call", () => {
    const s = play([START, ...chose(["list_tickets", "list_tickets"]),
      ev({ type: "tool_call", id: "a", tool: "list_tickets", input: { page: 1 } }),
      ev({ type: "tool_result", id: "a", tool: "list_tickets", ok: true, result: {} }),
      ev({ type: "tool_call", id: "b", tool: "list_tickets", input: { page: 2 } })]);
    expect(checklist(only(s).live)[0].items.map((i) => i.status)).toEqual(["ok", "running"]);
  });
});

describe("where the chat has got to", () => {
  const stage = (events: LiveEvent[]) => stageOf(only(play(events)));
  const call = ev({ type: "tool_call", id: "c", tool: "list_tickets", input: {} });

  it("reads as a short sentence at every point", () => {
    expect(stage([START])).toBe("Message received");
    expect(stage([START, CHECKS[0]])).toBe("Checking the message");
    expect(stage([START, ...CHECKS])).toBe("Memory loaded");
    expect(stage([START, ...CHECKS, callStart(1)])).toBe("Calling the AI (call 1)");
    expect(stage([START, callStart(1), ev({ type: "model_call", n: 1, ms: 1, inputTokens: 1, outputTokens: 1, messages: 1, toolsRequested: ["list_tickets"] })])).toBe("The AI chose: list_tickets");
    expect(stage([START, call])).toBe("Running list_tickets");
    expect(stage([START, call, ev({ type: "tool_result", id: "c", tool: "list_tickets", ok: true, result: {} })])).toBe("Reading the result");
    expect(stage([START, ev({ type: "done" })])).toBe("Answer sent");
    expect(stage([START, ev({ type: "blocked", stage: "input", reason: "Too long" })])).toBe("Refused: Too long");
    expect(stage([START, ev({ type: "error", message: "boom" })])).toBe("Failed: boom");
    expect(stage([START, ev({ type: "phase", phase: "with_person", ref: "HO-1" })])).toContain("With a person");
  });
});
