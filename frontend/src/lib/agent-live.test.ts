import { describe, it, expect } from "vitest";
import { applyEvent, beginRun, checkInput, emptyRun, parseEvents, rowsOf, type AgentInfo, type LiveEvent, type LiveRun, type ToolInfo } from "./agent-live";

const tool = (over: Partial<ToolInfo> & { name: string }): ToolInfo => ({
  kind: "data", description: "d", confirm: false, changes: false,
  inputSchema: { type: "object", properties: {}, additionalProperties: true }, ...over,
});

const getTicket = tool({ name: "get_ticket", inputSchema: { type: "object", properties: { id: { type: "string" } }, required: ["id"], additionalProperties: true } });
const setTicket = tool({
  name: "update_ticket", changes: true, confirm: true,
  inputSchema: { type: "object", properties: { id: { type: "string" }, data: { type: "object" }, count: { type: "number" } }, required: ["id", "data"], additionalProperties: false },
});
const agent: AgentInfo = { id: "a", name: "A", model: null, systemPrompt: "You help.", maxTurns: 4, tools: [getTicket, setTicket] };

const play = (events: LiveEvent[], from: LiveRun = emptyRun()) => events.reduce(applyEvent, from);
const start: LiveEvent = { type: "debug_start", t: 0, agent, user: { id: "u1", name: "Lena", email: null, role: "Support" }, allowChanges: false, draft: true };

describe("checkInput", () => {
  it("says nothing when the input is fine and its id was seen", () => {
    expect(checkInput(getTicket, "get_ticket", { id: "abc-123" }, "close ticket abc-123")).toEqual([]);
  });

  it("flags an id that came from nowhere, naming the field", () => {
    const p = checkInput(getTicket, "get_ticket", { id: "1" }, "close the oldest ticket");
    expect(p).toHaveLength(1);
    expect(p[0]).toMatchObject({ code: "unseen_id", field: "id" });
    expect(p[0].message).toContain("may have been made up");
  });

  it("finds ids by their name, nested too (customerId, record_id, data.ownerId)", () => {
    const p = checkInput(setTicket, "update_ticket", { id: "t1", data: { ownerId: "zzz", note: "x" } }, "t1");
    expect(p.map((x) => x.field)).toEqual(["data.ownerId"]);
    expect(checkInput(tool({ name: "x" }), "x", { customerId: "c9", record_id: "r9" }, "").map((x) => x.field)).toEqual(["customerId", "record_id"]);
  });

  it("flags missing required fields, empty counts as missing", () => {
    const p = checkInput(setTicket, "update_ticket", { id: "", count: 2 }, "");
    expect(p.filter((x) => x.code === "missing").map((x) => x.field)).toEqual(["id", "data"]);
  });

  it("flags a field the tool does not accept only when it says so, and a wrong type", () => {
    expect(checkInput(setTicket, "update_ticket", { id: "t", data: {}, bogus: 1 }, "t").map((x) => x.code)).toEqual(["unexpected"]);
    expect(checkInput(getTicket, "get_ticket", { id: "t", bogus: 1 }, "t")).toEqual([]);
    const typed = checkInput(setTicket, "update_ticket", { id: "t", data: {}, count: "two" }, "t");
    expect(typed).toHaveLength(1);
    expect(typed[0]).toMatchObject({ code: "wrong_type", field: "count" });
    expect(typed[0].message).toContain("should be number");
  });

  it("flags a tool the agent does not have", () => {
    expect(checkInput(undefined, "nope", {}, "")[0]).toMatchObject({ code: "unknown_tool" });
  });
});

