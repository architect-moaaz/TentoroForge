import { describe, expect, it } from "vitest";

import { marginOf, readSpace, sizeNamed, spaceOp } from "../phoneSpace";
import type { PhonePart } from "../types";

const part = (style?: { kind: string; value: unknown }): PhonePart => ({
  id: "n1", parent: "n0", type: "Stack", kind: "element", line: 5,
  props: style ? [{ name: "style", ...style }] : [],
});

describe("the space around a part is read from its style", () => {
  it("is nothing when the part has no style", () => {
    expect(readSpace(part())).toEqual({ margins: {}, rest: [], fromCode: false });
  });

  it("reads margin numbers and keeps every other entry as written", () => {
    const got = readSpace(part({ kind: "expr", value: '{ marginTop: 16, color: "red", marginLeft: -4.5, ...extra }' }));
    expect(got.margins).toEqual({ marginTop: 16, marginLeft: -4.5 });
    expect(got.rest).toEqual(['color: "red"', "...extra"]);
    expect(got.fromCode).toBe(false);
  });

  it("does not split an entry at a comma inside brackets or quotes", () => {
    expect(readSpace(part({ kind: "expr", value: '{ transform: [{ scale: 1 }, { rotate: "1deg" }], label: "a, b" }' })).rest)
      .toEqual(['transform: [{ scale: 1 }, { rotate: "1deg" }]', 'label: "a, b"']);
  });

  it("leaves a style the screen's code decides alone", () => {
    expect(readSpace(part({ kind: "expr", value: "styles.card" })).fromCode).toBe(true);
    expect(readSpace(part({ kind: "expr", value: "[styles.a, { marginTop: 4 }]" })).fromCode).toBe(true);
    expect(readSpace(part({ kind: "expr", value: "{ marginTop: theme.space.md }" })).fromCode).toBe(true);
    expect(readSpace(part({ kind: "string", value: "x" })).fromCode).toBe(true);
  });
});

describe("the change that sets the space", () => {
  it("writes the sides that have a number, in the order top, right, bottom, left, after the rest of the style", () => {
    expect(spaceOp(part(), { marginLeft: 8, marginTop: 16 }, ['color: "red"'])).toEqual({
      op: "setProp", id: "n1", name: "style", value: { kind: "expr", value: '{ color: "red", marginTop: 16, marginLeft: 8 }' },
    });
  });

  it("writes an empty style when nothing is left", () => {
    expect(spaceOp(part(), {}, [])).toMatchObject({ value: { kind: "expr", value: "{}" } });
  });

  it("reads and writes paddings beside margins", () => {
    const got = readSpace(part({ kind: "expr", value: "{ paddingLeft: 8, marginTop: 4 }" }));
    expect(got.margins).toEqual({ paddingLeft: 8, marginTop: 4 });
    expect(spaceOp(part(), { paddingBottom: 12, marginTop: 4 }, [])).toMatchObject({ value: { value: "{ marginTop: 4, paddingBottom: 12 }" } });
  });

  it("keeps a margin of zero", () => {
    expect(spaceOp(part(), { marginTop: 0 }, [])).toMatchObject({ value: { value: "{ marginTop: 0 }" } });
  });
});

describe("what is typed in a side's box", () => {
  it("is no margin when empty, a number when it is one, and refused otherwise", () => {
    expect(marginOf("")).toBeUndefined();
    expect(marginOf(" 16 ")).toBe(16);
    expect(marginOf("-4.5")).toBe(-4.5);
    expect(marginOf("1e3")).toBe("bad");
    expect(marginOf("12px")).toBe("bad");
    expect(marginOf("9999")).toBe("bad");
  });

  it("names the steps of the design system's spacing", () => {
    expect(sizeNamed(16)).toBe("md");
    expect(sizeNamed(48)).toBe("xxl");
    expect(sizeNamed(10)).toBeNull();
    expect(sizeNamed(undefined)).toBeNull();
  });
});
