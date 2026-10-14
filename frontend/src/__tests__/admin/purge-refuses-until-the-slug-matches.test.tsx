/**
 * A permanent action needs its name typed back: the Purge (and Delete)
 * button does nothing until the slug matches exactly, and clears when the
 * dialog closes so a second opening starts from nothing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { TypedConfirmDialog } from "@/components/admin/TypedConfirmDialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | undefined; let el: HTMLDivElement;
beforeEach(() => { el = document.createElement("div"); document.body.appendChild(el); });
afterEach(() => { if (root) act(() => root!.unmount()); root = undefined; el.remove(); });

function typeInto(input: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => { set.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
}

function render(open: boolean, onConfirm: () => void) {
  const ui = (
    <TypedConfirmDialog open={open} onOpenChange={() => {}} title="Purge Acme for good" prompt="Everything goes."
                        expected="acme-corp" confirmText="Purge" onConfirm={onConfirm} />
  );
  if (!root) act(() => { root = createRoot(el); root.render(ui); });
  else act(() => root!.render(ui));
}

const button = () => Array.from(document.querySelectorAll("button")).find((b) => b.textContent === "Purge") as HTMLButtonElement;
const input = () => document.getElementById("typed") as HTMLInputElement;

describe("typing the slug back", () => {
  it("keeps Purge disabled until the slug matches exactly, then confirms once", () => {
    const onConfirm = vi.fn();
    render(true, onConfirm);
    expect(button().disabled).toBe(true);

    typeInto(input(), "acme");
    expect(button().disabled).toBe(true);
    typeInto(input(), "Acme-Corp");
    expect(button().disabled).toBe(true);

    typeInto(input(), "acme-corp");
    expect(button().disabled).toBe(false);
    act(() => button().click());
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("forgets what was typed when the dialog closes", () => {
    render(true, vi.fn());
    typeInto(input(), "acme-corp");
    expect(button().disabled).toBe(false);
    render(false, vi.fn());
    render(true, vi.fn());
    expect(input().value).toBe("");
    expect(button().disabled).toBe(true);
  });
});