describe("the run, step by step", () => {
  it("puts the model's words under the call they came with, and its tool calls after it", () => {
    const run = play([
      start,
      { type: "text", t: 10, content: "Let me look. " },
      { type: "model_call", t: 3000, n: 1, ms: 2990, inputTokens: 500, outputTokens: 40, messages: 1, toolsRequested: ["get_ticket"] },
      { type: "tool_call", t: 3001, id: "c1", tool: "get_ticket", input: { id: "abc" } },
      { type: "tool_result", t: 3400, id: "c1", tool: "get_ticket", ok: true, result: { id: "abc", status: "open" }, chars: 30, cut: false },
      { type: "text", t: 3500, content: "It is open." },
      { type: "model_call", t: 5000, n: 2, ms: 1500, inputTokens: 600, outputTokens: 10, messages: 3, toolsRequested: [] },
      { type: "done", t: 5001, conversationId: "conv-1" },
    ], beginRun(emptyRun(), "what is the status of ticket abc"));
    expect(run.steps.map((s) => s.kind)).toEqual(["model", "tool", "model"]);
    expect((run.steps[0] as any).said).toBe("Let me look.");
    expect((run.steps[2] as any).said).toBe("It is open.");
    const t = run.steps[1] as any;
    expect(t).toMatchObject({ tool: "get_ticket", status: "ok", ms: 399, problems: [] });
    expect(run).toMatchObject({ status: "done", conversationId: "conv-1", answer: "Let me look. It is open." });
    expect(run.totals).toEqual({ ms: 5001, inputTokens: 1100, outputTokens: 50, modelCalls: 2, toolCalls: 1 });
  });

  it("shows who it ran as and the prompt and tools the agent was given", () => {
    const run = play([start]);
    expect(run.user?.name).toBe("Lena");
    expect(run.agent?.systemPrompt).toBe("You help.");
    expect(run.draft).toBe(true);
  });

  it("marks a tool that changes data as not run, with why, and one the app is holding as held", () => {
    const notRun = play([
      start,
      { type: "tool_call", t: 1, id: "c1", tool: "update_ticket", input: { id: "t", data: {} } },
      { type: "tool_faked", t: 2, tool: "update_ticket", reason: "it changes data" },
      { type: "tool_result", t: 3, id: "c1", tool: "update_ticket", ok: true, result: { ok: true, debug_note: "Not run" } },
    ], beginRun(emptyRun(), "t"));
    expect(notRun.steps[0]).toMatchObject({ status: "not_run", notRunReason: "it changes data" });

    const held = play([
      start,
      { type: "tool_call", t: 1, id: "c1", tool: "update_ticket", input: { id: "t", data: {} } },
      { type: "tool_result", t: 2, id: "c1", tool: "update_ticket", ok: true, result: { held: true, needs_confirmation: true } },
    ], beginRun(emptyRun(), "t"));
    expect(held.steps[0]).toMatchObject({ status: "held" });
  });

  it("marks a failed tool with its error", () => {
    const run = play([
      start,
      { type: "tool_call", t: 1, id: "c1", tool: "get_ticket", input: { id: "1" } },
      { type: "tool_result", t: 9, id: "c1", tool: "get_ticket", ok: false, error: "Not found" },
    ], beginRun(emptyRun(), "x"));
    expect(run.steps[0]).toMatchObject({ status: "failed", error: "Not found", ms: 8 });
  });

  it("warns about an id the data never showed, and stops warning once an earlier result showed it", () => {
    const first = play([
      start,
      { type: "tool_call", t: 1, id: "c1", tool: "get_ticket", input: { id: "t-77" } },
    ], beginRun(emptyRun(), "show me the oldest ticket"));
    expect((first.steps[0] as any).problems[0]).toMatchObject({ code: "unseen_id" });

    const second = play([
      start,
      { type: "tool_call", t: 1, id: "c1", tool: "list", input: {} },
      { type: "tool_result", t: 2, id: "c1", tool: "list", ok: true, result: { data: [{ id: "t-77" }] }, chars: 20 },
      { type: "tool_call", t: 3, id: "c2", tool: "get_ticket", input: { id: "t-77" } },
    ], beginRun(emptyRun(), "show me the oldest ticket"));
    expect((second.steps[1] as any).problems).toEqual([]);
  });

  it("keeps what was seen across messages of one conversation, but starts the trace fresh", () => {
    const one = play([
      start,
      { type: "tool_result", t: 1, id: "x", tool: "list", ok: true, result: { data: [{ id: "keep-me" }] } },
      { type: "done", t: 2, conversationId: "conv-1" },
    ], beginRun(emptyRun(), "first"));
    const next = beginRun(one, "second message");
    expect(next.steps).toEqual([]);
    expect(next.conversationId).toBe("conv-1");
    expect(next.seen).toContain("keep-me");
    expect(next.seen).toContain("second message");
    expect(next.user?.name).toBe("Lena");
  });

  it("carries a refusal, an error, and the compile notes", () => {
    expect(play([{ type: "blocked", t: 1, stage: "input", reason: "Too long" }], beginRun(emptyRun(), "x"))).toMatchObject({ status: "blocked", blocked: "Too long" });
    expect(play([{ type: "error", t: 1, message: "The model call failed" }], beginRun(emptyRun(), "x"))).toMatchObject({ status: "error", error: "The model call failed" });
    expect(play([{ type: "platform_note", warnings: ["tool 'x' has no code"] }]).notes).toEqual(["tool 'x' has no code"]);
  });

  it("does not lose the words of a run that stopped before its next model call", () => {
    const run = play([
      start,
      { type: "model_call", t: 5, n: 1, ms: 5, inputTokens: 1, outputTokens: 1, messages: 1, toolsRequested: [] },
      { type: "text", t: 6, content: "Late words" },
      { type: "error", t: 7, message: "boom" },
    ], beginRun(emptyRun(), "x"));
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
