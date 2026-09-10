import { describe, it, expect } from "vitest";
import { applyAction } from "../src/apply";
import type { Artifacts } from "../src/types";

function fixture(): Artifacts {
  return {
    pageSchemas: {
      home: {
        schemaVersion: "2", id: "home", route: "/",
        root: {
          id: "n1", type: "Stack", children: [
            { id: "n2", type: "Text", props: { text: "Hello" } },
          ],
        },
      },
    },
    navFlow: {
      version: "1.0", initialPage: "home",
      pages: [{ id: "home", route: "/", title: "Home",
                schemaFile: "src/schemas/home.json", params: [] }],
      transitions: [], guards: {},
    },
    tokens: {
      color: {}, typography: {}, spacing: {}, radius: {},
      shadow: {}, motion: {}, breakpoints: {},
    },
  };
}

describe("applyAction — updateProp", () => {
  it("updates a prop", () => {
    const { next, inverse } = applyAction(fixture(), {
      type: "updateProp", pageId: "home", nodeId: "n2", propName: "text", value: "World",
    });
    expect((next.pageSchemas.home.root.children![0].props as any).text).toBe("World");
    expect(inverse).toEqual({
      type: "updateProp", pageId: "home", nodeId: "n2", propName: "text", value: "Hello",
    });
  });

  it("inverse undoes the change", () => {
    const start = fixture();
    const { next, inverse } = applyAction(start, {
      type: "updateProp", pageId: "home", nodeId: "n2", propName: "text", value: "World",
    });
    const { next: undone } = applyAction(next, inverse);
    expect((undone.pageSchemas.home.root.children![0].props as any).text).toBe("Hello");
  });

  it("throws on unknown node", () => {
    expect(() => applyAction(fixture(), {
      type: "updateProp", pageId: "home", nodeId: "missing", propName: "x", value: 1,
    })).toThrow();
  });
});

describe("applyAction — insertNode / removeNode", () => {
  it("insertNode adds at index", () => {
    const node = { id: "n3", type: "Text", props: { text: "Two" } };
    const { next } = applyAction(fixture(), {
      type: "insertNode", pageId: "home", parentId: "n1", index: 1, node,
    });
    expect(next.pageSchemas.home.root.children!.length).toBe(2);
    expect(next.pageSchemas.home.root.children![1].id).toBe("n3");
  });

  it("insertNode inverse removes inserted", () => {
    const node = { id: "n3", type: "Text", props: { text: "Two" } };
    const { next, inverse } = applyAction(fixture(), {
      type: "insertNode", pageId: "home", parentId: "n1", index: 1, node,
    });
    expect(inverse).toEqual({ type: "removeNode", pageId: "home", nodeId: "n3" });
    const { next: undone } = applyAction(next, inverse);
    expect(undone.pageSchemas.home.root.children!.length).toBe(1);
  });

  it("removeNode roundtrips with insertNode inverse", () => {
    const start = fixture();
    const { next, inverse } = applyAction(start, {
      type: "removeNode", pageId: "home", nodeId: "n2",
    });
    expect(next.pageSchemas.home.root.children!.length).toBe(0);
    const { next: undone } = applyAction(next, inverse);
    expect(undone.pageSchemas.home.root.children![0].id).toBe("n2");
    expect((undone.pageSchemas.home.root.children![0].props as any).text).toBe("Hello");
  });
});

describe("applyAction — moveNode", () => {
  it("reparents and reindexes", () => {
    const start = fixture();
    const withCol = applyAction(start, {
      type: "insertNode", pageId: "home", parentId: "n1", index: 1,
      node: { id: "n3", type: "Stack", children: [] },
    }).next;
    const { next, inverse } = applyAction(withCol, {
      type: "moveNode", pageId: "home", nodeId: "n2",
      newParentId: "n3", newIndex: 0,
    });
    // After moving n2 out of n1 into n3, n1 has one child (n3) and n3 contains n2.
    // n3 slides from index 1 → index 0 once n2 is removed from n1.
    expect(next.pageSchemas.home.root.children!.length).toBe(1);
    expect(next.pageSchemas.home.root.children![0].children![0].id).toBe("n2");
    expect(inverse).toEqual({
      type: "moveNode", pageId: "home", nodeId: "n2",
      newParentId: "n1", newIndex: 0,
    });
  });
});

