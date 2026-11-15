/**
 * Watch live: the strip for recording the next X chats.
 *
 * The panel is mounted with the real recording hook (as the builder does) and driven with the REAL captured chat, so what is pinned is
 * what the builder SEES and can press: the three states of the strip, "Send to Blast" and "Send to fix" handing the recorded chats
 * over and showing the sentence that comes back (or the reason it did not), "Download" making a file that holds every detail, "Clear",
 * and that the strip stays slim and its buttons carry no brackets or ampersands.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import fixture from "@/lib/__fixtures__/watch-real-run.json";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const apiGet = vi.fn();
vi.mock("@/lib/api", () => ({ api: { get: (u: string) => apiGet(u), post: vi.fn(), put: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }));

import { AgentWatchPanel } from "../AgentWatchPanel";
import { useWatchRecording } from "../useWatchRecording";
import { applyWatch, initialWatch, type WatchState } from "@/lib/agent-watch";
import type { LiveEvent } from "@/lib/agent-live";
import type { RecordedChat } from "@/lib/agent-recording";

const events = fixture.events as LiveEvent[];
const base = (): WatchState => applyWatch(initialWatch(), fixture.map as LiveEvent);
const play = (from: WatchState, id: string, at: number = Date.now() + 50): WatchState => events.reduce((s, e) => applyWatch(s, { ...e, runId: id }, at), from);

const sendBlast = vi.fn();
const sendFix = vi.fn();
let container: HTMLDivElement;
let root: Root;

function Harness({ watch }: { watch: WatchState }) {
  const recording = useWatchRecording("p1", watch);
  return (
    <AgentWatchPanel
      state={watch}
      link="connected"
      reason={null}
      suggestedUrl={null}
      projectId="p1"
      onConnect={vi.fn()}
      onDisconnect={vi.fn()}
      onSelect={vi.fn()}
      onFollow={vi.fn()}
      recording={recording}
      onSendToBlast={sendBlast}
      onSendToFix={sendFix}
    />
  );
}
const show = (watch: WatchState) => act(async () => { root.render(<Harness watch={watch} />); });
const strip = () => container.querySelector('[data-testid="watch-record"]') as HTMLElement;
const stripText = () => strip().textContent ?? "";
const byId = (id: string) => container.querySelector(`[data-testid="${id}"]`) as HTMLButtonElement;
const click = (e: Element) => act(async () => { (e as HTMLElement).click(); });
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 10)); });
const setNumber = (value: string) => act(async () => {
  const input = byId("watch-record-count") as unknown as HTMLInputElement;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
});
/** A recording with two real chats in it, ready to be sent. */
async function twoChats() {
  await show(base());
  await setNumber("2");
  await click(byId("watch-record-start"));
  await show(play(play(base(), "r1"), "r2"));
}

