/**
 * The screen's own values.
 *
 * A calculator's display is not a column and pressing a key is not a workflow.
 * These hold the two pure halves of that — where a declared value starts, and
 * what an action makes of it — so the arithmetic can be reasoned about without
 * mounting anything.
 */
import { describe, expect, it } from "vitest";

import {
  initialValues,
  isClientAction,
  nextValue,
  nextValues,
  type ClientStateValue,
} from "../src/client/ClientState";

const DISPLAY: ClientStateValue[] = [
  { name: "display", type: "string", initial: "0" },
  { name: "count", type: "number" },
  { name: "shown", type: "boolean" },
  { name: "note", type: "string" },
];

describe("a declared value starts somewhere", () => {
  it("starts where the contract says", () => {
    expect(initialValues(DISPLAY).display).toBe("0");
  });

  it("starts at a typed empty when the contract says nothing", () => {
    // A display bound to `undefined` renders as nothing, which reads as a
    // broken screen rather than as a calculator showing zero.
    const start = initialValues(DISPLAY);
    expect(start.count).toBe(0);
    expect(start.shown).toBe(false);
    expect(start.note).toBe("");
  });

  it("declares nothing for a page that declares nothing", () => {
    expect(initialValues(undefined)).toEqual({});
    expect(initialValues([])).toEqual({});
  });
});

describe("a control changes one", () => {
  it("sets a literal — the Clear key", () => {
    expect(nextValue({ kind: "set", target: "display", value: "0" },
                     { display: "123" })).toEqual({ target: "display", value: "0" });
  });

  it("computes over what is on screen — a digit key", () => {
    expect(nextValue({ kind: "compute", target: "display", formula: "display + '7'" },
                     { display: "12" })).toEqual({ target: "display", value: "127" });
  });

  it("does the arithmetic", () => {
    expect(nextValue({ kind: "compute", target: "total", formula: "a * b" },
                     { a: 6, b: 7 })).toEqual({ target: "total", value: 42 });
  });

  it("changes nothing when the formula cannot be evaluated", () => {
    // A half-applied screen is worse than one that ignored a press.
    expect(nextValue({ kind: "compute", target: "total", formula: "((((" },
                      { a: 1 })).toBeUndefined();
  });

  it("changes nothing without a target", () => {
    expect(nextValue({ kind: "set", target: "", value: 1 } as never, {})).toBeUndefined();
  });
});

describe("telling an action from a handler", () => {
  it("recognises both kinds", () => {
    expect(isClientAction({ kind: "set", target: "display", value: "0" })).toBe(true);
    expect(isClientAction({ kind: "compute", target: "d", formula: "d" })).toBe(true);
  });

  it("refuses everything else", () => {
    expect(isClientAction(undefined)).toBe(false);
    expect(isClientAction("submit")).toBe(false);
    expect(isClientAction({ kind: "navigate", target: "/" })).toBe(false);
    expect(isClientAction({ kind: "set" })).toBe(false);
  });
});

describe("one press, several values", () => {
  const CLEAR = [
    { kind: "set", target: "display", value: "0" },
    { kind: "set", target: "error", value: false },
    { kind: "set", target: "errorMessage", value: "" },
  ] as const;

  it("applies every change of the press", () => {
    expect(nextValues(CLEAR as never, { display: "12", error: true, errorMessage: "bad" }))
      .toEqual({ display: "0", error: false, errorMessage: "" });
  });

  it("reads the state BEFORE the press, so nothing can chain", () => {
    // A list is a simultaneous assignment. If `b` could see `a`'s write this
    // would be 2; a page whose buttons are small scripts is the thing these
    // semantics exist to prevent.
    const out = nextValues(
      [{ kind: "compute", target: "a", formula: "n + 1" },
       { kind: "compute", target: "b", formula: "a + 1" }] as never,
      { n: 0, a: 0, b: 0 },
    );
    expect(out).toEqual({ a: 1, b: 1 });
  });

  it("one bad formula does not stop the others", () => {
    const out = nextValues(
      [{ kind: "set", target: "display", value: "0" },
       { kind: "compute", target: "error", formula: "((((" }] as never,
      { display: "7", error: true },
    );
    expect(out).toEqual({ display: "0" });
  });

  it("a single action still works unwrapped", () => {
    expect(nextValues({ kind: "set", target: "display", value: "0" } as never,
                      { display: "9" })).toEqual({ display: "0" });
  });
});
