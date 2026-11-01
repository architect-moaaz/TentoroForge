/**
 * Recording chats from Watch live (lib/agent-recording.ts), driven with the REAL captured run that Watch live is tested with
 * (lib/__fixtures__/watch-real-run.json) rather than hand-made chats: what is kept is what the app really sent.
 *
 * Pinned: a finished chat is kept with who wrote, the message, every step with its tool input and output, the checks, the reply
 * and the totals; one that is still going, or began before recording, is not; each chat is kept once; recording stops by itself at
 * the number asked for and keeps the first ones; what went wrong is worked out from what was recorded; the file has every detail;
 * and what comes back from the browser's storage is never trusted.
 */
import { describe, it, expect } from "vitest";
import fixture from "./__fixtures__/watch-real-run.json";
import { applyWatch, initialWatch, type WatchState } from "./agent-watch";
import type { LiveEvent } from "./agent-live";
import { arrivalNote, chatOf, chatsFor, clampWant, clear, emptyRecording, problemsOf, readRecording, recordingFile, sentence, start, stop, summarise, take, MAX_WANT } from "./agent-recording";

const events = fixture.events as LiveEvent[];
const map = fixture.map as LiveEvent;

/** The real chat, as a run with this id, up to `n` of its events. */
const play = (from: WatchState, id: string, n: number = events.length, at = 1000): WatchState =>
  events.slice(0, n).reduce((s, e) => applyWatch(s, { ...e, runId: id }, at), from);
const base = (): WatchState => applyWatch(initialWatch(), map);

describe("one real chat, recorded", () => {
  it("keeps who wrote, the message, every step with its input and output, the checks, the reply and the totals", () => {
    const state = play(base(), "r1");
    const chat = chatOf(state.runs.r1, 5000)!;
    expect(chat.id).toBe("r1");
    expect(chat.who?.name).toBeTruthy();
    expect(chat.message).toContain("open tickets");
    expect(chat.reply).toContain("open tickets");
    expect(chat.status).toBe("done");
    expect(chat.steps.map((s) => s.kind)).toEqual(["model", "tool", "model"]);
    const tool = chat.steps.find((s) => s.kind === "tool")!;
    expect(tool.kind === "tool" && tool.input).toBeTruthy();
    expect(tool.kind === "tool" && tool.result).toBeDefined();
    expect(chat.phases.map((p) => p.phase)).toEqual(["input_check", "memory", "output_check"]);
    expect(chat.totals.modelCalls).toBe(2);
    expect(chat.totals.toolCalls).toBe(1);
    expect(chat.recordedAt).toBe(5000);
    expect(problemsOf(chat), "the one thing wrong with the real chat is that it took 34 seconds").toEqual(["It was slow: 34 seconds to answer."]);
    expect(problemsOf({ ...chat, totals: { ...chat.totals, ms: 4000 } }), "answered quickly it went well").toEqual([]);
  });

  it("is not kept while it is still going", () => {
    const state = play(base(), "r1", 4);
    expect(state.runs.r1.finished).toBe(false);
    expect(chatOf(state.runs.r1)).toBeNull();
  });
});

