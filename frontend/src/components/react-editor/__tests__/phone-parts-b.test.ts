import { describe, expect, it } from "vitest";

import {
  GUIDED_PARTS, holderIdOf, rowVarAt, addOps, newPartAfterAdd, resolveDrop, choiceOp, choicesOf, dropOp, dropPlace, outlineOf, placeFor, searchPalette, settingLabel, sourceOfPart, stepOp, valueLabel, zoneAt,
} from "../phoneParts";
import type { PalettePart, PhoneKit, PhonePart } from "../types";

const part = (over: Partial<PhonePart>): PhonePart => ({ id: "r0", parent: null, type: "Text", kind: "component", line: 1, props: [], file: "view", ...over });

// <ScreenView title="x" footer={<Stack>..</Stack>}> <Text/> <Text/> <Row><Button/></Row> <Text/> </ScreenView>
const nodes: Record<string, PhonePart> = {
  r0: part({ id: "r0", type: "ScreenView", children: ["r0.0", "r0.1", "r0.2", "r0.3"] }),
  "r0.0": part({ id: "r0.0", parent: "r0", type: "Text", line: 2, text: "First", textEditable: true, props: [{ name: "variant", kind: "string", value: "body" }] }),
  "r0.1": part({ id: "r0.1", parent: "r0", type: "Text", line: 3, text: "Second" }),
  "r0.2": part({ id: "r0.2", parent: "r0", type: "Row", line: 4, children: ["r0.2.0"], props: [{ name: "wrap", kind: "true", value: null }, { name: "gap", kind: "expr", value: "space" }] }),
  "r0.2.0": part({ id: "r0.2.0", parent: "r0.2", type: "Button", line: 5, props: [{ name: "variant", kind: "string", value: "accent" }, { name: "size", kind: "expr", value: "big" }] }),
  "r0.3": part({ id: "r0.3", parent: "r0", type: "Text", line: 6, text: "Last" }),
  "r0@footer.0": part({ id: "r0@footer.0", parent: "r0", type: "Stack", line: 8, slot: "footer", children: [] }),
};
const imports = { ScreenView: "Screen", Text: "Text", Row: "Row", Button: "Button", Stack: "Stack" };

const kit: PhoneKit = {
  ok: true, lists: { icons: ["star", "cart"] }, palette: [], containers: ["Screen", "Stack", "Row", "Card"],
  components: {
    Button: { props: { variant: { kind: "enum", values: ["accent", "ghost"], optional: true }, size: { kind: "enum", values: ["sm", "md"], optional: true },
                       icon: { kind: "enum", values: [], list: "icons", optional: true } } },
    Row: { props: { wrap: { kind: "boolean", values: [], optional: true }, gap: { kind: "enum", values: ["xs", "sm"], alsoNumber: true, optional: true } } },
    Text: { props: { variant: { kind: "enum", values: ["body", "caption"], optional: true } } },
  },
};

