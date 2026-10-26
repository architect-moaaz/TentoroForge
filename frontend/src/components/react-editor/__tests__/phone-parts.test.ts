import { describe, expect, it } from "vitest";

import { fieldsOf, findPart, isScreenRoot, opFor, screenOf } from "../phoneParts";
import type { PhonePart } from "../types";

const part = (over: Partial<PhonePart>): PhonePart => ({ id: "r0", parent: null, type: "Text", kind: "component", line: 1, props: [], ...over });

const nodes: Record<string, PhonePart> = {
  r0: part({ id: "r0", type: "ScreenView", line: 10, props: [{ name: "title", kind: "string", value: "Shopping List" }, { name: "loading", kind: "expr", value: "list.loading" }] }),
  "r0.0": part({ id: "r0.0", parent: "r0", type: "Text", line: 11, text: "{count} to buy", textEditable: false }),
  "r0.1": part({ id: "r0.1", parent: "r0", type: "Text", line: 12, text: "Add what you need", textEditable: true, props: [{ name: "variant", kind: "string", value: "body" }] }),
  "r0.2": part({ id: "r0.2", parent: "r0", type: "Button", line: 14, text: "Add", textEditable: true }),
  "coupons:r0": part({ id: "coupons:r0", parent: "r0", type: "Text", line: 3, text: "Coupons", textEditable: true, file: "part:coupons" }),
};
for (const n of Object.values(nodes)) if (!n.file) n.file = "view";

describe("which screen a click belongs to", () => {
  it("knows a screen's own file and a part's", () => {
    expect(screenOf("src/screens/PAGE-001.tsx")).toEqual({ page: "PAGE-001", part: null });
    expect(screenOf("src/screens/PAGE-007/coupons.tsx")).toEqual({ page: "PAGE-007", part: "coupons" });
    expect(screenOf("native\\src\\screens\\PAGE-002.tsx")).toEqual({ page: "PAGE-002", part: null });
  });
  it("is not fooled by a route file or the kit", () => {
    expect(screenOf("app/(tabs)/index.tsx")).toBeNull();
    expect(screenOf("src/ui/Button.tsx")).toBeNull();
    expect(screenOf(null)).toBeNull();
  });
});

describe("finding the part that was clicked", () => {
  const at = (line: number, component: string | null, file = "src/screens/PAGE-001.tsx") => findPart(nodes, { file, line, component });
  it("is the one of that kind on that line", () => {
    expect(at(12, "Text")?.id).toBe("r0.1");
    expect(at(14, "Button")?.id).toBe("r0.2");
    expect(at(10, "ScreenView")?.id).toBe("r0");
  });
  it("is nothing when the line holds another kind of part, or nothing", () => {
    expect(at(12, "Button")).toBeNull();
    expect(at(99, "Text")).toBeNull();
    expect(findPart(nodes, null)).toBeNull();
  });
  it("looks in a part's own file for a click that came from it", () => {
    expect(at(3, "Text", "src/screens/PAGE-001/coupons.tsx")?.id).toBe("coupons:r0");
    expect(at(3, "Text")).toBeNull();
  });
});

describe("what can be typed over", () => {
  const words = ["title", "label", "placeholder"];
  it("is a part's plain words and its settings that hold words", () => {
    expect(fieldsOf(nodes["r0.1"], words)).toEqual([{ kind: "text", name: "", label: "Words", value: "Add what you need" }]);
    expect(fieldsOf(nodes.r0, words)).toEqual([{ kind: "prop", name: "title", label: "Title", value: "Shopping List" }]);
  });
  it("is not words that come from data, and not a choice the kit makes", () => {
    expect(fieldsOf(nodes["r0.0"], words)).toEqual([]);
    expect(fieldsOf(nodes["r0.1"], words).some((f) => f.name === "variant")).toBe(false);
  });
  it("asks the server for exactly the change that was typed", () => {
    const [title] = fieldsOf(nodes.r0, words);
    expect(opFor(nodes.r0, title, "My list")).toEqual({ op: "setProp", id: "r0", name: "title", value: { kind: "string", value: "My list" } });
    const [text] = fieldsOf(nodes["r0.1"], words);
    expect(opFor(nodes["r0.1"], text, "Hi")).toEqual({ op: "setText", id: "r0.1", text: "Hi" });
  });
  it("knows the screen itself is not a part to copy or delete", () => {
    expect(isScreenRoot(nodes.r0)).toBe(true);
    expect(isScreenRoot(nodes["r0.1"])).toBe(false);
    expect(isScreenRoot(part({ id: "r0@footer.0", parent: "r0", slot: "footer" }))).toBe(true);
    expect(isScreenRoot(part({ id: "r0@footer.0.1", parent: "r0@footer.0" }))).toBe(false);
  });
});
