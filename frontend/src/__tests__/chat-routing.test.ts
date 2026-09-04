/**
 * Which backend a chat message goes to.
 *
 * There are two, and they do different jobs: the streaming front door builds
 * an application (discovery → plan → generate), and `/smith/turn` changes one
 * that already exists. Getting this wrong is quiet in both directions — a
 * change sent to the front door re-runs a build, and a first prompt sent to
 * Smith hits a project with no Blueprint.
 */
import { describe, it, expect } from "vitest";
import { routeFor, isControlSignal } from "@/components/chat/ChatPanel";

describe("routing a chat message", () => {
  it("sends a change to Smith once the project has a Blueprint", () => {
    expect(routeFor("make the candidate table compact", true)).toBe("smith-turn");
  });

  it("keeps the front door while there is nothing to change yet", () => {
    // No Blueprint means the project has not been discovered, planned or
    // built. Smith would have nothing to reason against.
    expect(routeFor("build me an applicant tracker", false)).toBe("front-door");
  });

  it("keeps lifecycle signals on the front door even with a Blueprint", () => {
    // These drive the build flow, not a conversation about the app.
    for (const signal of [
      "[APPROVE_PLAN]",
      "[APPROVE_DISCOVERY]",
      "[SELECT_TEMPLATE:aurora]",
      '[APPROVE_DISCOVERY] {"mode":"fast"}',
    ]) {
      expect(routeFor(signal, true), signal).toBe("front-door");
    }
  });

  it("treats a sentence that merely mentions brackets as a real message", () => {
    expect(routeFor("rename the [Draft] badge to Pending", true)).toBe("smith-turn");
  });

  it("ignores surrounding whitespace when recognising a signal", () => {
    expect(isControlSignal("  [APPROVE_PLAN]  ")).toBe(true);
  });

  it("does not mistake a lowercase bracketed word for a signal", () => {
    expect(isControlSignal("[approve_plan]")).toBe(false);
  });
});
