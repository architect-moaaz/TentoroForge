/**
 * "Confirm before changing", from the person's side: the SHIPPED chat widget (backend/templates/runtime/agents/
 * ChatWidget.tsx). A change the app is holding shows a Go ahead and a Cancel button; pressing one sends the hold's id
 * in a structured `confirm` field; and typing a reply, however it is worded, sends none. The old rule read any
 * reply that was not an English "no" as a yes.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { ChatWidget } from "../../../backend/templates/runtime/agents/ChatWidget";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
// jsdom draws no layout, so it has no scrollIntoView; the widget calls it after every message.
Element.prototype.scrollIntoView = () => {};

const agents = [{ id: "a1", name: "Helper", description: null, ui: { title: "Helper", position: "full-page" } }];
const sse = (events: unknown[]) =>
  new Response(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(""), { headers: { "content-type": "text/event-stream" } });

const heldTurn = (holdId: string) => [
  { type: "text", content: "I will close ticket t1. Press Go ahead to agree." },
  { type: "tool_call", id: "c1", tool: "update_ticket", input: {} },
  { type: "tool_result", id: "c1", tool: "update_ticket", ok: true, held: true, holdId },
  { type: "done", conversationId: "conv-1", tokens: { input: 1, output: 1 }, turns: 1, messageId: "m1" },
];

let posts: Array<Record<string, unknown>>;
let replies: unknown[][];
let root: Root;
let el: HTMLElement;

beforeEach(() => {
  posts = [];
  replies = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        return sse(replies.shift() ?? [{ type: "done", conversationId: "conv-1", tokens: { input: 0, output: 0 }, turns: 1, messageId: null }]);
      }
      if (String(url).includes("/api/agent/chat")) return Response.json(agents);
      return Response.json([]);
    }),
  );
  el = document.createElement("div");
  document.body.appendChild(el);
});

afterEach(() => {
  act(() => root.unmount());
  el.remove();
  vi.unstubAllGlobals();
});

async function mount() {
  await act(async () => {
    root = createRoot(el);
    root.render(<ChatWidget variant="page" />);
  });
}

const button = (name: string) => [...el.querySelectorAll("button")].find((b) => b.textContent === name) as HTMLButtonElement | undefined;

async function type(text: string) {
  const input = el.querySelector("input[aria-label='Message']") as HTMLInputElement;
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    set.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    (el.querySelector("form") as HTMLFormElement).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

const click = (b: HTMLButtonElement) => act(async () => { b.click(); });

describe("a held change in the chat", () => {
  it("is shown with Go ahead and Cancel, and typing sends no press", async () => {
    await mount();
    replies.push(heldTurn("hold-1111-aaaa"));
    await type("close ticket t1");
    expect(posts[0]).not.toHaveProperty("confirm");
    expect(button("Go ahead")).toBeTruthy();
    expect(button("Cancel")).toBeTruthy();

    // Typing "yes" is not a press: the request carries no confirm field at all.
    replies.push(heldTurn("hold-2222-bbbb"));
    await type("yes please");
    expect(posts[1]).not.toHaveProperty("confirm");
    expect(posts[1].message).toBe("yes please");
  });

  it("is released only by Go ahead, which sends that hold's id", async () => {
    await mount();
    replies.push(heldTurn("hold-3333-cccc"));
    await type("close ticket t1");
    await click(button("Go ahead")!);
    expect(posts[1].confirm).toEqual({ holdId: "hold-3333-cccc", decision: "confirm" });
    // Once answered, the buttons are gone: there is nothing left to press.
    expect(button("Go ahead")).toBeUndefined();
  });

  it("is dropped by Cancel, which says so in the same structured way", async () => {
    await mount();
    replies.push(heldTurn("hold-4444-dddd"));
    await type("close ticket t1");
    await click(button("Cancel")!);
    expect(posts[1].confirm).toEqual({ holdId: "hold-4444-dddd", decision: "cancel" });
  });

  it("labels its buttons in plain words, with no brackets or ampersands", async () => {
    await mount();
    replies.push(heldTurn("hold-5555-eeee"));
    await type("close ticket t1");
    const labels = [button("Go ahead"), button("Cancel")].map((b) => b?.textContent ?? "");
    expect(labels).toEqual(["Go ahead", "Cancel"]);
    for (const l of labels) expect(l).not.toMatch(/[\[\]()&]/);
  });
});
