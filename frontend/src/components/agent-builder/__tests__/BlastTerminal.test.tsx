/**
 * The blast's live log as a terminal: lines in colour with the time they were printed, a cursor while it runs, the newest
 * line followed until you scroll up (then a way back down), and clear, copy and fold.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

import { BlastTerminal } from "../BlastTerminal";
import type { LogLine } from "@/lib/blast-log";

const line = (id: number, kind: LogLine["kind"], text: string, t = id * 1000): LogLine => ({ id, kind, text, t });
const LINES: LogLine[] = [line(1, "cmd", '$ blast "A"', 0), line(2, "info", "Asking the AI…", 1000), line(3, "good", "[01] ✔ DEFUSED   Ghost", 65000), line(4, "bad", "[02] ✖ EXPLODED  Bulk", 66000)];

let container: HTMLDivElement;
let root: Root;
const onClear = vi.fn();
beforeEach(() => {
  onClear.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

const show = async (props: Partial<{ lines: LogLine[]; running: boolean }> = {}) => {
  await act(async () => { root.render(<BlastTerminal lines={props.lines ?? LINES} running={props.running ?? false} onClear={onClear} />); });
};
const scroller = () => container.querySelector('[data-testid="terminal-lines"]') as HTMLDivElement;
const click = (label: string) => act(async () => { (container.querySelector(`[aria-label="${label}"]`) as HTMLElement).click(); });
/** jsdom has no layout: give the log a height so scrolling means something. */
function layout(el: HTMLElement, scrollHeight: number, clientHeight: number) {
  Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => scrollHeight });
  Object.defineProperty(el, "clientHeight", { configurable: true, get: () => clientHeight });
}

describe("BlastTerminal", () => {
  it("prints each line with when it was printed, in the colour of what it says", async () => {
    await show();
    const rows = [...container.querySelectorAll("[data-kind]")];
    expect(rows.map((r) => r.getAttribute("data-kind"))).toEqual(["cmd", "info", "good", "bad"]);
    expect(rows[0].textContent).toBe('+00:00$ blast "A"');
    expect(rows[2].textContent).toBe("+01:05[01] ✔ DEFUSED   Ghost");
    expect(rows[2].className).toContain("text-green-400");
    expect(rows[3].className).toContain("text-red-400");
    expect(container.textContent).toContain("4 lines");
  });

  it("is a log for assistive tech, in a dark monospaced pane", async () => {
    await show();
    expect(scroller().getAttribute("role")).toBe("log");
    const pane = container.querySelector('[data-testid="blast-terminal"]')!;
    expect(pane.className).toContain("bg-zinc-950");
    expect(pane.className).toContain("font-mono");
  });

  it("shows it is running, with a cursor under the last line, and not when it is done", async () => {
    await show({ running: true });
    expect(container.querySelector('[data-testid="terminal-running"]')?.textContent).toContain("running");
    expect(scroller().textContent).toContain("▌");
    await show({ running: false });
    expect(container.querySelector('[data-testid="terminal-running"]')).toBeNull();
    expect(scroller().textContent).not.toContain("▌");
  });

  it("follows the newest line as lines arrive", async () => {
    await show({ lines: LINES.slice(0, 2) });
    layout(scroller(), 1000, 200);
    scroller().scrollTop = 0;
    await show({ lines: LINES });
    expect(scroller().scrollTop).toBe(1000);
  });

  it("stays where you are once you scroll up, and offers a way back to the newest", async () => {
    await show({ lines: LINES.slice(0, 2) });
    layout(scroller(), 1000, 200);
    expect(container.querySelector('[data-testid="terminal-jump"]')).toBeNull();
    await act(async () => { scroller().scrollTop = 100; scroller().dispatchEvent(new Event("scroll", { bubbles: true })); });
    expect(container.querySelector('[data-testid="terminal-jump"]')?.textContent).toContain("newest");

    await show({ lines: LINES });
    expect(scroller().scrollTop).toBe(100);

    await act(async () => { (container.querySelector('[data-testid="terminal-jump"]') as HTMLElement).click(); });
    expect(scroller().scrollTop).toBe(1000);
    expect(container.querySelector('[data-testid="terminal-jump"]')).toBeNull();
  });

  it("follows again once you scroll back to the bottom", async () => {
    await show({ lines: LINES.slice(0, 2) });
    layout(scroller(), 1000, 200);
    await act(async () => { scroller().scrollTop = 100; scroller().dispatchEvent(new Event("scroll", { bubbles: true })); });
    await act(async () => { scroller().scrollTop = 790; scroller().dispatchEvent(new Event("scroll", { bubbles: true })); });
    expect(container.querySelector('[data-testid="terminal-jump"]')).toBeNull();
  });

  it("can be folded away and opened again, keeping its lines", async () => {
    await show();
    await click("Fold the log");
    expect(container.querySelector('[data-testid="terminal-lines"]')).toBeNull();
    expect(container.textContent).toContain("4 lines");
    await click("Show the log");
    expect(scroller().textContent).toContain("EXPLODED");
  });

  it("clears when asked, but not in the middle of a blast, and not when there is nothing to clear", async () => {
    await show();
    await click("Clear the log");
    expect(onClear).toHaveBeenCalledTimes(1);
    await show({ running: true });
    expect((container.querySelector('[aria-label="Clear the log"]') as HTMLButtonElement).disabled).toBe(true);
    await show({ lines: [] });
    expect((container.querySelector('[aria-label="Clear the log"]') as HTMLButtonElement).disabled).toBe(true);
    expect(container.textContent).toContain("0 lines");
  });

  it("copies the whole log as plain text with its times, and says so", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    await show();
    await click("Copy the log");
    expect(writeText).toHaveBeenCalledWith('+00:00 $ blast "A"\n+00:01 Asking the AI…\n+01:05 [01] ✔ DEFUSED   Ghost\n+01:06 [02] ✖ EXPLODED  Bulk');
    expect(container.textContent).toContain("copied");
  });

  it("does not break when the clipboard is not available", async () => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => { throw new Error("denied"); } } });
    await show();
    await click("Copy the log");
    expect(container.textContent).not.toContain("copied");
  });
});
