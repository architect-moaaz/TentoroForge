/**
 * The Drafts Room's hand-off reaches the page as one `handoff` frame that
 * says the app exists and its build has started on the platform. Nothing is
 * replayed from the browser: the project page reattaches to the running
 * build when it opens. (Brain Juice stored the opening in sessionStorage and
 * the Smith panel sent it as a first message; no browser, no build.)
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { useDraftsRoomTurn, type Handoff } from "@/components/drafts-room/useDraftsRoomTurn";

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

const FRAMES = [
  'event: step\ndata: {"text": "Writing the requirements document…"}\n',
  'event: step\ndata: {"text": "Creating Threadline…"}\n',
  'event: step\ndata: {"text": "Starting the build…"}\n',
  'event: handoff\ndata: {"project_id": "p1", "org_id": "o1", "app_name": "Threadline", "description": "A wardrobe app.", "build": "started"}\n',
  'event: done\ndata: {"status": "ok"}\n',
].join("");

function Harness({ seen }: { seen: { handoff?: Handoff; steps?: string[] } }) {
  const turn = useDraftsRoomTurn("o1", "s1", {
    onBoard: () => undefined,
    onFile: () => undefined,
    onMessage: () => undefined,
    onStudy: () => undefined,
    onHandoff: (h) => { seen.handoff = h; },
  });
  seen.steps = turn.steps;
  return <button onClick={() => void turn.send("Build it", [])}>send</button>;
}

let root: Root | null = null;
afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("the hand-off frame", () => {
  it("says the app is created and being built, and leaves nothing to replay", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => stream(FRAMES)));
    const seen: { handoff?: Handoff; steps?: string[] } = {};
    const el = document.createElement("div");
    document.body.appendChild(el);
    await act(async () => {
      root = createRoot(el);
      root.render(<Harness seen={seen} />);
    });
    await act(async () => {
      el.querySelector("button")!.click();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(seen.handoff).toEqual({
      project_id: "p1", org_id: "o1", app_name: "Threadline", description: "A wardrobe app.", build: "started",
    });
    expect(seen.handoff && "opening" in seen.handoff).toBe(false);
    expect(seen.steps).toEqual(["Writing the requirements document…", "Creating Threadline…", "Starting the build…"]);
    expect(sessionStorage.length).toBe(0);
  });
});
