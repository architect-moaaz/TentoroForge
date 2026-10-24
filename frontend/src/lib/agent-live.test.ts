import { describe, it, expect } from "vitest";
import { applyEvent, checkInput, emptyRun, parseEvents, rowsOf, type LiveEvent, type LiveRun, type ToolInfo } from "./agent-live";

const tool = (over: Partial<ToolInfo> & { name: string }): ToolInfo => ({
  inputSchema: { type: "object", properties: {}, additionalProperties: true }, ...over,
});

const getTicket = tool({ name: "get_ticket", inputSchema: { type: "object", properties: { id: { type: "string" } }, required: ["id"], additionalProperties: true } });
const setTicket = tool({
  name: "update_ticket",
  inputSchema: { type: "object", properties: { id: { type: "string" }, data: { type: "object" }, count: { type: "number" } }, required: ["id", "data"], additionalProperties: false },
});

/** A chat that has just begun, whose person has said this much so far. */
const begin = (said: string, tools?: ToolInfo[]): LiveRun => ({ ...emptyRun(), status: "running", seen: said, ...(tools ? { tools } : {}) });
const play = (events: LiveEvent[], from: LiveRun = emptyRun()) => events.reduce(applyEvent, from);

describe("checkInput", () => {
  it("says nothing when the input is fine and its id was seen", () => {
    expect(checkInput(getTicket, { id: "abc-123" }, "close ticket abc-123")).toEqual([]);
  });

  it("flags an id that came from nowhere, naming the field", () => {
    const p = checkInput(getTicket, { id: "1" }, "close the oldest ticket");
    expect(p).toHaveLength(1);
    expect(p[0]).toMatchObject({ code: "unseen_id", field: "id" });
    expect(p[0].message).toContain("may have been made up");
  });

  it("finds ids by their name, nested too (customerId, record_id, data.ownerId)", () => {
    const p = checkInput(setTicket, { id: "t1", data: { ownerId: "zzz", note: "x" } }, "t1");
    expect(p.map((x) => x.field)).toEqual(["data.ownerId"]);
    expect(checkInput(tool({ name: "x" }), { customerId: "c9", record_id: "r9" }, "").map((x) => x.field)).toEqual(["customerId", "record_id"]);
  });

  it("flags missing required fields, empty counts as missing", () => {
    const p = checkInput(setTicket, { id: "", count: 2 }, "");
    expect(p.filter((x) => x.code === "missing").map((x) => x.field)).toEqual(["id", "data"]);
  });

  it("flags a field the tool does not accept only when it says so, and a wrong type", () => {
    expect(checkInput(setTicket, { id: "t", data: {}, bogus: 1 }, "t").map((x) => x.code)).toEqual(["unexpected"]);
    expect(checkInput(getTicket, { id: "t", bogus: 1 }, "t")).toEqual([]);
    const typed = checkInput(setTicket, { id: "t", data: {}, count: "two" }, "t");
    expect(typed).toHaveLength(1);
    expect(typed[0]).toMatchObject({ code: "wrong_type", field: "count" });
    expect(typed[0].message).toContain("should be number");
  });

  it("does not claim a tool is unknown when its definition is not available: only the id check runs", () => {
    expect(checkInput(undefined, { id: "seen-1", extra: true }, "seen-1")).toEqual([]);
    expect(checkInput(undefined, { id: "made-up" }, "nothing").map((x) => x.code)).toEqual(["unseen_id"]);
  });
});

