/**
 * The strip of checks above the canvas can be put away with its X, and it comes back when it has something new to say.
 * A question waiting for an answer ("Apply anyway?") can never be put away.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { AgentChecksBar } from "../AgentChecksBar";
import type { AgentFinding } from "@/types/agent-builder";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const finding = (over: Partial<AgentFinding> = {}): AgentFinding =>
  ({ severity: "warning", code: "no_tools", message: "This agent has no tools.", nodeId: null, ...over }) as AgentFinding;

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

const bar = (findings: AgentFinding[], confirming = false) =>
  act(async () => {
    root.render(<AgentChecksBar findings={findings} appChecked confirming={confirming} onSelectNode={() => {}} onApplyAnyway={() => {}} onCancel={() => {}} />);
  });
const strip = () => container.querySelector('[data-testid="agent-checks"]');
const x = () => container.querySelector('[aria-label="Dismiss these checks"]') as HTMLButtonElement | null;
const press = (el: Element) => act(async () => { (el as HTMLElement).click(); });

describe("putting the checks away", () => {
  it("the green strip has an X, and it stays away", async () => {
    await bar([]);
    expect(strip()?.textContent).toContain("No problems found");
    await press(x()!);
    expect(strip()).toBeNull();
    await bar([]); // the same thing said again
    expect(strip()).toBeNull();
  });

  it("a strip of warnings has an X, and it stays away for the same warnings", async () => {
    await bar([finding()]);
    expect(strip()?.textContent).toContain("Checks: 1 warning");
    await press(x()!);
    expect(strip()).toBeNull();
    await bar([finding()]);
    expect(strip()).toBeNull();
  });

  it("comes back when the checks say something else", async () => {
    await bar([finding()]);
    await press(x()!);
    expect(strip()).toBeNull();
    await bar([finding(), finding({ code: "many_tools", message: "Too many tools." })]);
    expect(strip()?.textContent).toContain("Checks: 2 warnings");
    await bar([]); // and the all-clear is a new thing to say as well
    expect(strip()?.textContent).toContain("No problems found");
  });

  it("opening the list of findings still works beside the X", async () => {
    await bar([finding()]);
    await press(strip()!.querySelector("button[aria-expanded]")!);
    expect(strip()?.textContent).toContain("This agent has no tools.");
    expect(x()).not.toBeNull();
  });

  it("a question that is waiting for an answer has no X and cannot be put away", async () => {
    await bar([finding({ severity: "error", code: "unknown_table", message: "No such table." })], true);
    expect(strip()?.textContent).toContain("Apply anyway?");
    expect(x()).toBeNull();
  });
});
