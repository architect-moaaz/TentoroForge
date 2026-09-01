/**
 * Smith's reasoning reaches the panel, and leaves when the answer arrives.
 *
 * A turn that composes a screen runs for about a minute behind one `message`
 * event. Until it lands the panel shows a spinner, so a long turn and a stuck
 * one are indistinguishable — the same complaint as the empty editor panels
 * and the unreported runs.
 */
import { describe, expect, it } from "vitest";

import { reduce } from "@/hooks/useBlueprintRun";

const EMPTY = {
  messages: [], thoughts: [], events: [], nodes: [], nodesDone: 0,
  nodesTotal: 0, callsDone: 0, alreadyComplete: [], awaitingApproval: false,
  unbuilt: [], forecast: null, usage: null, status: "idle" as const,
  error: null,
};

describe("thought events", () => {
  it("collects reasoning in arrival order", () => {
    let s = reduce(EMPTY, "thought", { text: "The route / has no layout." });
    s = reduce(s, "thought", { text: "So this is a composition." });
    expect(s.thoughts).toEqual([
      "The route / has no layout.",
      "So this is a composition.",
    ]);
  });

  it("drops empty reasoning rather than rendering a blank line", () => {
    const s = reduce(EMPTY, "thought", { text: "   " });
    expect(s.thoughts).toEqual([]);
  });

  it("does not put reasoning in the transcript", () => {
    // It is how the answer was reached, not part of the conversation — and
    // the server does not write it to the stored transcript either.
    const s = reduce(EMPTY, "thought", { text: "Considering the route." });
    expect(s.messages).toEqual([]);
  });

  it("clears the reasoning once Smith speaks", () => {
    // The answer says it better than the thinking that reached it, and the
    // reasoning from one turn must not sit above the next.
    let s = reduce(EMPTY, "thought", { text: "Considering the route." });
    s = reduce(s, "message", { text: "I composed the dashboard." });
    expect(s.thoughts).toEqual([]);
    expect(s.messages.map((m) => m.text)).toEqual(["I composed the dashboard."]);
  });

  it("records the event either way, like every other event", () => {
    const s = reduce(EMPTY, "thought", { text: "x" });
    expect(s.events.map((e) => e.event)).toEqual(["thought"]);
  });
});
