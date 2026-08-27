/**
 * Parser coverage for smith_thought event payloads — the extended-thinking
 * variant (kind:"reasoning") must be distinguished from classic tool
 * events, and legacy events without `kind` must fall back to tool so
 * older backends stay compatible.
 */
import { describe, it, expect } from "vitest";
import {
  classifySmithThought,
  narrateSmithReasoning,
  narrateSmithThought,
} from "./smithNarration";

describe("classifySmithThought", () => {
  it("classifies extended-thinking chunks as reasoning", () => {
    const c = classifySmithThought({
      kind: "reasoning",
      text: "Looking at the schedule button — it dispatches AssessmentScheduling…",
    });
    expect(c.kind).toBe("reasoning");
    expect(c.text).toContain("AssessmentScheduling");
    expect(c.tool).toBe("");
  });

  it("classifies tool-call events as tool", () => {
    const c = classifySmithThought({
      tool: "read_workflow",
      summary: '{"path":"workflows/foo.json","nodes":8}',
    });
    expect(c.kind).toBe("tool");
    expect(c.tool).toBe("read_workflow");
    expect(c.summary).toContain("workflows/foo.json");
  });

  it("legacy events without `kind` default to tool (backward-compat)", () => {
    const c = classifySmithThought({ tool: "list_pages", summary: "3 pages" });
    expect(c.kind).toBe("tool");
    expect(c.tool).toBe("list_pages");
  });

  it("handles empty payloads without throwing", () => {
    const c = classifySmithThought({});
    expect(c.kind).toBe("tool");
    expect(c.text).toBe("");
    expect(c.tool).toBe("");
  });

  it("ignores unrecognized `kind` values and falls back to tool", () => {
    const c = classifySmithThought({ kind: "gibberish", tool: "recall" });
    expect(c.kind).toBe("tool");
    expect(c.tool).toBe("recall");
  });
});

describe("narrateSmithReasoning", () => {
  it("labels with an approximate token count for non-empty reasoning", () => {
    // 80 chars ≈ 20 tokens at 4 chars/token.
    const text = "a".repeat(80);
    const n = narrateSmithReasoning(text);
    expect(n.icon).toBe("💭");
    expect(n.text).toMatch(/Reasoning \(20 tokens\)/);
  });

  it("degrades gracefully on empty text", () => {
    const n = narrateSmithReasoning("");
    expect(n.icon).toBe("💭");
    expect(n.text).toBe("Reasoning…");
  });
});

describe("narrateSmithThought (regression — unchanged for legacy tools)", () => {
  it("still narrates known tools with their icon + short line", () => {
    const n = narrateSmithThought("read_workflow", '{"path":"workflows/foo.json","nodes":8}');
    expect(n.icon).toBe("⚙️");
    expect(n.text).toMatch(/Reading workflows\/foo\.json/);
  });
});