describe("the look a part can have", () => {
  it("lists the settings the kit gives the part, with what it has now", () => {
    const button = choicesOf(nodes["r0.2.0"], kit, imports);
    expect(button.map((c) => c.name)).toEqual(["variant", "size", "icon"]);
    expect(button[0]).toMatchObject({ label: "Style", current: "accent", fromCode: false, optional: true });
    expect(button[2]).toMatchObject({ list: "icons", current: null });
  });
  it("says when the screen's own code decides a setting, and leaves it alone", () => {
    expect(choicesOf(nodes["r0.2.0"], kit, imports).find((c) => c.name === "size")?.fromCode).toBe(true);
    expect(choicesOf(nodes["r0.2"], kit, imports).find((c) => c.name === "gap")?.fromCode).toBe(true);
  });
  it("reads a bare switch as on, and one that is absent as the default", () => {
    expect(choicesOf(nodes["r0.2"], kit, imports).find((c) => c.name === "wrap")?.current).toBe(true);
    expect(choicesOf(nodes["r0.0"], kit, imports)[0].current).toBe("body");
  });
  it("offers nothing for a part the kit has no choices for, or when the kit could not be read", () => {
    expect(choicesOf(nodes["r0.1"], { ...kit, components: {} }, imports)).toEqual([]);
    expect(choicesOf(nodes["r0.2"], { ...kit, ok: false }, imports)).toEqual([]);
    expect(choicesOf(nodes["r0.2"], null, imports)).toEqual([]);
  });
  it("asks the server for a word, a switch, or taking the setting away", () => {
    const [variant] = choicesOf(nodes["r0.2.0"], kit, imports);
    expect(choiceOp(nodes["r0.2.0"], variant, "ghost")).toEqual({ op: "setProp", id: "r0.2.0", name: "variant", value: { kind: "string", value: "ghost" } });
    expect(choiceOp(nodes["r0.2.0"], variant, null)).toEqual({ op: "setProp", id: "r0.2.0", name: "variant", value: null });
    const wrap = choicesOf(nodes["r0.2"], kit, imports).find((c) => c.name === "wrap")!;
    expect(choiceOp(nodes["r0.2"], wrap, true)).toEqual({ op: "setProp", id: "r0.2", name: "wrap", value: { kind: "true" } });
    expect(choiceOp(nodes["r0.2"], wrap, false)).toEqual({ op: "setProp", id: "r0.2", name: "wrap", value: null });
  });
  it("says it in words a person uses", () => {
    expect(settingLabel("variant")).toBe("Style");
    expect(settingLabel("fullWidth")).toBe("Full width");
    expect(settingLabel("someNewThing")).toBe("Some New Thing");
    expect(valueLabel("xl")).toBe("Extra large");
    expect(valueLabel("in_progress")).toBe("In progress");
  });
});

describe("putting a part in another place", () => {
  it("steps one place up or down among its brothers, counted before it is lifted out", () => {
    expect(stepOp(nodes, nodes["r0.1"], -1)).toEqual({ op: "move", id: "r0.1", parentId: "r0", index: 0 });
    expect(stepOp(nodes, nodes["r0.1"], 1)).toEqual({ op: "move", id: "r0.1", parentId: "r0", index: 3 });
  });
  it("does not step past either end, and the screen and what a setting holds do not move", () => {
    expect(stepOp(nodes, nodes["r0.0"], -1)).toBeNull();
    expect(stepOp(nodes, nodes["r0.3"], 1)).toBeNull();
    expect(stepOp(nodes, nodes.r0, 1)).toBeNull();
    expect(stepOp(nodes, nodes["r0@footer.0"], 1)).toBeNull();
  });
  it("drops a part before or after another beside it", () => {
    expect(dropOp(nodes, "r0.3", "r0.0", "before")).toEqual({ op: "move", id: "r0.3", parentId: "r0", index: 0 });
    expect(dropOp(nodes, "r0.0", "r0.3", "after")).toEqual({ op: "move", id: "r0.0", parentId: "r0", index: 4 });
    expect(dropOp(nodes, "r0.0", "r0.2", "before")).toEqual({ op: "move", id: "r0.0", parentId: "r0", index: 2 });
  });
  it("does nothing when the drop leaves the part where it is", () => {
    expect(dropOp(nodes, "r0.1", "r0.0", "after")).toBeNull();
    expect(dropOp(nodes, "r0.1", "r0.2", "before")).toBeNull();
    expect(dropOp(nodes, "r0.1", "r0.1", "before")).toBeNull();
  });
  it("is only among brothers: not into another part, not onto what a setting holds", () => {
    expect(dropOp(nodes, "r0.0", "r0.2.0", "before")).toBeNull();
    expect(dropOp(nodes, "r0.0", "r0@footer.0", "after")).toBeNull();
    expect(dropOp(nodes, "r0@footer.0", "r0.0", "before")).toBeNull();
  });
});