describe("applyAction — duplicateNode", () => {
  it("inserts a clone after the original", () => {
    const { next, inverse } = applyAction(fixture(), {
      type: "duplicateNode", pageId: "home", nodeId: "n2",
    });
    expect(next.pageSchemas.home.root.children!.length).toBe(2);
    expect(next.pageSchemas.home.root.children![1].id).not.toBe("n2");
    expect((inverse as any).type).toBe("removeNode");
  });
});

describe("applyAction — bind/unbind", () => {
  const textProp = (a: any) => (a.pageSchemas.home.root.children![0].props as any).text;

  it("bindProp writes a {{expr}} STRING, never the {$binding} object", () => {
    // The object form was implemented by nothing outside the editor: it survived
    // interpolateDeep (which only transforms strings) and validateProps (which
    // cannot coerce it) and reached React in child position, so binding a prop
    // rendered "⚠ render error" and then autosaved the breakage into the
    // generated app. The string is what interpolate.ts actually resolves.
    const { next } = applyAction(fixture(), {
      type: "bindProp", pageId: "home", nodeId: "n2",
      propName: "text", binding: "form.name",
    });
    expect(textProp(next)).toBe("{{form.name}}");
    expect(typeof textProp(next)).toBe("string");
  });

  it("an EMPTY bind writes \"\", not \"{{}}\"", () => {
    // The bind toggle binds before the user has typed anything. "{{}}" would be
    // a template that resolves to nothing while still reading as bound — the
    // same bug in a quieter costume. "" is honestly "no value yet", renders as
    // nothing, and still satisfies a required string field.
    const { next } = applyAction(fixture(), {
      type: "bindProp", pageId: "home", nodeId: "n2", propName: "text", binding: "",
    });
    expect(textProp(next)).toBe("");
  });

  it("undo of an EMPTY bind restores the literal (the inverse used to be asymmetric)", () => {
    // unbindProp tested the TRUTHINESS of prev.$binding, so a bind that was
    // toggled but never filled took the updateProp branch and undo behaved
    // differently from a filled one. Shape, not truthiness, decides now.
    const before = fixture();
    const { next, inverse } = applyAction(before, {
      type: "bindProp", pageId: "home", nodeId: "n2", propName: "text", binding: "",
    });
    const restored = applyAction(next, inverse).next;
    expect(textProp(restored)).toBe(textProp(before));
  });

  it("re-binding an already-bound prop round-trips through its inverse", () => {
    const start = applyAction(fixture(), {
      type: "bindProp", pageId: "home", nodeId: "n2", propName: "text", binding: "a.one",
    }).next;
    const { next, inverse } = applyAction(start, {
      type: "bindProp", pageId: "home", nodeId: "n2", propName: "text", binding: "b.two",
    });
    expect(textProp(next)).toBe("{{b.two}}");
    expect(textProp(applyAction(next, inverse).next)).toBe("{{a.one}}");
  });

  it("unbindProp replaces the binding with the literal", () => {
    const start = applyAction(fixture(), {
      type: "bindProp", pageId: "home", nodeId: "n2",
      propName: "text", binding: "form.name",
    }).next;
    const { next } = applyAction(start, {
      type: "unbindProp", pageId: "home", nodeId: "n2",
      propName: "text", literalValue: "Goodbye",
    });
    expect((next.pageSchemas.home.root.children![0].props as any).text).toBe("Goodbye");
  });
});