describe("recording the next X chats", () => {
  it("takes finished chats, once each, and says how far it has got", () => {
    let rec = start(emptyRecording(), 3, 500);
    expect(rec).toMatchObject({ on: true, want: 3, chats: [] });
    let state = play(base(), "r1");
    rec = take(rec, state, 2000);
    rec = take(rec, state, 3000);
    expect(rec.chats.map((c) => c.id), "the same chat arriving again adds nothing").toEqual(["r1"]);
    expect(summarise(rec).text).toBe("Recording: 1 of 3 chats");
    state = play(state, "r2");
    rec = take(rec, state, 4000);
    expect(rec.chats.map((c) => c.id)).toEqual(["r1", "r2"]);
    expect(rec.on).toBe(true);
  });

  it("stops by itself at X and keeps the first X", () => {
    const state = play(play(play(base(), "r1"), "r2"), "r3");
    const rec = take(start(emptyRecording(), 2, 0), state, 9);
    expect(rec.chats).toHaveLength(2);
    expect(rec.on).toBe(false);
    expect(summarise(rec).text, "both real chats were slow").toBe("Recorded 2 chats, 2 with problems");
    expect(summarise({ ...rec, chats: rec.chats.map((c) => ({ ...c, totals: { ...c.totals, ms: 4000 } })) }).text).toBe("Recorded 2 chats, none with problems");
    expect(take(rec, play(state, "r4"), 10).chats, "a full recording takes no more").toHaveLength(2);
  });

  it("does not take a chat that began before recording started, or one still going", () => {
    const early = play(base(), "old", events.length, 100);
    const rec = start(emptyRecording(), 5, 1000);
    expect(take(rec, early, 2000).chats, "it began at 100, before 1000").toEqual([]);
    const running = play(base(), "now", 4, 1500);
    expect(take(rec, running, 2000).chats).toEqual([]);
  });

  it("does nothing while recording is off, and can be stopped and cleared", () => {
    const state = play(base(), "r1");
    expect(take(emptyRecording(), state)).toEqual(emptyRecording());
    const on = take(start(emptyRecording(), 5, 0), state);
    const off = stop(on);
    expect(off.on).toBe(false);
    expect(off.chats).toHaveLength(1);
    expect(clear({ ...off, want: 7 })).toEqual({ ...emptyRecording(), want: 7 });
  });

  it("makes the number of chats sensible", () => {
    expect([clampWant(0), clampWant(-3), clampWant(2.6), clampWant(500), clampWant("x"), clampWant("12")]).toEqual([1, 1, 3, MAX_WANT, 5, 12]);
  });
});

describe("what went wrong", () => {
  // the real chat, answered quickly (the captured one took 34 seconds, which is itself a problem)
  const good = () => { const c = chatOf(play(base(), "r1").runs.r1)!; return { ...c, totals: { ...c.totals, ms: 4000 } }; };

  it("names each kind of trouble in plain words", () => {
    const bad = {
      ...good(),
      status: "error" as const, error: "boom", reply: "", totals: { ...good().totals, ms: 41_000 },
      phases: [{ phase: "output_check" as const, t: 1, ok: false, reason: "leaks a secret" }],
      steps: [
        { kind: "tool" as const, id: "c", tool: "update_ticket", t: 1, input: {}, status: "failed" as const, error: "403", problems: [{ code: "missing" as const, message: "id is required" }], calls: [] },
        { kind: "model" as const, n: 1, t: 1, ms: 1, inputTokens: 1, outputTokens: 1, messages: 1, toolsRequested: [], said: "", failed: "overloaded" },
      ],
    };
    const said = problemsOf(bad).join(" ");
    for (const part of ["The chat failed: boom", "update_ticket failed: 403", "bad input: id is required", "A call to the AI failed: overloaded", "output check: leaks a secret", "41 seconds"]) expect(said).toContain(part);
    expect(problemsOf({ ...good(), reply: "" }).join(" ")).toContain("no reply");
    expect(problemsOf({ ...good(), status: "blocked", blocked: "too long", reply: "" }).join(" ")).toContain("refused the message");
  });

  it("counts the chats with problems in the summary", () => {
    const rec = { ...emptyRecording(), chats: [good(), { ...good(), id: "r2", status: "error" as const, error: "x" }] };
    expect(summarise(rec).text).toBe("Recorded 2 chats, 1 with problems");
  });
});

