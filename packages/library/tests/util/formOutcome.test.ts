/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { parentPath, withDefaults, runOutcome } from "../../src/util/formOutcome";

// ─────────────────────────────────────────────────────────────────────────────
// parentPath — deterministic URL derivation
// ─────────────────────────────────────────────────────────────────────────────

describe("parentPath", () => {
  it("goes one segment up from /candidates/new → /candidates", () => {
    expect(parentPath("/candidates/new")).toBe("/candidates");
  });

  it("goes one segment up from a deeper path", () => {
    expect(parentPath("/candidates/[id]/edit")).toBe("/candidates/[id]");
  });

  it("returns root for a single-segment path (nothing sensible to go up to)", () => {
    expect(parentPath("/schedule-assessment")).toBe("/");
  });

  it("returns root for the root path", () => {
    expect(parentPath("/")).toBe("/");
  });

  it("strips query strings and hashes before deriving the parent", () => {
    expect(parentPath("/candidates/new?ref=nav#top")).toBe("/candidates");
  });

  it("reads window.location.pathname when no arg is supplied", () => {
    const originalPathname = window.location.pathname;
    // jsdom lets us mutate this via history.pushState.
    window.history.pushState({}, "", "/orders/new");
    try {
      expect(parentPath()).toBe("/orders");
    } finally {
      window.history.pushState({}, "", originalPathname);
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// withDefaults — per-field merge, caller wins
// ─────────────────────────────────────────────────────────────────────────────

describe("withDefaults", () => {
  it("fills BOTH fields when action is undefined", () => {
    expect(
      withDefaults(undefined, { toast: "Saved", navigate: "/list" })
    ).toEqual({ toast: "Saved", navigate: "/list" });
  });

  it("caller-supplied fields override defaults per field, others fill in", () => {
    expect(
      withDefaults({ toast: "Custom" }, { toast: "Saved", navigate: "/list" })
    ).toEqual({ toast: "Custom", navigate: "/list" });
  });

  it("passing an explicit empty object still gets both defaults", () => {
    expect(
      withDefaults({}, { toast: "Saved", navigate: "/list" })
    ).toEqual({ toast: "Saved", navigate: "/list" });
  });

  it("null toast/navigate from the caller are treated as unset → defaults win", () => {
    expect(
      withDefaults(
        { toast: undefined, navigate: undefined },
        { toast: "Saved", navigate: "/list" },
      )
    ).toEqual({ toast: "Saved", navigate: "/list" });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// runOutcome — navigate + toast side effects
// ─────────────────────────────────────────────────────────────────────────────

describe("runOutcome", () => {
  let setTimeoutSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // Verify navigation intent by spying on setTimeout — that's the seam
    // runOutcome uses to defer the redirect one microtask so a toast has
    // time to register. Direct window.location.href mutation is not
    // reliably interceptable across jsdom versions.
    setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
  });

  afterEach(() => {
    setTimeoutSpy.mockRestore();
  });

  it("is a no-op when action is undefined", () => {
    // Must not throw AND must not schedule anything.
    expect(() => runOutcome(undefined, "success")).not.toThrow();
    expect(setTimeoutSpy).not.toHaveBeenCalled();
  });

  it("schedules a deferred navigate when navigate is set", () => {
    runOutcome({ navigate: "/candidates" }, "success");
    // Navigation goes through setTimeout so the toast has time to register.
    expect(setTimeoutSpy).toHaveBeenCalled();
    const [callback, delay] = setTimeoutSpy.mock.calls[0];
    expect(typeof callback).toBe("function");
    expect(delay).toBeGreaterThan(0);
  });

  it("does NOT throw for either kind when only toast is set (browser render is verified out-of-band)", () => {
    // Real toast rendering happens via sonner (peer dep in the standalone-
    // app template); vitest/jsdom doesn't have sonner installed, so the
    // module falls through its inner catch. The critical guarantee we
    // test here is that neither kind crashes the caller's dispatch flow.
    expect(() => runOutcome({ toast: "Saved" }, "success")).not.toThrow();
    expect(() => runOutcome({ toast: "Failed" }, "error")).not.toThrow();
  });

  it("schedules navigate when BOTH fields are set (toast is best-effort)", () => {
    runOutcome({ toast: "Done", navigate: "/list" }, "success");
    expect(setTimeoutSpy).toHaveBeenCalled();
  });
});