describe("the chat, step by step", () => {
  it("puts the model's words under the call they came with, and its tool calls after it", () => {
    const run = play([
      { type: "text", t: 10, content: "Let me look. " },
      { type: "model_call", t: 3000, n: 1, ms: 2990, inputTokens: 500, outputTokens: 40, messages: 1, toolsRequested: ["get_ticket"] },
      { type: "tool_call", t: 3001, id: "c1", tool: "get_ticket", input: { id: "abc" } },
      { type: "tool_result", t: 3400, id: "c1", tool: "get_ticket", ok: true, result: { id: "abc", status: "open" }, chars: 30, cut: false },
      { type: "text", t: 3500, content: "It is open." },
      { type: "model_call", t: 5000, n: 2, ms: 1500, inputTokens: 600, outputTokens: 10, messages: 3, toolsRequested: [] },
      { type: "done", t: 5001, conversationId: "conv-1" },
    ], begin("what is the status of ticket abc", [getTicket]));
    expect(run.steps.map((s) => s.kind)).toEqual(["model", "tool", "model"]);
    expect((run.steps[0] as any).said).toBe("Let me look.");
    expect((run.steps[2] as any).said).toBe("It is open.");
    expect(run.steps[1]).toMatchObject({ tool: "get_ticket", status: "ok", ms: 399, problems: [] });
    expect(run).toMatchObject({ status: "done", conversationId: "conv-1", answer: "Let me look. It is open." });
    expect(run.totals).toEqual({ ms: 5001, inputTokens: 1100, outputTokens: 50, modelCalls: 2, toolCalls: 1 });
  });

  it("notes who wrote what when the chat begins, and what was said counts as seen", () => {
    const run = play([{ type: "run_start", t: 0, user: { id: "u1", name: "Lena", email: null, role: "Support" }, message: "close ticket t-9", conversationId: "c1" }]);
    expect(run).toMatchObject({ message: "close ticket t-9", user: { name: "Lena" }, conversationId: "c1" });
    expect(run.seen).toContain("close ticket t-9");
  });

  it("shows a call to the AI as working while it is, then finishes that same card", () => {
    const working = play([{ type: "model_start", t: 5, n: 1, messages: 1, tools: 26, systemChars: 3150 }], begin("hi"));
    expect(working.steps).toHaveLength(1);
    expect(working.steps[0]).toMatchObject({ kind: "model", n: 1, running: true, tools: 26, systemChars: 3150, messages: 1 });
    const finished = play([
      { type: "text", t: 6, content: "Hello" },
      { type: "model_call", t: 900, n: 1, ms: 895, inputTokens: 10, outputTokens: 2, messages: 1, toolsRequested: [] },
    ], working);
    expect(finished.steps).toHaveLength(1);
    expect(finished.steps[0]).toMatchObject({ n: 1, ms: 895, said: "Hello", tools: 26, systemChars: 3150 });
    expect((finished.steps[0] as any).running).toBeFalsy();
  });

  it("marks a call to the AI that failed, with why", () => {
    const run = play([
      { type: "model_start", t: 1, n: 1, messages: 1, tools: 2, systemChars: 10 },
      { type: "model_failed", t: 50, n: 1, ms: 49, error: "overloaded" },
    ], begin("hi"));
    expect(run.steps[0]).toMatchObject({ running: false, failed: "overloaded", ms: 49 });
  });

  it("keeps the runtime's own steps in order", () => {
    const run = play([
      { type: "phase", t: 1, phase: "input_check", ok: true },
      { type: "phase", t: 2, phase: "memory", messages: 3, summarised: false },
      { type: "phase", t: 9, phase: "output_check", ok: false, reason: "Blocked" },
    ], begin("hi"));
    expect(run.phases.map((p) => [p.phase, p.ok, p.t])).toEqual([["input_check", true, 1], ["memory", undefined, 2], ["output_check", false, 9]]);
    expect(run.phases[1]).toMatchObject({ messages: 3, summarised: false });
    expect(run.phases[2].reason).toBe("Blocked");
  });

  it("marks a change the app is holding as held", () => {
    const held = play([
      { type: "tool_call", t: 1, id: "c1", tool: "update_ticket", input: { id: "t", data: {} } },
      { type: "tool_result", t: 2, id: "c1", tool: "update_ticket", ok: true, result: { held: true, needs_confirmation: true } },
    ], begin("t"));
    expect(held.steps[0]).toMatchObject({ status: "held" });
  });

  it("marks a failed tool with its error", () => {
    const run = play([
      { type: "tool_call", t: 1, id: "c1", tool: "get_ticket", input: { id: "1" } },
      { type: "tool_result", t: 9, id: "c1", tool: "get_ticket", ok: false, error: "Not found" },
    ], begin("x"));
    expect(run.steps[0]).toMatchObject({ status: "failed", error: "Not found", ms: 8 });
  });

  it("attaches what a tool did in the app to that tool, in order, with the real method and status", () => {
    const run = play([
      { type: "tool_call", t: 1, id: "c1", tool: "get_ticket", input: { id: "t" } },
      { type: "app_call", t: 2, kind: "request", label: "/api/data/tickets/t", method: "GET", status: 200, ms: 120, ok: true },
      { type: "app_call", t: 3, kind: "request", label: "/api/data/users/u", method: "GET", status: 403, ms: 30, ok: false, error: "Not allowed" },
      { type: "tool_result", t: 4, id: "c1", tool: "get_ticket", ok: true, result: {} },
    ], begin("t"));
    const calls = (run.steps[0] as any).calls;
    expect(calls.map((c: any) => [c.method, c.label, c.status, c.ok])).toEqual([["GET", "/api/data/tickets/t", 200, true], ["GET", "/api/data/users/u", 403, false]]);
    expect(calls[1].error).toBe("Not allowed");
    expect(calls[0]).not.toHaveProperty("type");
    expect(calls[0]).not.toHaveProperty("t");
  });

  it("ignores a call that belongs to no running tool", () => {
    expect(play([{ type: "app_call", t: 1, kind: "request", label: "/x", method: "GET", ms: 1, ok: true }]).steps).toEqual([]);
  });

  it("warns about an id the data never showed, and stops warning once an earlier result showed it", () => {
    const first = play([{ type: "tool_call", t: 1, id: "c1", tool: "get_ticket", input: { id: "t-77" } }], begin("show me the oldest ticket"));
    expect((first.steps[0] as any).problems[0]).toMatchObject({ code: "unseen_id" });

    const second = play([
      { type: "tool_call", t: 1, id: "c1", tool: "list", input: {} },
      { type: "tool_result", t: 2, id: "c1", tool: "list", ok: true, result: { data: [{ id: "t-77" }] }, chars: 20 },
      { type: "tool_call", t: 3, id: "c2", tool: "get_ticket", input: { id: "t-77" } },
    ], begin("show me the oldest ticket"));
    expect((second.steps[1] as any).problems).toEqual([]);
  });

  it("checks an input against the tool as drawn, when it is known", () => {
    const run = play([{ type: "tool_call", t: 1, id: "c1", tool: "update_ticket", input: { id: "t", data: {}, bogus: 1 } }], begin("t", [setTicket]));
    expect((run.steps[0] as any).problems.map((p: any) => p.code)).toEqual(["unexpected"]);
    const unknown = play([{ type: "tool_call", t: 1, id: "c1", tool: "something_else", input: { id: "t" } }], begin("t", [setTicket]));
    expect((unknown.steps[0] as any).problems).toEqual([]);
  });

  it("carries a refusal and an error", () => {
    expect(play([{ type: "blocked", t: 1, stage: "input", reason: "Too long" }], begin("x"))).toMatchObject({ status: "blocked", blocked: "Too long" });
    expect(play([{ type: "error", t: 1, message: "The model call failed" }], begin("x"))).toMatchObject({ status: "error", error: "The model call failed" });
  });

  it("does not lose the words of a chat that stopped before its next model call", () => {
    const run = play([
      { type: "model_call", t: 5, n: 1, ms: 5, inputTokens: 1, outputTokens: 1, messages: 1, toolsRequested: [] },
      { type: "text", t: 6, content: "Late words" },
      { type: "error", t: 7, message: "boom" },
    ], begin("x"));
    expect((run.steps[0] as any).said).toBe("Late words");
  });
});

