/**
 * A credit entry is a signed amount with a reason: a top-up or opening
 * balance positive, a refund negative, an adjustment either way but never
 * nothing — and no entry without a few words saying why, because the
 * record is read later by someone who was not there.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { CreditEntryDialog, entryReady } from "@/components/admin/CreditEntryDialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("when an entry may be recorded", () => {
  it("wants the sign its kind demands", () => {
    expect(entryReady("top_up", "100", "Invoice 42")).toBe(true);
    expect(entryReady("top_up", "-100", "Invoice 42")).toBe(false);
    expect(entryReady("opening", "0", "Opening")).toBe(false);
    expect(entryReady("refund", "-25", "Refund for the failed build")).toBe(true);
    expect(entryReady("refund", "25", "Refund for the failed build")).toBe(false);
    expect(entryReady("adjustment", "-3.5", "Correcting the May figure")).toBe(true);
    expect(entryReady("adjustment", "3.5", "Correcting the May figure")).toBe(true);
    expect(entryReady("adjustment", "0", "Correcting the May figure")).toBe(false);
  });

  it("wants a reason of a few characters and a real number", () => {
    expect(entryReady("top_up", "100", "")).toBe(false);
    expect(entryReady("top_up", "100", "ok")).toBe(false);
    expect(entryReady("top_up", "100", "   ")).toBe(false);
    expect(entryReady("top_up", "", "Invoice 42")).toBe(false);
    expect(entryReady("top_up", "abc", "Invoice 42")).toBe(false);
  });
});

let root: Root | undefined; let el: HTMLDivElement;
beforeEach(() => { el = document.createElement("div"); document.body.appendChild(el); });
afterEach(() => { if (root) act(() => root!.unmount()); root = undefined; el.remove(); });

function fill(node: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const set = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  act(() => { set.call(node, value); node.dispatchEvent(new Event("input", { bubbles: true })); });
}

describe("the entry dialog", () => {
  it("records a top-up only once the amount and the reason are there", () => {
    const onSubmit = vi.fn();
    act(() => {
      root = createRoot(el);
      root!.render(<CreditEntryDialog open onOpenChange={() => {}} orgName="Acme" hasOpening onSubmit={onSubmit} />);
    });
    const record = () => Array.from(document.querySelectorAll("button")).find((b) => b.textContent === "Record entry") as HTMLButtonElement;
    expect(document.body.textContent).toContain("Credit entry for Acme");
    expect(record().disabled).toBe(true);

    fill(document.getElementById("amount") as HTMLInputElement, "150");
    expect(record().disabled).toBe(true);
    fill(document.getElementById("note") as HTMLTextAreaElement, "Invoice 42, October");
    expect(record().disabled).toBe(false);

    act(() => record().click());
    expect(onSubmit).toHaveBeenCalledWith({ amount_usd: 150, kind: "top_up", note: "Invoice 42, October" });
  });
});
