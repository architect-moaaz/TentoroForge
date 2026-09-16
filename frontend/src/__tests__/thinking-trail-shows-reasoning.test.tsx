/**
 * The thinking trail shows Smith's reasoning while a turn runs — as thinking.
 *
 * DEFECT-THINKING-LEAK was a raw "Let me analyze this: 1. This is a change
 * request…" painted into the chat as if it were Smith's answer. The fix then
 * was to hide reasoning; the ask now is to show it, and the contract that
 * keeps the defect fixed is FRAMING: the reasoning appears only under the
 * busy "Thinking" header, in its own labelled block, and is gone when the
 * turn ends. Deterministic `step` status renders as before.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ThinkingTrail } from "@/components/smith/SmithPanel";

describe("ThinkingTrail", () => {
  it("shows each thought on its own line under the Thinking header", () => {
    // The server flushes reasoning a sentence at a time, trimmed; the panel
    // puts each on its own line rather than running them together.
    const { container, getByTestId } = render(
      <ThinkingTrail
        busy
        thoughts={[
          { kind: "reasoning", text: "The user is asking which requirements came from the document." },
          { kind: "reasoning", text: "- REQ-004: Reception cannot close a visit." },
        ]}
      />,
    );
    expect(container.textContent).toContain("Thinking");
    const block = getByTestId("smith-thinking");
    expect(block.textContent).toBe(
      "The user is asking which requirements came from the document.\n- REQ-004: Reception cannot close a visit.",
    );
    expect(block.getAttribute("aria-label")).toBe("Smith's thinking");
  });

  it("keeps deterministic step status beside the reasoning", () => {
    const { container, getByTestId } = render(
      <ThinkingTrail
        busy
        thoughts={[
          { kind: "reasoning", text: "weighing the two readings" },
          { kind: "step", text: "Regenerating frontend.", node: "frontend" },
        ]}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Generating the frontend");
    expect(getByTestId("smith-thinking").textContent).toBe("weighing the two readings");
  });

  it("does not show reasoning once the turn is over", () => {
    const { container, queryByTestId } = render(
      <ThinkingTrail
        busy={false}
        thoughts={[{ kind: "reasoning", text: "stale reasoning from the turn" }]}
      />,
    );
    expect(queryByTestId("smith-thinking")).toBeNull();
    expect(container.textContent ?? "").not.toContain("stale reasoning");
  });

  it("renders nothing when idle with nothing to leave behind", () => {
    const { container } = render(<ThinkingTrail busy={false} thoughts={[]} />);
    expect(container.innerHTML).toBe("");
  });
});