describe("the file and the browser's storage", () => {
  it("has every detail of every chat, and what went wrong in each", () => {
    const rec = take(start(emptyRecording(), 2, 0), play(base(), "r1"));
    const file = recordingFile(rec, "p1", new Date("2026-10-22T09:30:15.123Z"));
    expect(file.name).toBe("watch-recording-2026-10-22T09-30-15.json");
    const parsed = JSON.parse(file.json);
    expect(parsed).toMatchObject({ kind: "forge-watch-recording", version: 1, project: "p1" });
    expect(parsed.chats[0].steps).toHaveLength(3);
    expect(parsed.chats[0].message).toContain("open tickets");
    expect(parsed.chats[0].problems).toEqual(["It was slow: 34 seconds to answer."]);
  });

  it("brings back what was kept, and never trusts what was not", () => {
    const rec = take(start(emptyRecording(), 2, 7), play(base(), "r1"));
    expect(readRecording(JSON.stringify(rec))).toEqual(rec);
    for (const junk of ["", "not json", "null", "[]", '{"chats":"x"}', 5, undefined]) expect(readRecording(junk)).toEqual(emptyRecording());
    const mixed = readRecording({ want: 99, on: true, startedAt: 3, chats: [{ id: "a" }, rec.chats[0], null] });
    expect(mixed.chats).toHaveLength(1);
    expect(mixed.want).toBe(MAX_WANT);
  });
});

describe("what is said after a send", () => {
  const sent = (over: Record<string, unknown> = {}) => ({ sent: 3, added: 3, alreadyThere: 0, leftOut: 0, fixes: [], problems: {}, ...over });
  const fix = { id: "f", kind: "instruction_add" as const, title: "T", why: "w", fixesTests: [] };

  it("only chats of this assistant (or of no named assistant) are sent, and the rest are counted", () => {
    const chat = (id: string, agentId?: string) => ({ ...chatOf(play(base(), id).runs[id], 1)!, agentId });
    const { mine, skipped } = chatsFor([chat("a", "me"), chat("b", "other"), chat("c", undefined), chat("d", "me")], "me");
    expect(mine.map((c) => c.id)).toEqual(["a", "c", "d"]);
    expect(skipped).toBe(1);
  });

  it("says how many were added as tests, and how many were there already", () => {
    expect(sentence(sent(), { fix: false })).toBe("Added 3 chats as tests in Find problems.");
    expect(sentence(sent({ sent: 1, added: 1 }), { fix: false })).toBe("Added 1 chat as tests in Find problems.");
    expect(sentence(sent({ added: 2, alreadyThere: 1 }), { fix: false })).toBe("Added 2 chats as tests in Find problems (1 was already there).");
    expect(sentence(sent({ added: 1, alreadyThere: 2 }), { fix: false })).toContain("(2 were already there)");
    expect(sentence(sent({ added: 0, alreadyThere: 3 }), { fix: false })).toBe("Those 3 chats were already in Find problems as tests.");
  });

  it("says what the fixer made of it, only when it was asked", () => {
    expect(sentence(sent({ fixes: [fix, fix] }), { fix: true })).toBe("Added 3 chats as tests in Find problems. The fixer proposed 2 fixes.");
    expect(sentence(sent({ fixes: [fix] }), { fix: true })).toContain("The fixer proposed 1 fix.");
    expect(sentence(sent(), { fix: true })).toContain("The fixer found no safe fix.");
    expect(sentence(sent({ fixes: [fix] }), { fix: false })).not.toContain("fixer");
  });

  it("says how many were left out, by us or by the platform", () => {
    expect(sentence(sent({ leftOut: 1 }), { fix: false, skipped: 2 })).toContain("3 chats left out");
    expect(sentence(sent(), { fix: false, skipped: 1 })).toContain("1 chat left out");
    expect(sentence(sent(), { fix: false })).not.toContain("left out");
  });

  it("the note in Find problems says what arrived, how many had problems, and what the fixer found", () => {
    const base = { ...sent({ problems: { a: ["slow"], b: ["bad"] } }), key: 1, fixRequested: false };
    expect(arrivalNote(base)).toBe("Added 3 real chats from Watch live to My tests (2 of them had problems).");
    expect(arrivalNote({ ...base, problems: {} })).toContain("(none had problems)");
    expect(arrivalNote({ ...base, added: 0, alreadyThere: 3 })).toBe("Those 3 real chats were already in My tests (2 of them had problems).");
    expect(arrivalNote({ ...base, fixRequested: true, fixes: [fix] })).toContain("The fixer proposed 1 fix below.");
    expect(arrivalNote({ ...base, fixRequested: true })).toContain("The fixer found no safe fix.");
    expect(arrivalNote({ ...base, leftOut: 2 })).toContain("2 chats left out");
  });
});
