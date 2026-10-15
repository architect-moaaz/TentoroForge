/**
 * The study side reaches the page as `reference`, `cards` and `draft`
 * frames; the Drafts tab shows drafts side by side with a cost and time
 * range and what Forge cannot do yet; the References tab says what a
 * recording is stripped of.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { DraftsPanel } from "@/components/drafts-room/DraftsPanel";
import { ReferencesPanel } from "@/components/drafts-room/ReferencesPanel";
import { useDraftsRoomTurn } from "@/components/drafts-room/useDraftsRoomTurn";
import type { Card, Draft, Reference } from "@/components/drafts-room/types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function stream(frames: string): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) { controller.enqueue(new TextEncoder().encode(frames)); controller.close(); },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const DRAFT = (over: Partial<Draft>): Draft => ({
  id: "d1", version: 1, title: "Care first", pitch: "A notebook that logs every watering.", roles: [{ name: "Gardener" }],
  features: [{ name: "Log care", priority: "must" }], screens: [{ name: "Plants", device: "phone" }], records: [{ name: "Plant" }],
  rules: ["Once a day"], needs: ["push"], estimate: { units: 3, measured_on: "x", cost: { low: 0.74, high: 1.54 }, minutes: { low: 7, high: 14 }, fixes: { low: 0.19, high: 0.38 } },
  cannot_yet: [{ kind: "push", status: "unproven", what: "web push", proof: "not seen live" }], notes: [], changed: "first draft", created: 1, at: 1, ...over,
});

function Harness({ seen }: { seen: { refs: Reference[]; cards: Card[][]; drafts: Draft[] } }) {
  const turn = useDraftsRoomTurn("o1", "s1", {
    onBoard: () => undefined, onFile: () => undefined, onMessage: () => undefined, onHandoff: () => undefined, onStudy: () => undefined,
    onReference: (r) => seen.refs.push(r), onCards: (c) => seen.cards.push(c), onDraft: (d) => seen.drafts.push(d),
  });
  return <button onClick={() => void turn.send("go", [])}>go</button>;
}

describe("the study side on the page", () => {
  let root: Root | null = null;
  let host: HTMLDivElement | null = null;
  afterEach(() => { act(() => root?.unmount()); host?.remove(); vi.restoreAllMocks(); });
  function mount(el: React.ReactNode) {
    host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
    act(() => root!.render(el));
  }

  it("reference, cards and draft frames reach their handlers", async () => {
    const frames = [
      `event: reference\ndata: ${JSON.stringify({ reference: { id: "r1", name: "Garden", url: "https://garden.test", studies: {}, har: null, allowed: [], added_by: "u", at: 1 } })}\n`,
      `event: cards\ndata: ${JSON.stringify({ cards: [{ id: "c1", feature: "Log care" }] })}\n`,
      `event: draft\ndata: ${JSON.stringify({ draft: DRAFT({}) })}\n`,
      'event: done\ndata: {"status": "ok"}\n',
    ].join("");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(stream(frames));
    const seen = { refs: [] as Reference[], cards: [] as Card[][], drafts: [] as Draft[] };
    mount(<Harness seen={seen} />);
    await act(async () => { host!.querySelector("button")!.click(); await new Promise((r) => setTimeout(r, 20)); });
    expect(seen.refs.map((r) => r.name)).toEqual(["Garden"]);
    expect(seen.cards[0][0].feature).toBe("Log care");
    expect(seen.drafts[0].title).toBe("Care first");
  });

  it("drafts stand side by side with a range and what cannot be done yet", () => {
    const sent: string[] = []; const composed: string[] = []; const opened: string[] = [];
    mount(<DraftsPanel drafts={[DRAFT({}), DRAFT({ id: "d2", title: "Shop first", cannot_yet: [{ kind: "store_app", status: "not_yet", what: "", proof: "" }] })]}
      drawings={[]} drawingPath={(id, k) => `/d/${id}.${k}`} onOpen={(d) => opened.push(d)} onDraw={() => undefined}
      onPin={async () => undefined} onSend={(t) => sent.push(t)} onCompose={(t) => composed.push(t)} onOpenDrawing={() => undefined} built={false} />);
    const drafts = host!.querySelectorAll("[data-testid=draft]");
    expect(drafts.length).toBe(2);
    expect(drafts[0].querySelector("[data-testid=estimate]")!.textContent).toContain("$0.74–$1.54");
    expect(drafts[0].querySelector("[data-testid=estimate]")!.textContent).toContain("7–14 min");
    expect(drafts[1].querySelector("[data-testid=cannot-yet]")!.textContent).toContain("store app · not yet");
    const buttons = [...drafts[0].querySelectorAll("button")];
    act(() => (buttons.find((b) => b.textContent?.includes("Build this draft")) as HTMLButtonElement).click());
    expect(sent).toEqual(["Build draft d1 (“Care first”)"]);
    act(() => (buttons.find((b) => b.textContent?.includes("Revise")) as HTMLButtonElement).click());
    expect(composed[0]).toContain("Revise draft d1");
    act(() => (buttons.find((b) => b.textContent?.includes("Open")) as HTMLButtonElement).click());
    expect(opened).toEqual(["d1"]);
  });

  it("the references tab says what a recording is stripped of", () => {
    mount(<ReferencesPanel references={[]} studies={[]} onAdd={async () => undefined} onUploadHar={async () => undefined} onStop={() => undefined} />);
    expect(host!.querySelector("[data-testid=har-note]")!.textContent).toContain("Cookies, Authorization and Set-Cookie headers");
    expect(host!.querySelector("[data-testid=har-note]")!.textContent).toContain("never signs in for you");
  });
});
