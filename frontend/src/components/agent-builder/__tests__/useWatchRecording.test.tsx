/**
 * Recording the next X chats, as the builder holds it (useWatchRecording).
 *
 * Driven with the REAL captured chat (lib/__fixtures__/watch-real-run.json), played into the watch state the way the app streams it.
 * Pinned: a chat that finishes while recording is on is kept, one that was going on before is not, progress is said, recording stops
 * by itself at X, it goes on while nobody is looking at Watch live (the hook lives in the builder), what was recorded survives a
 * reload through the browser's storage, one project's recording is never shown under another, and everything still works when the
 * browser will not store anything.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import fixture from "@/lib/__fixtures__/watch-real-run.json";
import { applyWatch, initialWatch, type WatchState } from "@/lib/agent-watch";
import type { LiveEvent } from "@/lib/agent-live";
import { useWatchRecording } from "../useWatchRecording";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const events = fixture.events as LiveEvent[];
const base = (): WatchState => applyWatch(initialWatch(), fixture.map as LiveEvent);
/** The real chat as a run with this id, started at `at`. */
const play = (from: WatchState, id: string, n: number = events.length, at: number = Date.now() + 50): WatchState =>
  events.slice(0, n).reduce((s, e) => applyWatch(s, { ...e, runId: id }, at), from);

let container: HTMLDivElement;
let root: Root;
let api: ReturnType<typeof useWatchRecording>;

function Harness({ projectId, watch }: { projectId: string; watch: WatchState }) {
  api = useWatchRecording(projectId, watch);
  return <span data-testid="text">{api.summary.text}</span>;
}
const show = (watch: WatchState, projectId = "p1") => act(async () => { root.render(<Harness projectId={projectId} watch={watch} />); });
const KEY = "forge.watch.recording.p1";
const kept = () => api.recording.chats.map((c) => c.id);

beforeEach(() => {
  window.localStorage.clear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("recording", () => {
  it("starts idle, and keeps nothing until it is started", async () => {
    await show(play(base(), "r1"));
    expect(api.recording).toMatchObject({ on: false, want: 5, chats: [] });
    expect(api.summary.text).toBe("");
  });

  it("keeps a chat that finishes after it was started, with every detail, and says how far it has got", async () => {
    await show(base());
    await act(async () => api.start(3));
    expect(api.summary.text).toBe("Recording: 0 of 3 chats");
    await show(play(base(), "r1"));
    expect(kept()).toEqual(["r1"]);
    expect(api.summary.text).toBe("Recording: 1 of 3 chats");
    const chat = api.recording.chats[0];
    expect(chat.steps.map((s) => s.kind)).toEqual(["model", "tool", "model"]);
    expect(chat.message).toContain("open tickets");
    expect(chat.reply).toBeTruthy();
    expect(chat.who?.name).toBeTruthy();
  });

  it("does not keep a chat that was already going or finished before it was started, nor one still going", async () => {
    const before = play(base(), "old", events.length, 1000);
    await show(before);
    await act(async () => api.start(3));
    await show(before);
    expect(kept(), "it began before recording").toEqual([]);
    await show(play(before, "r1", 4));
    expect(kept(), "it has not finished").toEqual([]);
    await show(play(before, "r1"));
    expect(kept()).toEqual(["r1"]);
  });

  it("stops by itself at X and keeps the first X", async () => {
    await show(base());
    await act(async () => api.start(2));
    await show(play(play(play(base(), "r1"), "r2"), "r3"));
    expect(kept()).toEqual(["r1", "r2"]);
    expect(api.recording.on).toBe(false);
    expect(api.summary.text).toBe("Recorded 2 chats, 2 with problems");
  });

  it("can be stopped early, keeping what it has, and cleared", async () => {
    await show(base());
    await act(async () => api.start(5));
    await show(play(base(), "r1"));
    await act(async () => api.stop());
    expect(api.recording.on).toBe(false);
    await show(play(play(base(), "r1"), "r2"));
    expect(kept(), "a chat after stopping is not kept").toEqual(["r1"]);
    await act(async () => api.clear());
    expect(api.recording.chats).toEqual([]);
    expect(api.recording.want, "the number asked for is remembered").toBe(5);
  });

  it("records again from nothing, with a new number", async () => {
    await show(base());
    await act(async () => api.start(1));
    await show(play(base(), "r1"));
    expect(api.recording.on).toBe(false);
    await act(async () => api.start(2));
    expect(api.recording).toMatchObject({ on: true, want: 2, chats: [] });
  });

  it("takes the number to record as a sensible whole number from 1 to 40, only while not recording", async () => {
    await show(base());
    await act(async () => api.setWant(12));
    expect(api.recording.want).toBe(12);
    await act(async () => api.setWant(900));
    expect(api.recording.want).toBe(40);
    await act(async () => api.setWant(0));
    expect(api.recording.want).toBe(1);
    await act(async () => api.start(4));
    await act(async () => api.setWant(9));
    expect(api.recording.want, "not changed under a recording that is going").toBe(4);
  });

  it("goes on while the Watch live page is not shown: the hook is held by the builder, and only the watch state matters", async () => {
    await show(base());
    await act(async () => api.start(2));
    // the builder looks at another page (no panel at all), chats finish meanwhile
    await show(play(base(), "r1"));
    await show(play(play(base(), "r1"), "r2"));
    expect(kept()).toEqual(["r1", "r2"]);
  });
});

describe("remembered in the browser", () => {
  it("brings a recording back after a reload, with the progress where it was", async () => {
    await show(base());
    await act(async () => api.start(3));
    await show(play(base(), "r1"));
    expect(JSON.parse(window.localStorage.getItem(KEY)!).chats).toHaveLength(1);
    act(() => root.unmount());
    root = createRoot(container);
    await show(base());
    expect(kept()).toEqual(["r1"]);
    expect(api.recording).toMatchObject({ on: true, want: 3 });
    expect(api.summary.text).toBe("Recording: 1 of 3 chats");
  });

  it("keeps each project's recording apart", async () => {
    await show(base());
    await act(async () => api.start(3));
    await show(play(base(), "r1"));
    await show(base(), "p2");
    expect(kept(), "the other project has none").toEqual([]);
    expect(JSON.parse(window.localStorage.getItem(KEY)!).chats, "and the first one was not overwritten").toHaveLength(1);
    expect(window.localStorage.getItem("forge.watch.recording.p2")).toContain('"chats":[]');
    await show(base(), "p1");
    expect(kept()).toEqual(["r1"]);
  });

  it("starts empty when what was stored is not a recording", async () => {
    window.localStorage.setItem(KEY, "{not json");
    await show(base());
    expect(api.recording).toMatchObject({ on: false, chats: [] });
  });

  it("works when the browser will not read or store anything", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("full"); });
    await show(base());
    await act(async () => api.start(2));
    await show(play(base(), "r1"));
    expect(kept()).toEqual(["r1"]);
    expect(api.summary.text).toBe("Recording: 1 of 2 chats");
  });
});