describe("adding a ready part", () => {
  const badge: PalettePart = { id: "badge", label: "Badge", category: "Content", description: "A small coloured label", search: ["pill"],
                               jsx: "<Badge>New</Badge>", imports: ["Badge"], container: false, drawnOnly: false };
  it("goes inside the picked part when it can hold others", () => {
    expect(placeFor(nodes, imports, kit.containers, nodes["r0.2"])).toEqual({ op: { parentId: "r0.2" }, says: "inside the selected Row" });
  });
  it("goes after the picked part when that cannot hold others", () => {
    expect(placeFor(nodes, imports, kit.containers, nodes["r0.1"])).toEqual({ op: { afterId: "r0.1" }, says: "after the selected Text" });
  });
  it("goes at the end of the screen when nothing is picked, or what is picked is held by a setting and cannot hold it", () => {
    expect(placeFor(nodes, imports, kit.containers, null)).toEqual({ op: { parentId: "r0" }, says: "at the end of the screen" });
    expect(placeFor(nodes, imports, ["Screen"], nodes["r0@footer.0"])).toEqual({ op: { parentId: "r0" }, says: "at the end of the screen" });
  });
  it("is nowhere when the screen has no part that can hold it", () => {
    expect(placeFor(nodes, imports, [], null)).toBeNull();
  });
  it("asks the server to import it from the kit and then add it", () => {
    expect(addOps(badge, { op: { parentId: "r0" }, says: "" })).toEqual([
      { op: "addImport", source: "@/ui", names: ["Badge"] },
      { op: "insert", jsx: "<Badge>New</Badge>", parentId: "r0" },
    ]);
  });
  it("is found by name, description, group or a word people search by", () => {
    const palette = [badge, { ...badge, id: "tag", label: "Tag", description: "Outlined", category: "Form", search: ["chip"] }];
    expect(searchPalette(palette, "").length).toBe(2);
    expect(searchPalette(palette, "pill").map((p) => p.id)).toEqual(["badge"]);
    expect(searchPalette(palette, "CHIP").map((p) => p.id)).toEqual(["tag"]);
    expect(searchPalette(palette, "form").map((p) => p.id)).toEqual(["tag"]);
    expect(searchPalette(palette, "zzz")).toEqual([]);
  });
});

describe("the outline", () => {
  it("lists the parts in the order they are written, indented, a held part after its owner", () => {
    expect(outlineOf(nodes).map((r) => [r.part.id, r.depth])).toEqual([
      ["r0", 0], ["r0.0", 1], ["r0.1", 1], ["r0.2", 1], ["r0.2.0", 2], ["r0.3", 1], ["r0@footer.0", 1],
    ]);
  });
  it("names where a picked part is, so the Change tab can find it", () => {
    expect(sourceOfPart("PAGE-001", nodes["r0.1"])).toEqual({ file: "src/screens/PAGE-001.tsx", line: 3, component: "Text" });
    expect(sourceOfPart("PAGE-001", part({ file: "part:coupons", line: 9, type: "Text" })))
      .toEqual({ file: "src/screens/PAGE-001/coupons.tsx", line: 9, component: "Text" });
  });
});


