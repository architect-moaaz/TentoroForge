/**
 * Each screen on the board is drawn as a page in the company's brand. A
 * `drawing` frame reaches the page as the drawing starts and lands; the card
 * shows the picture when there is one, else the document itself in a frame
 * that may run nothing; a failed drawing says so and offers Redraw.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { ScreenDrawing } from "@/components/drafts-room/ScreenDrawing";
import { useDraftsRoomTurn } from "@/components/drafts-room/useDraftsRoomTurn";
import type { Drawing } from "@/components/drafts-room/types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function stream(frames: string): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(frames));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const DRAWING: Drawing = {
  id: "d1", screen: "Plant detail", status: "done", viewport: "phone", html: true, png: false,
  caption: "Plant detail — drawn in Acme's brand", brand_source: "company", at: 1,
};

function Harness({ seen }: { seen: Drawing[] }) {
  const turn = useDraftsRoomTurn("o1", "s1", {
    onBoard: () => undefined, onFile: () => undefined, onMessage: () => undefined,
    onHandoff: () => undefined, onStudy: () => undefined, onDrawing: (d) => seen.push(d),
  });
  return <button onClick={() => void turn.send("draw", [])}>go</button>;
}

const path = (id: string, kind: "html" | "png") => `/api/orgs/o1/drafts-room/s1/drawings/${id}.${kind}`;

describe("screens drawn in the company's brand", () => {
  let root: Root | null = null;
  let host: HTMLDivElement | null = null;
  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    vi.restoreAllMocks();
  });

  function mount(el: React.ReactNode) {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => root!.render(el));
  }

  it("a drawing frame reaches the page as it starts and as it lands", async () => {
    const frames = [
      `event: drawing\ndata: ${JSON.stringify({ drawing: { ...DRAWING, status: "drawing", html: false } })}\n`,
      `event: drawing\ndata: ${JSON.stringify({ drawing: DRAWING })}\n`,
      'event: done\ndata: {"status": "ok"}\n',
    ].join("");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(stream(frames));
    const seen: Drawing[] = [];
    mount(<Harness seen={seen} />);
    await act(async () => {
      host!.querySelector("button")!.click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(seen.map((d) => d.status)).toEqual(["drawing", "done"]);
    expect(seen[1].caption).toContain("Acme's brand");
  });

  it("shows the document in a frame that may run nothing when there is no picture", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<!doctype html><html><body>Plant</body></html>"));
    mount(<ScreenDrawing drawing={DRAWING} path={path} onOpen={() => undefined} onRedraw={() => undefined} />);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    const frame = host!.querySelector("iframe")!;
    expect(frame).not.toBeNull();
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("srcdoc")).toContain("<!doctype html>");
    expect(host!.querySelector("img")).toBeNull();
    expect((globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0]).toContain("/drawings/d1.html");
  });

  it("shows the picture when a browser took one, and nothing live", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(new Blob([new Uint8Array([137, 80, 78, 71])])));
    vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:x" });
    mount(<ScreenDrawing drawing={{ ...DRAWING, png: true }} path={path} onOpen={() => undefined} onRedraw={() => undefined} />);
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(host!.querySelector("iframe")).toBeNull();
    expect((globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0]).toContain("/drawings/d1.png");
  });

  it("a failed drawing says so and offers Redraw", () => {
    const redraws: number[] = [];
    mount(<ScreenDrawing drawing={{ ...DRAWING, status: "failed", html: false, error: "RuntimeError: no document" }}
      path={path} onOpen={() => undefined} onRedraw={() => redraws.push(1)} />);
    expect(host!.querySelector("[data-testid=drawing-status]")!.textContent).toContain("Could not be drawn: RuntimeError: no document");
    act(() => (host!.querySelector("button") as HTMLButtonElement).click());
    expect(redraws).toEqual([1]);
    expect(host!.querySelector("button")!.textContent).toContain("Redraw");
  });

  it("a screen not drawn yet offers Draw", () => {
    mount(<ScreenDrawing drawing={undefined} path={path} onOpen={() => undefined} onRedraw={() => undefined} />);
    expect(host!.querySelector("[data-testid=drawing-status]")!.textContent).toContain("Not drawn yet");
    expect(host!.querySelector("button")!.textContent).toContain("Draw");
  });
});
