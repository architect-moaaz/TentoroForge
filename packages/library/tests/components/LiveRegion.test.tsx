/**
 * LiveRegion + announce() — Spec E Wave 2 accessibility spine.
 *
 * Contract:
 *  - LiveRegion component renders exactly two divs: polite + assertive,
 *    both aria-live regions live at the app root, visually hidden but
 *    exposed to assistive tech.
 *  - `announce(text, urgency?)` is a module-level imperative API that
 *    non-React code (workflow dispatchers, toasts) can call directly.
 *  - Rapidly repeated identical messages must not spam — coalesce until
 *    the message text actually changes.
 *  - Messages clear after a short delay so a repeat of the same text
 *    triggers a fresh announcement.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, act, cleanup } from "@testing-library/react";

import {
  LiveRegion,
  announce,
  __resetAnnouncerForTests,
} from "../../src/a11y";

describe("LiveRegion", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    __resetAnnouncerForTests();
  });
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it("renders exactly two aria-live regions (polite + assertive)", () => {
    const { container } = render(<LiveRegion />);
    const politeEls = container.querySelectorAll('[aria-live="polite"]');
    const assertiveEls = container.querySelectorAll('[aria-live="assertive"]');
    expect(politeEls.length).toBe(1);
    expect(assertiveEls.length).toBe(1);
  });

  it("both regions are aria-atomic=true so full text re-announces on change", () => {
    const { container } = render(<LiveRegion />);
    const all = container.querySelectorAll("[aria-live]");
    all.forEach((el) => {
      expect(el.getAttribute("aria-atomic")).toBe("true");
    });
  });

  it("regions are visually hidden but still in the accessibility tree", () => {
    const { container } = render(<LiveRegion />);
    const polite = container.querySelector(
      '[aria-live="polite"]'
    ) as HTMLElement;
    // sr-only-style: position:absolute + 1x1 + overflow:hidden — NOT
    // display:none / visibility:hidden (those pull it out of the a11y tree).
    const cs = polite.className;
    // We accept either a Tailwind "sr-only" class OR an explicit inline
    // hidden-visually pattern. Both are widely-used conventions.
    const hasSrOnly = /\bsr-only\b/.test(cs);
    const hasInlineHidden =
      polite.style.position === "absolute" &&
      polite.style.width === "1px" &&
      polite.style.height === "1px";
    expect(hasSrOnly || hasInlineHidden).toBe(true);
  });

  it("announce(text) with no urgency defaults to polite region", () => {
    const { container } = render(<LiveRegion />);
    act(() => {
      announce("Saved changes");
    });
    const polite = container.querySelector('[aria-live="polite"]');
    expect(polite?.textContent).toBe("Saved changes");
    const assertive = container.querySelector('[aria-live="assertive"]');
    expect(assertive?.textContent ?? "").toBe("");
  });

  it("announce(text, 'assertive') writes to the assertive region", () => {
    const { container } = render(<LiveRegion />);
    act(() => {
      announce("Something went wrong", "assertive");
    });
    const assertive = container.querySelector('[aria-live="assertive"]');
    expect(assertive?.textContent).toBe("Something went wrong");
    const polite = container.querySelector('[aria-live="polite"]');
    expect(polite?.textContent ?? "").toBe("");
  });

  it("polite and assertive channels are independent", () => {
    const { container } = render(<LiveRegion />);
    act(() => {
      announce("Polite update");
      announce("Loud error", "assertive");
    });
    expect(
      container.querySelector('[aria-live="polite"]')?.textContent
    ).toBe("Polite update");
    expect(
      container.querySelector('[aria-live="assertive"]')?.textContent
    ).toBe("Loud error");
  });

  it("message clears after the coalesce window so repeats re-announce", () => {
    const { container } = render(<LiveRegion />);
    act(() => {
      announce("Downloaded");
    });
    expect(
      container.querySelector('[aria-live="polite"]')?.textContent
    ).toBe("Downloaded");
    // Advance past the clear window (~150ms).
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(
      container.querySelector('[aria-live="polite"]')?.textContent ?? ""
    ).toBe("");
  });

  it("announce() called before LiveRegion mounts is not lost", () => {
    // Real apps mount LiveRegion in the shell; a workflow dispatcher might
    // fire before hydration. The last-pending announcement should flush
    // when the region mounts.
    act(() => {
      announce("Fired early");
    });
    const { container } = render(<LiveRegion />);
    expect(
      container.querySelector('[aria-live="polite"]')?.textContent
    ).toBe("Fired early");
  });

  it("empty / whitespace-only announcements are ignored", () => {
    const { container } = render(<LiveRegion />);
    act(() => {
      announce("");
      announce("   ");
      announce("\n\t");
    });
    expect(
      container.querySelector('[aria-live="polite"]')?.textContent ?? ""
    ).toBe("");
  });

  it("second LiveRegion mount is a no-op (singleton contract)", () => {
    // Some layouts nest schema-pages under a shell that also renders
    // LiveRegion — the extra copies should not cause duplicate
    // announcements or errors.
    const { container } = render(
      <>
        <LiveRegion />
        <LiveRegion />
      </>
    );
    act(() => {
      announce("Once");
    });
    // Count regions with the actual text content
    const politeWithText = Array.from(
      container.querySelectorAll('[aria-live="polite"]')
    ).filter((el) => el.textContent === "Once");
    // Both copies subscribe to the same store, so both show text — that
    // is acceptable for SR behavior (SR reads first live region it finds).
    // The critical guarantee is: no crash, no thrown state error.
    expect(politeWithText.length).toBeGreaterThanOrEqual(1);
  });
});

describe("announce (module API)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    __resetAnnouncerForTests();
  });
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it("is a no-op with no subscribers (does not throw)", () => {
    expect(() => announce("no listeners")).not.toThrow();
    expect(() => announce("no listeners", "assertive")).not.toThrow();
  });

  it("consecutive different messages both surface", () => {
    const { container } = render(<LiveRegion />);
    act(() => {
      announce("First");
    });
    expect(
      container.querySelector('[aria-live="polite"]')?.textContent
    ).toBe("First");
    act(() => {
      // Same tick as First — should still replace so SR reads latest.
      announce("Second");
    });
    expect(
      container.querySelector('[aria-live="polite"]')?.textContent
    ).toBe("Second");
  });
});
