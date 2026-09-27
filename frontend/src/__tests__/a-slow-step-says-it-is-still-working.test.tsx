/**
 * A step that is slow but alive says so.
 *
 * A model call still streaming changed nothing on the panel but the clock,
 * which reads the same as a hang. After three quiet minutes the status line
 * says the step is still working; the moment anything lands, the note goes.
 */
// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StageList } from "@/components/smith/SmithPanel";
import { SLOW_STEP_MS, progressMark, slowStepNote } from "@/components/smith/slowStep";
import { reduce, type BlueprintRun } from "@/hooks/useBlueprintRun";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const EMPTY: BlueprintRun = {
  messages: [], thoughts: [], events: [], nodes: [], nodesDone: 0, nodesTotal: 0, callsDone: 0,
  alreadyComplete: [], awaitingApproval: false, unbuilt: [], forecast: null, usage: null,
  status: "idle", error: null, review: null,
};
const play = (steps: [string, Record<string, unknown>][], from: BlueprintRun = EMPTY) =>
  steps.reduce((s, [e, d]) => reduce(s, e, d), from);

const RUNNING = play([["started", {}], ["plan", { nodes: ["requirements", "page_code"], total: 2 }],
                      ["node:start", { node: "requirements" }]]);

describe("the note", () => {
  it("is silent before three minutes and says how long after", () => {
    expect(slowStepNote(SLOW_STEP_MS - 1000)).toBeNull();
    expect(slowStepNote(SLOW_STEP_MS + 20_000)).toBe(
      "This step is taking longer than usual (nothing new for 3m 20s). " +
      "It's still working; long steps can take several minutes.");
  });

  it("counts a landing as progress, and nothing else", () => {
    const later = play([["node:done", { node: "requirements" }]], RUNNING);
    expect(progressMark(later)).not.toBe(progressMark(RUNNING));
    expect(progressMark({ ...RUNNING })).toBe(progressMark(RUNNING));
  });
});

describe("the status line", () => {
  let host: HTMLDivElement;
  beforeEach(() => { vi.useFakeTimers(); host = document.createElement("div"); document.body.appendChild(host); });
  afterEach(() => { vi.useRealTimers(); host.remove(); });

  it("shows the note after a quiet stretch and drops it when the build moves", () => {
    const root = createRoot(host);
    act(() => root.render(<StageList run={RUNNING} />));
    act(() => { vi.advanceTimersByTime(SLOW_STEP_MS - 5000); });
    expect(host.textContent).not.toContain("taking longer than usual");
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(host.textContent).toContain("This step is taking longer than usual (nothing new for 3m 05s)");
    const moved = play([["node:done", { node: "requirements" }], ["node:start", { node: "page_code" }]], RUNNING);
    act(() => root.render(<StageList run={moved} />));
    act(() => { vi.advanceTimersByTime(1000); });
    expect(host.textContent).not.toContain("taking longer than usual");
    act(() => root.unmount());
  });

  it("says nothing once the run is over", () => {
    const root = createRoot(host);
    act(() => root.render(<StageList run={RUNNING} />));
    act(() => { vi.advanceTimersByTime(SLOW_STEP_MS + 5000); });
    act(() => root.render(<StageList run={play([["done", {}]], RUNNING)} />));
    expect(host.textContent).not.toContain("taking longer than usual");
    act(() => root.unmount());
  });
});