describe("dropping a ready part on the screen", () => {
  const holders = kit.containers;
  it("reads where the pointer is: a part that can hold others is dropped into in its middle, beside it near the edges", () => {
    expect(zoneAt(0.1, true)).toBe("before");
    expect(zoneAt(0.5, true)).toBe("inside");
    expect(zoneAt(0.9, true)).toBe("after");
    expect(zoneAt(0.2, false)).toBe("before");
    expect(zoneAt(0.8, false)).toBe("after");
  });
  it("goes into a part that can hold it", () => {
    expect(dropPlace(nodes, imports, holders, nodes["r0.2"], "inside")).toEqual({ op: { parentId: "r0.2" }, says: "inside the Row" });
    expect(dropPlace(nodes, imports, holders, nodes["r0@footer.0"], "inside")).toEqual({ op: { parentId: "r0@footer.0" }, says: "inside the Stack" });
  });
  it("goes before or after a part whose parent can hold it", () => {
    expect(dropPlace(nodes, imports, holders, nodes["r0.1"], "before")).toEqual({ op: { beforeId: "r0.1" }, says: "before the Text" });
    expect(dropPlace(nodes, imports, holders, nodes["r0.1"], "after")).toEqual({ op: { afterId: "r0.1" }, says: "after the Text" });
    expect(dropPlace(nodes, imports, holders, nodes["r0.2.0"], "after")).toEqual({ op: { afterId: "r0.2.0" }, says: "after the Button" });
  });
  it("has no place on something that cannot hold it", () => {
    expect(dropPlace(nodes, imports, holders, nodes["r0.1"], "inside")).toBeNull();
    expect(dropPlace(nodes, imports, holders, nodes["r0.2.0"], "inside")).toBeNull();
  });
  it("has no 'beside' for the screen itself, nor for a part a setting holds", () => {
    expect(dropPlace(nodes, imports, holders, nodes.r0, "before")).toEqual({ op: { parentId: "r0" }, says: "inside the ScreenView" });
    expect(dropPlace(nodes, imports, holders, nodes["r0@footer.0"], "after")).toEqual({ op: { parentId: "r0@footer.0" }, says: "inside the Stack" });
    expect(dropPlace(nodes, imports, [], nodes["r0.1"], "before")).toBeNull();
  });
});


describe("what a drop on the picture means", () => {
  const field: PalettePart = { id: "text-field", label: "Text field", category: "Form", description: "", search: [], jsx: "<TextField />", imports: ["TextField"],
                               container: false, drawnOnly: true };
  const kitWith: PhoneKit = { ...kit, palette: [field] };
  const on = (line: number, component: string, rel: number, extra: Partial<Parameters<typeof resolveDrop>[0]> = {}) =>
    resolveDrop({ nodes, imports, kit: kitWith, dragging: null, partId: "text-field", source: { file: "src/screens/PAGE-001.tsx", line, component }, rel, ...extra });

  it("takes the part from the drag itself, so it still works after the editor has forgotten which part it was", () => {
    // A browser ends the drag (and the editor clears its record) before the picture's message about the drop arrives.
    const out = on(4, "Row", 0.5);
    expect(out).toMatchObject({ part: { id: "text-field" }, place: { op: { parentId: "r0.2" } } });
  });
  it("falls back to the part the editor is dragging when the picture did not say (an older picture)", () => {
    expect(on(4, "Row", 0.5, { partId: undefined, dragging: field })).toMatchObject({ part: { id: "text-field" } });
  });
  it("says so when it was not a part from the Add list", () => {
    expect(on(4, "Row", 0.5, { partId: "", dragging: null })).toEqual({ why: "That was not a part from the Add list." });
    expect(on(4, "Row", 0.5, { partId: "no-such-part", dragging: null })).toMatchObject({ why: expect.stringContaining("not a part") });
  });
  it("says so when what was under the pointer is drawn by the app itself", () => {
    expect(resolveDrop({ nodes, imports, kit: kitWith, dragging: null, partId: "text-field", source: null, rel: 0.5 })).toMatchObject({ why: expect.stringContaining("drawn by the app itself") });
    expect(resolveDrop({ nodes, imports, kit: kitWith, dragging: null, partId: "text-field", source: { file: "app/(tabs)/_layout.tsx", line: 38, component: "Tabs" }, rel: 0.5 }))
      .toMatchObject({ why: expect.stringContaining("drawn by the app itself") });
  });
  it("says so when the part is not in the screen's code, or the screen is not read yet", () => {
    expect(on(99, "Row", 0.5)).toMatchObject({ why: expect.stringContaining("could not be found") });
    expect(on(4, "Row", 0.5, { nodes: null })).toMatchObject({ why: expect.stringContaining("still being read") });
  });
  it("names the part that has no place for it", () => {
    expect(on(2, "Text", 0.3)).toMatchObject({ place: { op: { beforeId: "r0.0" } } });          // a Text is only dropped beside it
    expect(on(2, "Text", 0.7)).toMatchObject({ place: { op: { afterId: "r0.0" } } });
    expect(on(5, "Button", 0.5, { imports: { ...imports, Row: "Nope" } })).toMatchObject({ why: expect.stringContaining("Button") });
  });
});


