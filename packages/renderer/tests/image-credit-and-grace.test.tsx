// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import React from "react";
import { Image, GRACE_MS, splitCredit } from "../src/nodes/primitive/Image";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("splitCredit never throws on a malformed credit", () => {
  it("handles broken escapes, a lone %, and an empty credit", () => {
    for (const bad of ["%E0%A4%A", "%", "%%", "%zz", "Ann%20", ""]) {
      const r = splitCredit(`https://x/y.png#credit=${bad}`);
      expect(r.url).toBe("https://x/y.png");
    }
    expect(splitCredit("https://x/y.png#credit=").credit).toBeUndefined();
    expect(splitCredit("https://x/y.png#credit=%20&credit_link=").credit).toBeUndefined();
    expect(splitCredit("https://x/y.png#credit=Ann%20Lee").credit?.name).toBe("Ann Lee");
    expect(splitCredit("https://x/y.png")).toEqual({ url: "https://x/y.png" });
  });
});

describe("the grace timer", () => {
  it("a normal image sets no timer at all", () => {
    const spy = vi.spyOn(globalThis, "setTimeout");
    render(<Image node={{ id: "i", props: { src: "https://x/y.png", alt: "x" } }} />);
    expect(spy.mock.calls.filter((c) => c[1] === GRACE_MS)).toHaveLength(0);
  });

  it("an empty file route starts it, and a usable src cancels it", () => {
    const spy = vi.spyOn(globalThis, "setTimeout");
    const clear = vi.spyOn(globalThis, "clearTimeout");
    const { rerender } = render(<Image node={{ id: "i", props: { src: "/api/files/", alt: "x" } }} />);
    expect(spy.mock.calls.filter((c) => c[1] === GRACE_MS)).toHaveLength(1);
    rerender(<Image node={{ id: "i", props: { src: "https://x/y.png", alt: "x" } }} />);
    expect(clear).toHaveBeenCalled();
  });
});
