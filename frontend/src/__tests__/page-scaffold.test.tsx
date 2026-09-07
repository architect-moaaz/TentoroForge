/**
 * "New Page → Layout → Form" scaffolding — full coverage.
 *
 * Proves the pure builder emits a valid Page tree, that every field kind maps to
 * a Form field the RENDERER accepts (rendered through the real Engine — an
 * invalid field would surface as a data-invalid-node placeholder), and that the
 * scaffolded page round-trips through the real `addPage` reducer + undo.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import React from "react";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import { validateForCommit } from "@forge/patches";
import { starterRegistry } from "@forge/registry";
import { useEditorStore } from "@/lib/editor-store";
import {
  scaffoldPage,
  slugify,
  camelName,
  pageKindMeta,
  PAGE_KINDS,
  type PageKind,
  type ScaffoldField,
  type ScaffoldFieldKind,
} from "@/lib/page-scaffold";

// ---- jsdom polyfills --------------------------------------------------------
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  })) as unknown as typeof window.matchMedia;
}
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}

const NAV_FLOW = {
  version: "1.0", initialPage: "home",
  pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }],
  transitions: [], guards: {},
};

// deterministic ids for stable assertions
function seqIds() {
  const counts: Record<string, number> = {};
  return (type: string) => `${type.toLowerCase()}-${(counts[type] = (counts[type] ?? 0) + 1)}`;
}

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
async function renderPage(page: any) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <EngineProvider designSpec={{}} navFlow={NAV_FLOW as any} cssVarTokens={{}}>
        <Engine schema={page} previewData={{}} />
      </EngineProvider>,
    );
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
}

// =============================================================================
describe("scaffold helpers", () => {
  it("slugify → kebab-case", () => {
    expect(slugify("Contact Us")).toBe("contact-us");
    expect(slugify("  Weird__Name!! ")).toBe("weird-name");
    expect(slugify("")).toBe("");
  });
  it("camelName → camelCase field name", () => {
    expect(camelName("First Name")).toBe("firstName");
    expect(camelName("email")).toBe("email");
    expect(camelName("  ")).toBe("field");
  });
});

// =============================================================================
describe("scaffoldPage — structure + props", () => {
  it("centered layout: Container(md) → Stack → [Heading, Card → Form]", () => {
    const p = scaffoldPage({ title: "Contact Us", idFactory: seqIds() });
    expect(p.pageId).toBe("contact-us");
    expect(p.route).toBe("/contact-us");
    expect(p.title).toBe("Contact Us");
    expect(p.root.type).toBe("Container");
    expect(p.root.props).toEqual({ maxWidth: "md" });
    const stack = p.root.children![0];
    expect(stack.type).toBe("Stack");
    const [heading, card] = stack.children!;
    expect(heading.type).toBe("Heading");
    expect(heading.props).toEqual({ content: "Contact Us", level: 1 });
    expect(card.type).toBe("Card");
    const form = card.children![0];
    expect(form.type).toBe("Form");
    expect((form.props as any).submitLabel).toBe("Submit");
  });

  it("full layout: Container(xl) → Stack → [Heading, Form] (no card)", () => {
    const p = scaffoldPage({ title: "Signup", layout: "full", idFactory: seqIds() });
    expect(p.root.props).toEqual({ maxWidth: "xl" });
    const stack = p.root.children![0];
    expect(stack.children!.map((c) => c.type)).toEqual(["Heading", "Form"]);
  });

  it("heading:false omits the Heading", () => {
    const p = scaffoldPage({ title: "X", heading: false, layout: "full", idFactory: seqIds() });
    expect(p.root.children![0].children!.map((c) => c.type)).toEqual(["Form"]);
  });

  it("defaults to Name + Email fields when none supplied", () => {
    const p = scaffoldPage({ title: "X", idFactory: seqIds() });
    const form = p.root.children![0].children![1].children![0];
    const fields = (form.props as any).fields;
    expect(fields.map((f: any) => f.name)).toEqual(["name", "email"]);
    expect(fields.map((f: any) => f.kind)).toEqual(["text", "email"]);
  });

  it("de-duplicates the slug against existing pages/routes", () => {
    const p = scaffoldPage({
      title: "Contact",
      existingPageIds: ["contact"],
      existingRoutes: ["/contact-2"],
      idFactory: seqIds(),
    });
    expect(p.pageId).toBe("contact-3"); // contact + contact-2 taken
    expect(p.route).toBe("/contact-3");
  });

  it("generates unique ids across every node", () => {
    const p = scaffoldPage({ title: "Many", fields: [
      { label: "A", kind: "text" }, { label: "B", kind: "select" },
    ]});
    const ids: string[] = [];
    const walk = (n: any) => { ids.push(n.id); (n.children ?? []).forEach(walk); };
    walk(p.root);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

// =============================================================================
describe("scaffoldPage — field specs match the strict Form union", () => {
  const KINDS: ScaffoldFieldKind[] = ["text", "email", "number", "textarea", "select", "checkbox", "date", "switch"];

  it("maps each kind with the exact allowed keys (checkbox/switch reject 'required')", () => {
    const fields: ScaffoldField[] = KINDS.map((k) => ({ label: `${k} field`, kind: k, required: true }));
    const p = scaffoldPage({ title: "All", fields, layout: "full", heading: false, idFactory: seqIds() });
    const specs = (p.root.children![0].children![0].props as any).fields as any[];
    const byKind = Object.fromEntries(specs.map((s) => [s.kind, s]));
    // required stripped from checkbox + switch
    expect(byKind.checkbox).toEqual({ kind: "checkbox", name: "checkboxField", label: "checkbox field" });
    expect(byKind.switch).toEqual({ kind: "switch", name: "switchField", label: "switch field" });
    // requirable kinds keep it
    expect(byKind.text.required).toBe(true);
    expect(byKind.date.required).toBe(true);
    // select gets options
    expect(Array.isArray(byKind.select.options)).toBe(true);
    expect(byKind.select.options.length).toBeGreaterThan(0);
  });

  it("de-duplicates field names derived from identical labels", () => {
    const p = scaffoldPage({ title: "Dup", fields: [
      { label: "Name", kind: "text" }, { label: "Name", kind: "text" },
    ]});
    const form = p.root.children![0].children![1].children![0];
    const names = (form.props as any).fields.map((f: any) => f.name);
    expect(new Set(names).size).toBe(names.length);
  });
});

// =============================================================================
describe("scaffoldPage — commits + renders", () => {
  afterEach(() => { act(() => root?.unmount()); container?.remove(); });

  it("passes validateForCommit (valid types + unique ids)", () => {
    const p = scaffoldPage({ title: "Valid", fields: [{ label: "Msg", kind: "textarea" }] });
    const artifacts = {
      pageSchemas: { [p.pageId]: { schemaVersion: "2", id: p.pageId, route: p.route, root: p.root } },
      navFlow: NAV_FLOW, tokens: { color: {}, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {} },
    };
    const errs = validateForCommit(artifacts as any, starterRegistry as any);
    expect(errs).toEqual([]);
  });

  it("renders through the real Engine with the Form + no invalid-props placeholder", async () => {
    const KINDS: ScaffoldFieldKind[] = ["text", "email", "number", "textarea", "select", "checkbox", "date", "switch"];
    const p = scaffoldPage({
      title: "Render All",
      fields: KINDS.map((k) => ({ label: `${k}`, kind: k })),
    });
    await renderPage({ schemaVersion: "2", id: p.pageId, route: p.route, dataSources: [], root: p.root });
    // The Form node renders (selectable) and nothing is an invalid/unknown placeholder.
    const formEl = container.querySelector('[data-node-id^="form-"]');
    expect(formEl).toBeTruthy();
    expect(container.querySelectorAll("[data-invalid-node]").length).toBe(0);
    expect(container.querySelectorAll("[data-unknown-node]").length).toBe(0);
  });
});

// =============================================================================
// Page KINDS. The dialog used to be able to build exactly one shape (a form);
// these prove each new kind emits a tree the commit boundary and the renderer
// both accept, and that the form path is untouched by their arrival.
// =============================================================================
const ALL_KINDS: PageKind[] = PAGE_KINDS.map((k) => k.kind);

function typesIn(n: any): string[] {
  const out: string[] = [];
  const walk = (x: any) => { out.push(x.type); (x.children ?? []).forEach(walk); };
  walk(n);
  return out;
}

describe("page kinds — metadata drives the dialog", () => {
  it("only the form kind declares hasForm", () => {
    const withForm = PAGE_KINDS.filter((k) => k.hasForm).map((k) => k.kind);
    expect(withForm).toEqual(["form"]);
  });

  it("only the form kind uses the centered/full layout preset", () => {
    const withPreset = PAGE_KINDS.filter((k) => k.hasLayoutPreset).map((k) => k.kind);
    expect(withPreset).toEqual(["form"]);
  });

  it("sidebar + navbar are the nav-bearing kinds", () => {
    const withNav = PAGE_KINDS.filter((k) => k.hasNav).map((k) => k.kind);
    expect(withNav).toEqual(["sidebar", "navbar"]);
  });

  it("an unknown kind falls back to form metadata", () => {
    expect(pageKindMeta(undefined).kind).toBe("form");
    expect(pageKindMeta("nope" as PageKind).kind).toBe("form");
  });
});

describe("page kinds — shapes", () => {
  it("blank: Container(lg) → Stack → [Heading] and no Form anywhere", () => {
    const p = scaffoldPage({ title: "Scratch", kind: "blank", idFactory: seqIds() });
    expect(p.root.type).toBe("Container");
    expect(p.root.props).toEqual({ maxWidth: "lg" });
    const stack = p.root.children![0];
    expect(stack.type).toBe("Stack");
    expect(stack.children!.map((c) => c.type)).toEqual(["Heading"]);
    expect(typesIn(p.root)).not.toContain("Form");
  });

  it("blank + heading:false is a genuinely empty container", () => {
    const p = scaffoldPage({ title: "X", kind: "blank", heading: false, idFactory: seqIds() });
    expect(p.root.children![0].children).toEqual([]);
  });

  it("sidebar: Sidebar(16rem) with EXACTLY 2 children — rail then main", () => {
    const p = scaffoldPage({
      title: "Console", kind: "sidebar",
      navItems: [{ label: "Home", route: "/" }, { label: "Jobs", route: "/jobs" }],
      idFactory: seqIds(),
    });
    expect(p.root.type).toBe("Sidebar");
    // SidebarNode (packages/schema/src/nodes/layout-v2.ts) enforces both of these.
    expect(p.root.props).toEqual({ width: "16rem" });
    expect(p.root.children).toHaveLength(2);
    const [rail, main] = p.root.children!;
    expect(rail.children!.map((c) => c.type)).toEqual(["NavLink", "NavLink"]);
    expect(rail.children![1].props).toEqual({ label: "Jobs", navigate: "/jobs" });
    expect(main.children!.map((c) => c.type)).toEqual(["Heading"]);
  });

  it("sidebar falls back to placeholder nav items when none are supplied", () => {
    const p = scaffoldPage({ title: "C", kind: "sidebar", idFactory: seqIds() });
    expect(p.root.children![0].children).toHaveLength(3);
  });

  it("navbar: Stack → [Row(brand + links), Divider, Container]", () => {
    const p = scaffoldPage({
      title: "Site", kind: "navbar",
      navItems: [{ label: "Docs", route: "/docs" }],
      idFactory: seqIds(),
    });
    expect(p.root.type).toBe("Stack");
    expect(p.root.children!.map((c) => c.type)).toEqual(["Row", "Divider", "Container"]);
    const [brand, links] = p.root.children![0].children!;
    expect(brand.props).toEqual({ content: "Site", level: 3 });
    expect(links.children!.map((c) => c.type)).toEqual(["NavLink"]);
  });

  it("dashboard: 4-up MetricTile grid over a Card → Table", () => {
    const p = scaffoldPage({ title: "Ops", kind: "dashboard", idFactory: seqIds() });
    const stack = p.root.children![0];
    expect(stack.children!.map((c) => c.type)).toEqual(["Heading", "Grid", "Card"]);
    const grid = stack.children![1];
    expect(grid.props).toMatchObject({ columns: 4 });
    expect(grid.children!.map((c) => c.type)).toEqual(
      ["MetricTile", "MetricTile", "MetricTile", "MetricTile"],
    );
    expect(typesIn(p.root)).toContain("Table");
  });

  it("list: header Row (heading + Button) over a Card → Table", () => {
    const p = scaffoldPage({ title: "Items", kind: "list", idFactory: seqIds() });
    const stack = p.root.children![0];
    expect(stack.children!.map((c) => c.type)).toEqual(["Row", "Card"]);
    expect(stack.children![0].children!.map((c) => c.type)).toEqual(["Heading", "Button"]);
  });

  it("detail: Split(2:1) with EXACTLY 2 children", () => {
    const p = scaffoldPage({ title: "Record", kind: "detail", idFactory: seqIds() });
    const split = p.root.children![0].children![1];
    expect(split.type).toBe("Split");
    // SplitNode enforces ratio + exactly-2 children.
    expect(split.props).toEqual({ ratio: "2:1", breakpoint: "md" });
    expect(split.children).toHaveLength(2);
  });

  it("every kind generates unique node ids", () => {
    for (const kind of ALL_KINDS) {
      const p = scaffoldPage({ title: `Page ${kind}`, kind });
      const ids: string[] = [];
      const walk = (n: any) => { ids.push(n.id); (n.children ?? []).forEach(walk); };
      walk(p.root);
      expect(new Set(ids).size, `duplicate ids in kind '${kind}'`).toBe(ids.length);
    }
  });

  it("only the form kind emits a Form node", () => {
    for (const kind of ALL_KINDS) {
      const p = scaffoldPage({ title: "T", kind });
      expect(typesIn(p.root).includes("Form"), `kind '${kind}'`).toBe(kind === "form");
    }
  });
});

// =============================================================================
describe("page kinds — the form path is byte-identical to before `kind` existed", () => {
  it("omitting `kind` produces exactly what kind:'form' produces", () => {
    const args = { title: "Contact Us", fields: [{ label: "Msg", kind: "textarea" as const }] };
    const implicit = scaffoldPage({ ...args, idFactory: seqIds() });
    const explicit = scaffoldPage({ ...args, kind: "form", idFactory: seqIds() });
    expect(implicit).toEqual(explicit);
  });

  it("layout centered/full still select Card vs bare Form", () => {
    const centered = scaffoldPage({ title: "A", kind: "form", idFactory: seqIds() });
    expect(centered.root.props).toEqual({ maxWidth: "md" });
    expect(centered.root.children![0].children!.map((c) => c.type)).toEqual(["Heading", "Card"]);
    const full = scaffoldPage({ title: "A", kind: "form", layout: "full", idFactory: seqIds() });
    expect(full.root.props).toEqual({ maxWidth: "xl" });
    expect(full.root.children![0].children!.map((c) => c.type)).toEqual(["Heading", "Form"]);
  });
});

// =============================================================================
describe("page kinds — commit + render", () => {
  afterEach(() => { act(() => root?.unmount()); container?.remove(); });

  it.each(ALL_KINDS)("kind '%s' passes validateForCommit", (kind) => {
    const p = scaffoldPage({ title: `Page ${kind}`, kind });
    const artifacts = {
      pageSchemas: { [p.pageId]: { schemaVersion: "2", id: p.pageId, route: p.route, root: p.root } },
      navFlow: {
        ...NAV_FLOW,
        pages: [...NAV_FLOW.pages, { id: p.pageId, route: p.route, title: p.title, schemaFile: `src/schemas/${p.pageId}.json`, params: [] }],
      },
      tokens: { color: {}, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {} },
    };
    expect(validateForCommit(artifacts as any, starterRegistry as any)).toEqual([]);
  });

  it.each(ALL_KINDS)("kind '%s' renders with no unknown/invalid placeholder", async (kind) => {
    const p = scaffoldPage({ title: `Page ${kind}`, kind });
    await renderPage({ schemaVersion: "2", id: p.pageId, route: p.route, dataSources: [], root: p.root });
    const unknown = Array.from(container.querySelectorAll("[data-unknown-node]"))
      .map((el) => el.getAttribute("data-unknown-node"));
    const invalid = Array.from(container.querySelectorAll("[data-invalid-node]"))
      .map((el) => el.getAttribute("data-invalid-node"));
    expect(unknown, `unknown components in kind '${kind}'`).toEqual([]);
    expect(invalid, `invalid props in kind '${kind}'`).toEqual([]);
  });
});

// =============================================================================
describe("scaffoldPage — addPage reducer round-trip + undo", () => {
  beforeEach(() => {
    useEditorStore.getState().setInitial({
      pageSchemas: { home: { schemaVersion: "2", id: "home", route: "/", root: { id: "root", type: "Container", props: {}, children: [] } } },
      navFlow: { ...NAV_FLOW, pages: [...NAV_FLOW.pages] },
      tokens: { color: {}, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {} },
    } as any);
  });

  it("addPage inserts the page + nav-flow entry; undo removes both", () => {
    const store = useEditorStore.getState();
    const existing = { existingPageIds: Object.keys((store.artifacts as any).pageSchemas), existingRoutes: (store.artifacts as any).navFlow.pages.map((p: any) => p.route) };
    const p = scaffoldPage({ title: "Contact", ...existing });
    store.dispatch({ type: "addPage", pageId: p.pageId, route: p.route, title: p.title, root: p.root as any });
    expect(useEditorStore.getState().lastError).toBeNull();

    const arts = () => useEditorStore.getState().artifacts as any;
    expect(arts().pageSchemas[p.pageId]).toBeTruthy();
    const navEntry = arts().navFlow.pages.find((x: any) => x.id === p.pageId);
    expect(navEntry).toMatchObject({ id: p.pageId, route: p.route, title: "Contact", schemaFile: `src/schemas/${p.pageId}.json` });
    // Editor-created pages must be shell pages so they render in the app frame
    // AND surface in the generated app's sidebar (nav-flow→SideNav merge).
    expect(navEntry.shell).toBe(true);

    useEditorStore.getState().undo();
    expect(arts().pageSchemas[p.pageId]).toBeUndefined();
    expect(arts().navFlow.pages.find((x: any) => x.id === p.pageId)).toBeUndefined();
  });
});
