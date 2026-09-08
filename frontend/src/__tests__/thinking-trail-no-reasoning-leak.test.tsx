/**
 * DEFECT-THINKING-LEAK — the thinking trail must not paint the model's raw
 * chain-of-thought into the chat. §111: "Do not expose hidden model reasoning."
 * On K-01 (`deploy`) and L-05 a raw "Let me analyze this: 1. This is a change
 * request…" flashed in the panel as if it were Smith's answer. Deterministic
 * `step` status stays (it is observable progress); reasoning text does not.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ThinkingTrail } from "@/components/smith/SmithPanel";

describe("ThinkingTrail", () => {
  it("does not render raw model reasoning text", () => {
    const { container } = render(
      <ThinkingTrail
        busy
        thoughts={[
          { kind: "reasoning", text: "Let me analyze this: 1. This is a change request." },
          { kind: "reasoning", text: "The user is saying deploy." },
        ]}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Thinking");                 // busy header present
    expect(text).not.toContain("Let me analyze this");   // no raw reasoning leaked
    expect(text).not.toContain("The user is saying deploy");
  });

  it("still shows deterministic step status and hides reasoning", () => {
    const { container } = render(
      <ThinkingTrail
        busy
        thoughts={[
          { kind: "reasoning", text: "internal reasoning that must not show" },
          { kind: "step", text: "Regenerating frontend.", node: "frontend" },
        ]}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Working");
    expect(text).not.toContain("internal reasoning that must not show");
  });

  it("renders nothing when there are no thoughts", () => {
    const { container } = render(<ThinkingTrail busy thoughts={[]} />);
    expect(container.innerHTML).toBe("");
  });
});