describe("parseEvents", () => {
  it("returns whole events and keeps the rest for the next chunk", () => {
    const a = parseEvents('data: {"type":"text","content":"he"}\n\ndata: {"type":"te');
    expect(a.events).toEqual([{ type: "text", content: "he" }]);
    const b = parseEvents(a.rest + 'xt","content":"llo"}\n\n');
    expect(b.events).toEqual([{ type: "text", content: "llo" }]);
    expect(b.rest).toBe("");
  });

  it("skips what is not an event", () => {
    expect(parseEvents(': ping\n\ndata: not json\n\ndata: {"type":"done"}\n\n').events).toEqual([{ type: "done" }]);
  });
});

describe("rowsOf", () => {
  it("finds a list of records however the tool wrapped it", () => {
    expect(rowsOf({ data: [{ a: 1 }, { a: 2 }] })).toHaveLength(2);
    expect(rowsOf([{ a: 1 }])).toHaveLength(1);
    expect(rowsOf({ rows: [{ a: 1 }] })).toHaveLength(1);
  });
  it("says no for anything else", () => {
    expect(rowsOf({ id: "1" })).toBeNull();
    expect(rowsOf({ data: [] })).toBeNull();
    expect(rowsOf({ data: [1, 2] })).toBeNull();
    expect(rowsOf("text")).toBeNull();
  });
});
