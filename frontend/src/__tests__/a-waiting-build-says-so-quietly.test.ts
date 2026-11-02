/**
 * A build that waits for a slot says so, as a line, not as an answer.
 *
 * At most FORGE_BUILD_SLOTS builds run at once across the workers; the one
 * that has to wait gets one `message` on its stream (`build_slots.held`).
 * Without a status the panel drew it as Smith's answer and wiped the trail of
 * steps the person was following; as "progress" it is the quiet line a long
 * turn's "Still at it" posts already are.
 */
import { describe, expect, it } from "vitest";

import { kindOf } from "@/components/smith/SmithPanel";
import { reduce, type BlueprintRun } from "@/hooks/useBlueprintRun";

const EMPTY: BlueprintRun = {
  messages: [], thoughts: [], events: [], nodes: [], nodesDone: 0, nodesTotal: 0, callsDone: 0,
  alreadyComplete: [], awaitingApproval: false, unbuilt: [], forecast: null, usage: null,
  status: "idle", error: null, review: null,
};

// What `build_slots.held` emits, word for word (`waiting_text(2)`).
const WAITING = {
  text: "The platform is already running as many builds as it takes at once (2), so yours is " +
        "waiting its turn and starts the moment one of them finishes. You don't need to do anything.",
  status: "progress",
};

describe("a build waiting for a slot", () => {
  it("reaches the run as a progress line and leaves the trail of steps", () => {
    let s = reduce(EMPTY, "started", {});
    s = reduce(s, "thought", { kind: "step", text: "Starting the build" });
    s = reduce(s, "message", WAITING);
    expect(s.messages).toEqual([{ text: WAITING.text, status: "progress",
                                  options: undefined, diffSummary: undefined, secret: undefined }]);
    expect(s.thoughts.map((t) => t.text)).toEqual(["Starting the build"]);
    expect(s.status).toBe("running");
  });

  it("is drawn as a quiet line, live and from the transcript alike", () => {
    // The live copy and `messageOf` both carry `status` through to the panel.
    expect(kindOf({ role: "smith", text: WAITING.text, status: "progress" })).toBe("progress");
    // Without it, the same words were Smith's answer.
    expect(kindOf({ role: "smith", text: WAITING.text })).toBe("smith");
  });
});