describe("applyAction — addPage / removePage atomic", () => {
  it("addPage updates pageSchemas AND navFlow.pages", () => {
    const { next } = applyAction(fixture(), {
      type: "addPage", pageId: "about", route: "/about", title: "About",
      root: { id: "ar", type: "Stack", children: [] },
    });
    expect(next.pageSchemas.about).toBeDefined();
    expect(next.navFlow.pages.find(p => p.id === "about")).toBeDefined();
  });

  it("addPage inverse removes from both", () => {
    const { next, inverse } = applyAction(fixture(), {
      type: "addPage", pageId: "about", route: "/about", title: "About",
      root: { id: "ar", type: "Stack", children: [] },
    });
    expect(inverse).toEqual({ type: "removePage", pageId: "about" });
    const { next: undone } = applyAction(next, inverse);
    expect(undone.pageSchemas.about).toBeUndefined();
    expect(undone.navFlow.pages.find(p => p.id === "about")).toBeUndefined();
  });

  it("removePage scrubs referencing transitions", () => {
    const start = fixture();
    start.navFlow.pages.push({ id: "x", route: "/x", title: "X",
                                schemaFile: "src/schemas/x.json", params: [] });
    start.navFlow.transitions = [
      { id: "t1", from: "home", trigger: "go-x", to: "x" },
    ];
    start.pageSchemas.x = {
      schemaVersion: "2", id: "x",
      root: { id: "xr", type: "Stack", children: [] },
    };
    const { next, inverse } = applyAction(start, {
      type: "removePage", pageId: "x",
    });
    expect(next.navFlow.transitions).toEqual([]);
    // Inverse restores the page AND… transitions stay scrubbed (acceptable v1
    // limitation; cascading transition restoration is future work).
    const { next: undone } = applyAction(next, inverse);
    expect(undone.pageSchemas.x).toBeDefined();
  });
});

describe("applyAction — renameToken cascade", () => {
  it("rewrites all references in pageSchemas", () => {
    const start = fixture();
    start.tokens.color = { brand: { primary: "#13A8A8" } };
    start.pageSchemas.home.root.children![0].props = {
      color: "color.brand.primary",
    };
    const { next, inverse } = applyAction(start, {
      type: "renameToken",
      oldPath: ["color", "brand", "primary"],
      newPath: ["color", "brand", "main"],
    });
    expect((next.pageSchemas.home.root.children![0].props as any).color)
      .toBe("color.brand.main");
    // Inverse rewrites back
    const { next: undone } = applyAction(next, inverse);
    expect((undone.pageSchemas.home.root.children![0].props as any).color)
      .toBe("color.brand.primary");
  });
});

describe("applyAction — updateToken", () => {
  it("sets a nested token value", () => {
    const start = fixture();
    start.tokens.color = { brand: { primary: "#13A8A8" } };
    const { next, inverse } = applyAction(start, {
      type: "updateToken", path: ["color", "brand", "primary"], value: "#000000",
    });
    expect((next.tokens.color as any).brand.primary).toBe("#000000");
    expect((inverse as any).value).toBe("#13A8A8");
  });
});

describe("applyAction — replaceArtifacts", () => {
  it("substitutes the whole bundle and inverse restores prior", () => {
    const start = fixture();
    const fresh: Artifacts = JSON.parse(JSON.stringify(start));
    fresh.pageSchemas.home.root.children = [];
    const { next, inverse } = applyAction(start, {
      type: "replaceArtifacts", artifacts: fresh,
    });
    expect(next.pageSchemas.home.root.children).toEqual([]);
    expect(inverse.type).toBe("replaceArtifacts");
    const { next: undone } = applyAction(next, inverse);
    expect(undone.pageSchemas.home.root.children![0].id).toBe("n2");
  });
});

describe("applyAction — setInitialPage / addTransition / removeTransition / setGuard", () => {
  it("setInitialPage swaps and inverse restores", () => {
    const start = fixture();
    start.navFlow.pages.push({ id: "x", route: "/x", title: "X",
                                schemaFile: "x", params: [] });
    const { next, inverse } = applyAction(start, {
      type: "setInitialPage", pageId: "x",
    });
    expect(next.navFlow.initialPage).toBe("x");
    expect((inverse as any).pageId).toBe("home");
  });

  it("addTransition + removeTransition roundtrip", () => {
    const start = fixture();
    const t = { id: "tnew", from: "home", trigger: "go", to: "home" };
    const { next: afterAdd } = applyAction(start, {
      type: "addTransition", transition: t,
    });
    expect(afterAdd.navFlow.transitions).toHaveLength(1);
    const { next: afterRemove } = applyAction(afterAdd, {
      type: "removeTransition", transitionId: "tnew",
    });
    expect(afterRemove.navFlow.transitions).toHaveLength(0);
  });

  it("setGuard toggles + inverse restores", () => {
    const start = fixture();
    const { next, inverse } = applyAction(start, {
      type: "setGuard", pageId: "home", guard: "requiresAuth",
    });
    expect(next.navFlow.pages[0].guard).toBe("requiresAuth");
    const { next: undone } = applyAction(next, inverse);
    expect(undone.navFlow.pages[0].guard).toBeFalsy();
  });
});