describe("finding the part that was just added", () => {
  // The screen after "a Heading was added" in each place; the new part is named by its place.
  const after = (id: string): Record<string, PhonePart> => ({ ...nodes, [id]: part({ id, type: "Text", text: "New heading" }) });
  it("is the last child when it was added inside a part", () => {
    expect(newPartAfterAdd(nodes, { op: { parentId: "r0.2" }, says: "" }, after("r0.2.1"))?.id).toBe("r0.2.1");
    expect(newPartAfterAdd(nodes, { op: { parentId: "r0" }, says: "" }, after("r0.4"))?.id).toBe("r0.4");
  });
  it("takes the place of the brother it was dropped in front of", () => {
    expect(newPartAfterAdd(nodes, { op: { beforeId: "r0.1" }, says: "" }, after("r0.1"))?.id).toBe("r0.1");
  });
  it("is the one after the brother it was dropped behind", () => {
    expect(newPartAfterAdd(nodes, { op: { afterId: "r0.1" }, says: "" }, after("r0.2"))?.id).toBe("r0.2");
  });
  it("is nothing when the screen does not have it where it should be", () => {
    expect(newPartAfterAdd(nodes, { op: { parentId: "r0.2" }, says: "" }, nodes)).toBeNull();
    expect(newPartAfterAdd(nodes, { op: { afterId: "nope" }, says: "" }, nodes)).toBeNull();
  });
});

describe("the guided parts", () => {
  const inRow: Record<string, PhonePart> = {
    ...nodes,
    "r0.1@renderItem.0": part({ id: "r0.1@renderItem.0", parent: "r0.1", type: "Row", slot: "renderItem", rowVar: "item", children: ["r0.1@renderItem.0.0"] }),
    "r0.1@renderItem.0.0": part({ id: "r0.1@renderItem.0.0", parent: "r0.1@renderItem.0", type: "Text" }),
  };
  it("are three, in their own group, each asking before it is added", () => {
    expect(GUIDED_PARTS.map((p) => [p.guided, p.category])).toEqual([["form", "Connected"], ["button", "Connected"], ["list", "Connected"]]);
    expect(GUIDED_PARTS.every((p) => p.jsx === "" && p.imports.length === 0)).toBe(true);   // the server writes the code, never the page
  });
  it("are found by the words people search by", () => {
    expect(searchPalette(GUIDED_PARTS, "delete").map((p) => p.guided)).toEqual(["button"]);
    expect(searchPalette(GUIDED_PARTS, "table").map((p) => p.guided)).toEqual(["list"]);
  });
  it("know what a list row is called where a part is added inside one", () => {
    expect(rowVarAt(inRow, "r0.1@renderItem.0")).toBe("item");
    expect(rowVarAt(inRow, "r0.1@renderItem.0.0")).toBe("item");
    expect(rowVarAt(inRow, "r0.2")).toBeNull();
    expect(rowVarAt(inRow, null)).toBeNull();
  });
  it("name the part a place adds into", () => {
    expect(holderIdOf(nodes, { op: { parentId: "r0.2" }, says: "" })).toBe("r0.2");
    expect(holderIdOf(nodes, { op: { afterId: "r0.2.0" }, says: "" })).toBe("r0.2");
    expect(holderIdOf(nodes, { op: { beforeId: "nope" }, says: "" })).toBeNull();
  });
  it("can be dropped on the picture like any ready part", () => {
    const out = resolveDrop({ nodes, imports, kit: { ...kit, palette: [] }, dragging: null, partId: "guided-form",
                              source: { file: "src/screens/PAGE-001.tsx", line: 4, component: "Row" }, rel: 0.5 });
    expect(out).toMatchObject({ part: { guided: "form" }, place: { op: { parentId: "r0.2" } } });
  });
});
