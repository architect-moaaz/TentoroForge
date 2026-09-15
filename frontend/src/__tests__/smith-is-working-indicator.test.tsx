/**
 * The Smith Chat "working" indicator.
 *
 * A build runs for minutes; a chat turn composes for a minute. Behind either,
 * the panel must say what Smith is doing — as an action, not a noun — so a long
 * turn reads as working rather than hung. It says "Thinking" while Smith
 * reasons and the present participle of the current stage while it does
 * something specific, marked by the forge (an anvil), not a generic spinner.
 */
import { describe, it, expect } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { ThinkingTrail } from "@/components/smith/SmithPanel";
import type { RunNode, RunThought } from "@/hooks/useBlueprintRun";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function mount(props: {
  thoughts: RunThought[];
  nodes: RunNode[];
  busy: boolean;
}) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  let root!: Root;
  act(() => {
    root = createRoot(el);
    root.render(<ThinkingTrail {...props} />);
  });
  return {
    el,
    text: () => el.textContent ?? "",
    hasForge: () =>
      !!el.querySelector('img[src="/tentoro-forge-loader.gif"]'),
    unmount: () => act(() => root.unmount()),
  };
}

const node = (key: string, state: RunNode["state"]): RunNode => ({
  key,
  state,
  calls: 0,
});

describe("the Smith working indicator", () => {
  it("names the current stage as a present participle, not a noun", () => {
    // page_layouts is running -> "Composing the screens", never "Working".
    const v = mount({
      thoughts: [],
      nodes: [node("requirements", "done"), node("page_layouts", "running")],
      busy: true,
    });
    expect(v.text()).toContain("Composing the screens");
    expect(v.text()).not.toContain("Working");
    v.unmount();
  });

  it("says Thinking while Smith is only reasoning", () => {
    const v = mount({
      thoughts: [{ kind: "reasoning", text: "Considering the route." }],
      nodes: [],
      busy: true,
    });
    expect(v.text()).toContain("Thinking");
    v.unmount();
  });

  it("shows the Tentoro Forge loader, not a generic spinner, while busy", () => {
    const v = mount({ thoughts: [], nodes: [], busy: true });
    expect(v.hasForge()).toBe(true);
    v.unmount();
  });

  it("renders nothing when idle with nothing to show", () => {
    const v = mount({ thoughts: [], nodes: [], busy: false });
    expect(v.text()).toBe("");
    v.unmount();
  });

  it("prefers the running stage over a stale reasoning thought", () => {
    const v = mount({
      thoughts: [{ kind: "reasoning", text: "hmm" }],
      nodes: [node("frontend", "running")],
      busy: true,
    });
    expect(v.text()).toContain("Generating the frontend");
    v.unmount();
  });
});