beforeEach(() => {
  window.localStorage.clear();
  apiGet.mockReset();
  apiGet.mockResolvedValue({ roles: [], people: [], peopleNote: null });
  sendBlast.mockReset();
  sendFix.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("the three states of the strip", () => {
  it("is idle at first: record the next five chats, a number to change, one button", async () => {
    await show(base());
    expect(stripText()).toContain("Record the next");
    expect(stripText()).toContain("chats");
    expect((byId("watch-record-count") as unknown as HTMLInputElement).value).toBe("5");
    expect(byId("watch-record-start").textContent).toBe("Record");
    expect(byId("watch-record-blast"), "nothing to send yet").toBeNull();
  });

  it("the number box takes 1 to 40: a bigger number is brought back to 40, nonsense to something sensible", async () => {
    await show(base());
    await setNumber("12");
    expect((byId("watch-record-count") as unknown as HTMLInputElement).value).toBe("12");
    await setNumber("900");
    expect((byId("watch-record-count") as unknown as HTMLInputElement).value).toBe("40");
    await click(byId("watch-record-start"));
    expect(stripText()).toContain("Recording: 0 of 40 chats");
  });

  it("says how far it has got while recording, with a Stop button, and Record is gone", async () => {
    await show(base());
    await setNumber("3");
    await click(byId("watch-record-start"));
    expect(byId("watch-record-text").textContent).toBe("Recording: 0 of 3 chats");
    expect(byId("watch-record-stop").textContent).toContain("Stop");
    expect(byId("watch-record-start")).toBeNull();
    await show(play(base(), "r1"));
    expect(byId("watch-record-text").textContent).toBe("Recording: 1 of 3 chats");
  });

  it("when it is done, says what was kept and offers to send, download, clear and record again", async () => {
    await twoChats();
    expect(byId("watch-record-text").textContent).toBe("Recorded 2 chats, 2 with problems");
    const labels = ["watch-record-blast", "watch-record-fix", "watch-record-download", "watch-record-clear", "watch-record-again"].map((id) => byId(id).textContent);
    expect(labels).toEqual(["Send to Blast", "Send to fix", "Download", "Clear", "Record again"]);
  });

  it("stopping early keeps what it has, ready to be sent", async () => {
    await show(base());
    await click(byId("watch-record-start"));
    await show(play(base(), "r1"));
    await click(byId("watch-record-stop"));
    expect(byId("watch-record-text").textContent).toBe("Recorded 1 chat, 1 with problems");
    expect(byId("watch-record-blast")).toBeTruthy();
  });

  it("no button says anything in brackets or with an ampersand, and the strip adds no scrolling area", async () => {
    const all = async () => [...container.querySelectorAll('[data-testid="watch-record"] button')].map((b) => b.textContent ?? "");
    await show(base());
    const idle = await all();
    await click(byId("watch-record-start"));
    const on = await all();
    await show(play(base(), "r1"));
    await click(byId("watch-record-stop"));
    const done = await all();
    for (const label of [...idle, ...on, ...done]) expect(label).not.toMatch(/[()[\]&]/);
    expect(idle.length + on.length + done.length).toBeGreaterThan(5);
    expect(strip().querySelector('[class*="overflow-y"]'), "the chats keep the room: the strip never scrolls").toBeNull();
    expect(strip().className).toContain("shrink-0");
  });

  it("is not there at all when the panel is not given a recording", async () => {
    await act(async () => {
      root.render(<AgentWatchPanel state={base()} link="idle" reason={null} suggestedUrl={null} projectId="p1" onConnect={vi.fn()} onDisconnect={vi.fn()} onSelect={vi.fn()} onFollow={vi.fn()} />);
    });
    expect(strip()).toBeNull();
  });
});

describe("sending", () => {
  it("Send to Blast hands over the recorded chats with every detail and shows the sentence that comes back", async () => {
    sendBlast.mockResolvedValue("Added 2 chats as tests in Find problems.");
    await twoChats();
    await click(byId("watch-record-blast"));
    expect(sendBlast).toHaveBeenCalledTimes(1);
    expect(sendFix).not.toHaveBeenCalled();
    const chats = sendBlast.mock.calls[0][0] as RecordedChat[];
    expect(chats.map((c) => c.id)).toEqual(["r1", "r2"]);
    expect(chats[0].steps.map((s) => s.kind)).toEqual(["model", "tool", "model"]);
    expect(chats[0].message).toContain("open tickets");
    const said = byId("watch-record-result");
    expect(said.textContent).toBe("Added 2 chats as tests in Find problems.");
    expect(said.getAttribute("role")).toBe("status");
  });

  it("Send to fix hands over the same chats to the fixing route", async () => {
    sendFix.mockResolvedValue("Added 2 chats as tests in Find problems. The fixer proposed 1 fix.");
    await twoChats();
    await click(byId("watch-record-fix"));
    expect(sendFix).toHaveBeenCalledTimes(1);
    expect(sendBlast).not.toHaveBeenCalled();
    expect((sendFix.mock.calls[0][0] as RecordedChat[]).map((c) => c.id)).toEqual(["r1", "r2"]);
    expect(byId("watch-record-result").textContent).toContain("The fixer proposed 1 fix.");
  });

  it("says why it did not work, as an alert, and keeps the chats so it can be tried again", async () => {
    sendBlast.mockRejectedValueOnce(new Error("The fixer needs the assistant as drawn."));
    sendBlast.mockResolvedValueOnce("Added 2 chats as tests in Find problems.");
    await twoChats();
    await click(byId("watch-record-blast"));
    const said = byId("watch-record-result");
    expect(said.getAttribute("role")).toBe("alert");
    expect(said.textContent).toBe("The fixer needs the assistant as drawn.");
    expect(byId("watch-record-text").textContent, "nothing was thrown away").toBe("Recorded 2 chats, 2 with problems");
    await click(byId("watch-record-blast"));
    expect(byId("watch-record-result").getAttribute("role")).toBe("status");
  });

  it("holds every button while sending, so a send cannot go twice", async () => {
    let finish: (s: string) => void = () => {};
    sendBlast.mockReturnValue(new Promise<string>((r) => { finish = r; }));
    await twoChats();
    await click(byId("watch-record-blast"));
    for (const id of ["watch-record-blast", "watch-record-fix", "watch-record-download", "watch-record-clear", "watch-record-again"]) expect(byId(id).disabled, id).toBe(true);
    await click(byId("watch-record-blast"));
    expect(sendBlast).toHaveBeenCalledTimes(1);
    await act(async () => finish("Done."));
    expect(byId("watch-record-blast").disabled).toBe(false);
    expect(byId("watch-record-result").textContent).toBe("Done.");
  });

  it("cannot send what is not there: no buttons without chats", async () => {
    await show(base());
    await click(byId("watch-record-start"));
    expect(byId("watch-record-blast")).toBeNull();
    expect(sendBlast).not.toHaveBeenCalled();
  });
});

describe("download and clear", () => {
  it("download makes a JSON file holding every detail of every chat, under a name with the date", async () => {
    const made: Blob[] = [];
    (URL as any).createObjectURL = vi.fn((b: Blob) => { made.push(b); return "blob:x"; });
    (URL as any).revokeObjectURL = vi.fn();
    const downloads: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { downloads.push(this.download); });
    await twoChats();
    await click(byId("watch-record-download"));
    expect(made).toHaveLength(1);
    expect(made[0].type).toBe("application/json");
    expect(downloads).toHaveLength(1);
    expect(downloads[0]).toMatch(/^watch-recording-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.json$/);
    // (jsdom's Blob has no text(): read it the old way)
    const body = JSON.parse(await new Promise<string>((done) => { const r = new FileReader(); r.onload = () => done(String(r.result)); r.readAsText(made[0]); }));
    expect(body.kind).toBe("forge-watch-recording");
    expect(body.chats.map((c: any) => c.id)).toEqual(["r1", "r2"]);
    const chat = body.chats[0];
    expect(chat.who.name, "who wrote").toBeTruthy();
    expect(chat.message).toContain("open tickets");
    const tool = chat.steps.find((s: any) => s.kind === "tool");
    expect(tool.input, "what the tool was given").toBeTruthy();
    expect(tool.result, "what came back").toBeDefined();
    expect(chat.phases.length, "the checks").toBeGreaterThan(0);
    expect(chat.reply).toBeTruthy();
    expect(chat.totals.modelCalls).toBe(2);
    expect(chat.problems, "what went wrong, said plainly").toEqual(["It was slow: 34 seconds to answer."]);
    expect(byId("watch-record-result").textContent).toContain("Saved watch-recording-");
    expect((URL as any).revokeObjectURL).toHaveBeenCalled();
  });

  it("says so, and keeps the chats, when the file cannot be made", async () => {
    (URL as any).createObjectURL = vi.fn(() => { throw new Error("no"); });
    await twoChats();
    await click(byId("watch-record-download"));
    expect(byId("watch-record-result").getAttribute("role")).toBe("alert");
    expect(byId("watch-record-text").textContent).toContain("Recorded 2 chats");
  });

  it("Clear empties the recording, and the strip is idle again with the number as it was", async () => {
    sendBlast.mockResolvedValue("Added 2 chats as tests in Find problems.");
    await twoChats();
    await click(byId("watch-record-blast"));
    await click(byId("watch-record-clear"));
    await settle();
    expect(byId("watch-record-idle")).toBeTruthy();
    expect(byId("watch-record-result"), "the old sentence goes with the old chats").toBeNull();
    expect((byId("watch-record-count") as unknown as HTMLInputElement).value).toBe("2");
    expect(JSON.parse(window.localStorage.getItem("forge.watch.recording.p1")!).chats).toEqual([]);
  });

  it("Record again throws the old chats away and starts on the next ones", async () => {
    await twoChats();
    await click(byId("watch-record-again"));
    expect(byId("watch-record-text").textContent).toBe("Recording: 0 of 2 chats");
  });
});
