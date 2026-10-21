/**
 * A self-heal card reads top to bottom as what broke, where, what Smith did,
 * and what happens next — and never says two contradicting things. Refund And
 * Chargeback's card said "no fix produced" over "nothing needed doing" over
 * "the change stays, untried" (pah7lhfz, 2026-10-21).
 */
import { describe, it, expect } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { SelfHealCard, type SelfHealMetadata } from "@/components/chat/SelfHealCard";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function mount(meta: Partial<SelfHealMetadata>) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  let root!: Root;
  act(() => {
    root = createRoot(el);
    root.render(<SelfHealCard metadata={{ self_heal: true, status: "failed", ...meta } as SelfHealMetadata} />);
  });
  return { el, text: () => el.textContent ?? "", unmount: () => act(() => root.unmount()) };
}

const crash = {
  error_message: 'invalid input syntax for type uuid: "CASE-NEW-001"',
  workflow_id: "reject-case",
  node_id: "record_decision",
  attempt: 1,
  max_attempts: 3,
};

describe("the self-heal card", () => {
  it("while fixing, names the place and the try", () => {
    const v = mount({ ...crash, status: "in_progress" });
    expect(v.text()).toContain("Fixing an error in the reject-case process");
    expect(v.text()).toContain("Try 1 of 3");
    expect(v.text()).toContain("CASE-NEW-001");
    expect(v.text()).toContain("record_decision");
    v.unmount();
  });

  it("fixed: the files and the commit, and no talk of trying again", () => {
    const v = mount({ ...crash, status: "resolved", edited_paths: ["app/src/lib/workflows/index.ts"], commit: "abcdef123456" });
    expect(v.text()).toContain("Fixed an error in");
    expect(v.text()).toContain("1 file changed");
    expect(v.text()).toContain("abcdef12");
    expect(v.text()).not.toContain("still open");
    v.unmount();
  });

  it("a change not yet proven is said as one, not as no fix", () => {
    const v = mount({ ...crash, status: "untried", edited_paths: ["app/src/lib/data-engine.ts"],
                      summary: "Changed the platform's `src/lib/data-engine.ts` for this app." });
    expect(v.text()).toContain("Changed, not yet proven");
    expect(v.text()).not.toMatch(/Not fixed|no fix/i);
    expect(v.text()).toContain("stays open until the app runs this again");
    v.unmount();
  });

  it("not fixed: how many automatic tries are left, or that there are none", () => {
    const one = mount({ ...crash, status: "failed" });
    expect(one.text()).toContain("Not fixed yet");
    expect(one.text()).toContain("2 tries left");
    one.unmount();
    const last = mount({ ...crash, status: "failed", attempt: 3 });
    expect(last.text()).toContain("last automatic try");
    last.unmount();
  });

  it("asks Smith's question in its own words", () => {
    const v = mount({ ...crash, status: "asked", question: "Should a rejected case keep its reference?" });
    expect(v.text()).toContain("Smith asks");
    expect(v.text()).toContain("Should a rejected case keep its reference?");
    v.unmount();
  });
});
