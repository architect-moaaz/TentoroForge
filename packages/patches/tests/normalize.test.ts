import { describe, it, expect } from "vitest";
import { normalize } from "../src/normalize";
import { applyAction } from "../src/apply";
import type { Artifacts } from "../src/types";

function fresh(): Artifacts {
  return {
    pageSchemas: {
      home: {
        schemaVersion: "2", id: "home", route: "/",
        root: { id: "n1", type: "Stack", props: { gap: "md", padding: "sm" },
                children: [
                  { id: "n2", type: "Text", props: { text: "Hello" } },
                ] },
      },
    },
    navFlow: {
      version: "1.0", initialPage: "home",
      pages: [{ id: "home", route: "/", title: "Home",
                schemaFile: "src/schemas/home.json", params: [] }],
      transitions: [], guards: {},
    },
    tokens: {
      color: { brand: { primary: "#13A8A8" } } as any,
      typography: {} as any, spacing: {} as any, radius: {} as any,
      shadow: {} as any, motion: {} as any, breakpoints: {} as any,
    },
  };
}

describe("normalize", () => {
  it("returns the same shape (structurally equal)", () => {
    const a = fresh();
    const n = normalize(a);
    expect(JSON.parse(JSON.stringify(n))).toEqual(JSON.parse(JSON.stringify(a)));
  });

  it("is idempotent — normalize(normalize(x)) === normalize(x)", () => {
    const a = fresh();
    const once = JSON.stringify(normalize(a));
    const twice = JSON.stringify(normalize(normalize(a)));
    expect(once).toBe(twice);
  });

  it("sorts object keys deterministically", () => {
    const a = fresh();
    a.pageSchemas.home.root.props = { padding: "sm", gap: "md", align: "start" };
    const serialised = JSON.stringify(normalize(a));
    // Find the props object in the serialised string
    const propsIdx = serialised.indexOf('"props":{');
    expect(propsIdx).toBeGreaterThan(-1);
    // The first key after `"props":{` should be "align" (alphabetical)
    const after = serialised.slice(propsIdx);
    const firstKey = after.match(/"props":\{"([^"]+)"/)![1];
    expect(firstKey).toBe("align");
  });

  it("sorts navFlow.pages by id", () => {
    const a = fresh();
    a.navFlow.pages = [
      { id: "z", route: "/z", title: "Z", schemaFile: "src/schemas/z.json", params: [] },
      { id: "a", route: "/a", title: "A", schemaFile: "src/schemas/a.json", params: [] },
      { id: "home", route: "/", title: "Home",
        schemaFile: "src/schemas/home.json", params: [] },
    ] as any;
    const n = normalize(a);
    expect(n.navFlow.pages.map(p => p.id)).toEqual(["a", "home", "z"]);
  });

  it("sorts navFlow.transitions by id", () => {
    const a = fresh();
    a.navFlow.transitions = [
      { id: "t3", from: "home", trigger: "x", to: "home" },
      { id: "t1", from: "home", trigger: "y", to: "home" },
      { id: "t2", from: "home", trigger: "z", to: "home" },
    ] as any;
    const n = normalize(a);
    expect(n.navFlow.transitions.map(t => t.id)).toEqual(["t1", "t2", "t3"]);
  });

  it("sorts pageSchemas keys", () => {
    const a = fresh();
    a.pageSchemas.zebra = a.pageSchemas.home;
    a.pageSchemas.alpha = a.pageSchemas.home;
    const n = normalize(a);
    expect(Object.keys(n.pageSchemas)).toEqual(["alpha", "home", "zebra"]);
  });

  it("does NOT sort children — order is semantic", () => {
    const a = fresh();
    a.pageSchemas.home.root.children = [
      { id: "c1", type: "Text", props: { text: "first" } },
      { id: "c2", type: "Text", props: { text: "second" } },
      { id: "c3", type: "Text", props: { text: "third" } },
    ];
    const n = normalize(a);
    expect(n.pageSchemas.home.root.children!.map(c => c.id))
      .toEqual(["c1", "c2", "c3"]);
  });

  it("round-trip via JSON is identity", () => {
    const a = fresh();
    const n1 = normalize(a);
    const n2 = normalize(JSON.parse(JSON.stringify(n1)));
    expect(JSON.stringify(n1)).toBe(JSON.stringify(n2));
  });

  it("equivalent applyAction paths produce identical normalised output", () => {
    // Editor path: insertNode then updateProp
    const start = fresh();
    let editor = start;
    const r1 = applyAction(editor, {
      type: "insertNode", pageId: "home", parentId: "n1", index: 1,
      node: { id: "x1", type: "Button", props: { label: "Original" } },
    });
    editor = r1.next;
    const r2 = applyAction(editor, {
      type: "updateProp", pageId: "home", nodeId: "x1",
      propName: "label", value: "Final",
    });
    editor = r2.next;

    // LLM path: replaceArtifacts with same logical end state
    const llmTarget: Artifacts = JSON.parse(JSON.stringify(start));
    llmTarget.pageSchemas.home.root.children!.push({
      id: "x1", type: "Button", props: { label: "Final" },
    });

    const editorNorm = JSON.stringify(normalize(editor));
    const llmNorm = JSON.stringify(normalize(llmTarget));
    expect(editorNorm).toBe(llmNorm);
  });
});
