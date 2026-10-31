/**
 * The step cards: one for each call to the AI and one for each tool.
 *
 * What is pinned is what the builder reads: the exact input with a warning when it looks wrong, the real requests the
 * tool made, the data as a table (or text), how big the answer was and what the AI sees of it later, a held change,
 * a failure, and a call to the AI that is still working or failed.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

import { ModelCard, ToolCard } from "../AgentRunCards";
import type { ModelStep, ToolStep } from "@/lib/agent-live";

const tool = (over: Partial<ToolStep> = {}): ToolStep => ({ kind: "tool", id: "c1", tool: "get_ticket", t: 1, input: { id: "t-1" }, status: "ok", problems: [], calls: [], ...over });
const model = (over: Partial<ModelStep> = {}): ModelStep => ({ kind: "model", n: 1, t: 1, ms: 2990, inputTokens: 5000, outputTokens: 80, messages: 3, toolsRequested: [], said: "", ...over });

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});
const show = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); };
const text = () => container.textContent ?? "";

describe("ToolCard", () => {
  it("shows the exact input, and a warning for an input that looks wrong", async () => {
    await show(<ToolCard step={tool({ problems: [{ code: "unseen_id", field: "id", message: `"t-1" did not come from anything the agent was shown, so it may have been made up.` }] })} />);
    expect(text()).toContain('"id": "t-1"');
    expect(container.querySelector('[data-testid="live-problems"]')?.textContent).toContain("may have been made up");
  });

  it("shows no warning list when the input is fine", async () => {
    await show(<ToolCard step={tool()} />);
    expect(container.querySelector('[data-testid="live-problems"]')).toBeNull();
  });

  it("lists the real requests the tool made, with method, route, filters, status and time", async () => {
    await show(<ToolCard step={tool({ calls: [
      { kind: "request", label: "/api/data/tickets", method: "GET", query: { status: "open", limit: 50 }, status: 200, ms: 340, ok: true },
      { kind: "request", label: "/api/data/tickets/t-1", method: "PUT", body: { data: { status: "closed" } }, status: 403, ms: 20, ok: false, error: "Not allowed" },
      { kind: "workflow", label: "assign_ticket", ms: 900, ok: true },
    ] })} />);
    const calls = container.querySelector('[data-testid="live-calls"]')!.textContent!;
    expect(calls).toContain("GET /api/data/tickets?status=open&limit=50");
    expect(calls).toContain("200");
    expect(calls).toContain("340 ms");
    expect(calls).toContain("PUT /api/data/tickets/t-1");
    expect(calls).toContain("403");
    expect(calls).toContain("Not allowed");
    expect(calls).toContain('"status": "closed"');
    expect(calls).toContain("workflow assign_ticket");
    expect(calls).toContain("done");
  });

  it("shows a list of records as a table, and anything else as text", async () => {
    await show(<ToolCard step={tool({ result: { data: [{ id: "a", subject: "Wrong colour" }, { id: "b", subject: "Late" }] } })} />);
    expect(container.querySelector("table")?.textContent).toContain("Wrong colour");
    await show(<ToolCard step={tool({ result: { id: "a", status: "open" } })} />);
    expect(container.querySelector("table")).toBeNull();
    expect(text()).toContain('"status": "open"');
  });

  it("says how big the answer was, and what the AI sees of it on later turns", async () => {
    await show(<ToolCard step={tool({ chars: 450 })} />);
    expect(container.querySelector('[data-testid="live-size"]')?.textContent).toContain("450 characters");
    expect(container.querySelector('[data-testid="live-size"]')?.textContent).not.toContain("on later turns");
    await show(<ToolCard step={tool({ chars: 8000, cut: true })} />);
    const size = container.querySelector('[data-testid="live-size"]')!.textContent!;
    expect(size).toContain("8,000 characters");
    expect(size).toContain("on later turns only the first 3,000");
    expect(size).toContain("Cut here for the screen");
  });

  it("says what a held change and a failure mean", async () => {
    await show(<ToolCard step={tool({ tool: "update_ticket", status: "held", result: { held: true } })} />);
    expect(text()).toContain("held: waiting for a yes");
    expect(text()).toContain("reply \"yes\" in the app's chat");
    await show(<ToolCard step={tool({ status: "failed", error: "Not found" })} />);
    expect(text()).toContain("failed");
    expect(text()).toContain("Not found");
  });

  it("shows a tool that is still running without a result", async () => {
    await show(<ToolCard step={tool({ status: "running" })} />);
    expect(text()).toContain("running…");
    expect(text()).not.toContain("What the app returned");
  });
});

describe("ModelCard", () => {
  it("shows how long the AI worked, its tokens, and the tools it decided on", async () => {
    await show(<ModelCard step={model({ toolsRequested: ["list_tickets", "get_ticket"], said: "Let me look." })} last={false} />);
    expect(text()).toContain("worked on it for 3.0 s");
    expect(text()).toContain("5,000 tokens in");
    expect(text()).toContain("list_tickets, get_ticket");
    expect(text()).toContain("Let me look.");
  });

  it("does not repeat its words when they are shown as the reply", async () => {
    await show(<ModelCard step={model({ said: "There are 4 open tickets." })} last />);
    expect(text()).not.toContain("There are 4 open tickets.");
    expect(text()).toContain("Its words are below");
  });

  it("shows a call that is still working, with what it was given and the words so far", async () => {
    await show(<ModelCard step={model({ running: true, ms: 0, messages: 1, tools: 26, systemChars: 3150 })} last={false} pending="Let me check. " />);
    const card = container.querySelector('[data-testid="live-model-running"]')!;
    expect(card.textContent).toContain("Calling the AI…");
    expect(card.textContent).toContain("26 tools offered");
    expect(card.textContent).toContain("instructions 3,150 characters");
    expect(card.textContent).toContain("Let me check.");
  });

  it("shows a call that failed, with why", async () => {
    await show(<ModelCard step={model({ failed: "overloaded", ms: 49 })} last={false} />);
    expect(container.querySelector('[data-testid="live-model-running"]')?.textContent).toContain("The AI call failed: overloaded");
  });
});
