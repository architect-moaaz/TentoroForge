/**
 * TourOverlay — Spec E Wave 3.
 *
 * Covers: initial render, dismissal via Skip, and localStorage
 * persistence preventing re-open.
 */
import { describe, it, expect, afterEach, beforeEach } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import * as React from "react";

import { TourOverlay } from "../../src/components/TourOverlay/TourOverlay";

// jsdom in this repo ships an incomplete localStorage. Provide a minimal
// in-memory shim so the component's storage-backed dismissal is testable.
function installLocalStorageShim() {
  const store: Record<string, string> = {};
  const shim = {
    getItem: (k: string) => (k in store ? store[k] : null),
    setItem: (k: string, v: string) => { store[k] = String(v); },
    removeItem: (k: string) => { delete store[k]; },
    clear: () => { for (const k of Object.keys(store)) delete store[k]; },
    key: (i: number) => Object.keys(store)[i] ?? null,
    get length() { return Object.keys(store).length; },
  };
  Object.defineProperty(window, "localStorage", { value: shim, configurable: true });
  return shim;
}

const steps = [
  { target: "#target", title: "Welcome", body: "Take the tour", placement: "auto" as const },
];

describe("TourOverlay", () => {
  beforeEach(() => {
    installLocalStorageShim();
    // Provide a target
    document.body.innerHTML = '<div id="target" style="width:100px;height:100px"></div>';
  });
  afterEach(() => cleanup());

  it("auto-starts the tour on first mount", () => {
    const { container, getByText } = render(<TourOverlay steps={steps} storageKey="test-tour" />);
    expect(container.querySelector("[data-forge-tour-overlay]")).not.toBeNull();
    getByText("Welcome");
  });

  it("Skip button dismisses and persists to localStorage", () => {
    const { container, getByText, rerender } = render(
      <TourOverlay steps={steps} storageKey="test-tour" />,
    );
    fireEvent.click(getByText("Skip"));
    expect(container.querySelector("[data-forge-tour-overlay]")).toBeNull();
    expect(window.localStorage.getItem("test-tour")).toBe("done");
    // Re-mount — the overlay should NOT reopen.
    cleanup();
    const { container: c2 } = render(
      <TourOverlay steps={steps} storageKey="test-tour" />,
    );
    expect(c2.querySelector("[data-forge-tour-overlay]")).toBeNull();
  });

  it("Done on the last step also dismisses", () => {
    const { container, getByText } = render(
      <TourOverlay steps={steps} storageKey="test-tour-2" />,
    );
    fireEvent.click(getByText("Done"));
    expect(container.querySelector("[data-forge-tour-overlay]")).toBeNull();
    expect(window.localStorage.getItem("test-tour-2")).toBe("done");
  });
});