describe("applyAction — renamePage / updateRoute", () => {
  it("renamePage updates title and inverse restores", () => {
    const { next, inverse } = applyAction(fixture(), {
      type: "renamePage", pageId: "home", title: "Welcome",
    });
    expect(next.navFlow.pages[0].title).toBe("Welcome");
    const { next: undone } = applyAction(next, inverse);
    expect(undone.navFlow.pages[0].title).toBe("Home");
  });

  it("updateRoute updates both navFlow and page record", () => {
    const { next } = applyAction(fixture(), {
      type: "updateRoute", pageId: "home", route: "/welcome",
    });
    expect(next.navFlow.pages[0].route).toBe("/welcome");
    expect(next.pageSchemas.home.route).toBe("/welcome");
  });
});

/**
 * Regression — docs/editor-audit/panels.md, "addPage overwrites an existing
 * page and its undo deletes it". `pageSchemas[id] = {...}` with no existence
 * check destroyed the user's page, duplicated its navFlow entry, and returned
 * `inverse: removePage`, so Ctrl-Z then deleted what was left.
 */
describe("applyAction — addPage refuses to destroy an existing page", () => {
  it("throws on a colliding pageId and leaves the original tree untouched", () => {
    const start = fixture();
    expect(() =>
      applyAction(start, {
        type: "addPage", pageId: "home", route: "/home-2", title: "Home 2",
        root: { id: "new-root", type: "Stack", children: [] },
      }),
    ).toThrow(/already exists/);
    // applyAction must not have mutated the input on the way to throwing.
    expect(start.pageSchemas.home.root.id).toBe("n1");
    expect(start.navFlow.pages).toHaveLength(1);
  });

  it("throws on a colliding route even when the pageId is new", () => {
    expect(() =>
      applyAction(fixture(), {
        type: "addPage", pageId: "landing", route: "/", title: "Landing",
        root: { id: "lr", type: "Stack", children: [] },
      }),
    ).toThrow(/route "\/" is already served by page "home"/);
  });

  it("throws when navFlow already has the id but pageSchemas does not", () => {
    const start = fixture();
    start.navFlow.pages.push({
      id: "orphan", route: "/orphan", title: "Orphan",
      schemaFile: "src/schemas/orphan.json", params: [],
    } as any);
    expect(() =>
      applyAction(start, {
        type: "addPage", pageId: "orphan", route: "/orphan-2", title: "Orphan",
        root: { id: "or", type: "Stack", children: [] },
      }),
    ).toThrow(/navFlow already has an entry/);
  });

  it("a fresh page still adds, and its undo only removes what it created", () => {
    const { next, inverse } = applyAction(fixture(), {
      type: "addPage", pageId: "about", route: "/about", title: "About",
      root: { id: "ar", type: "Stack", children: [] },
    });
    expect(next.pageSchemas.about).toBeDefined();
    const { next: undone } = applyAction(next, inverse);
    // The page that existed before the add survives the undo intact.
    expect(undone.pageSchemas.home.root.id).toBe("n1");
    expect(undone.pageSchemas.about).toBeUndefined();
    expect(undone.navFlow.pages.map(p => p.id)).toEqual(["home"]);
  });

  it("removePage → undo (addPage) round-trips without tripping the guards", () => {
    const start = fixture();
    const { next: removed, inverse } = applyAction(start, {
      type: "removePage", pageId: "home",
    });
    expect(removed.pageSchemas.home).toBeUndefined();
    const { next: restored } = applyAction(removed, inverse);
    expect(restored.pageSchemas.home.root.id).toBe("n1");
    expect(restored.navFlow.pages.map(p => p.id)).toEqual(["home"]);
  });
});
