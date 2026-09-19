import { describe, expect, it } from "vitest";

import { breakpointForWidth, effectiveValue, getGroupValue, getVisibility, groupOf, setGroupValue, setVisibility } from "../lib/classes";
import { breadcrumb, mainRoot, plainName, plainType, topmost } from "../lib/plain";
import { checkModel, findingsByNode, groupFindings } from "../lib/readiness";
import { buttonAction, buttonActionOps, entityColumns, formJsx, pageHref, tableJsx, workflowButtonJsx } from "../lib/templates";
import type { ModelNode, PageDoc, PageModel, PageRef, Registry, WorkflowRef } from "../types";

// ---------------------------------------------------------------------------
// Class families
// ---------------------------------------------------------------------------

describe("class families", () => {
  it("claims each class for one family, narrow text families before the colour catch-all", () => {
    expect(groupOf("text-sm")?.key).toBe("textSize");
    expect(groupOf("text-center")?.key).toBe("textAlign");
    expect(groupOf("text-muted-foreground")?.key).toBe("textColor");
    expect(groupOf("md:grid-cols-2")?.key).toBe("gridCols");
    expect(groupOf("hover:bg-muted")?.key).toBe("background"); // a hover slot of the same family
    expect(groupOf("dark:bg-muted")).toBeNull();
    expect(groupOf("whitespace-nowrap")).toBeNull();
  });

  it("sets one family at one breakpoint and leaves every other class in place", () => {
    const classes = "flex items-center gap-4 p-6 md:p-8 text-sm";
    expect(setGroupValue(classes, "padding", "", "p-2")).toBe("flex items-center gap-4 p-2 md:p-8 text-sm");
    expect(setGroupValue(classes, "padding", "md", null)).toBe("flex items-center gap-4 p-6 text-sm");
    expect(setGroupValue(classes, "rounded", "", "rounded-lg")).toBe("flex items-center gap-4 p-6 md:p-8 text-sm rounded-lg");
    expect(setGroupValue(classes, "padding", "lg", "p-10")).toBe("flex items-center gap-4 p-6 md:p-8 text-sm lg:p-10");
  });

  it("tells an inherited value from an override", () => {
    const classes = "p-4 lg:p-8";
    expect(getGroupValue(classes, "padding", "md")).toBeNull();
    expect(effectiveValue(classes, "padding", "md")).toEqual({ value: "p-4", from: "" });
    expect(effectiveValue(classes, "padding", "lg")).toEqual({ value: "p-8", from: "lg" });
    expect(effectiveValue(classes, "padding", "xl")).toEqual({ value: "p-8", from: "lg" });
  });

  it("maps a viewport width to Tailwind's breakpoint", () => {
    expect(breakpointForWidth(375)).toBe("");
    expect(breakpointForWidth(768)).toBe("md");
    expect(breakpointForWidth(1280)).toBe("xl");
  });

  it("expresses screen-size visibility as hidden / md:block pairs, both ways", () => {
    expect(setVisibility("p-4", "wide-only")).toBe("p-4 hidden md:block");
    expect(getVisibility("p-4 hidden md:block")).toBe("wide-only");
    expect(setVisibility("p-4 flex gap-2", "narrow-only")).toBe("p-4 flex gap-2 md:hidden");
    expect(getVisibility("p-4 flex gap-2 md:hidden")).toBe("narrow-only");
    expect(setVisibility("p-4 hidden md:flex", "all")).toBe("p-4");
  });
});

// ---------------------------------------------------------------------------
// A small page model
// ---------------------------------------------------------------------------

function node(id: string, type: string, extra: Partial<ModelNode> = {}): ModelNode {
  return {
    id, parent: id.includes(".") ? id.slice(0, id.lastIndexOf(".")) : null, index: 0, type,
    kind: /^[a-z]/.test(type) ? "element" : "component", props: [], text: null, textEditable: false,
    inner: null, innerSpan: null, selfClosing: false, span: [0, 0], wrapperSpan: null, line: 1, endLine: 1,
    context: null, children: [], ...extra,
  };
}

const registry: Registry = {
  version: "1",
  components: [
    { id: "button", label: "Button", category: "Actions", description: "", search: [], match: { types: ["Button"] }, jsx: "", imports: [],
      container: false, settings: [], events: [], guide: null, status: "ready" },
    { id: "heading", label: "Heading", category: "Content", description: "", search: [], match: { types: ["h1", "h2"] }, jsx: "", imports: [],
      container: false, settings: [], events: [], guide: null, status: "ready" },
  ],
};

const model: PageModel = {
  ok: true, roots: [{ id: "r0", owner: "sortIcon" }, { id: "r1", owner: "View" }], imports: [], loadKeys: ["rows"], viewProps: ["rows"],
  nodes: {
    r0: node("r0", "ArrowUp"),
    r1: node("r1", "div", { children: ["r1.0", "r1.1", "r1.2", "r1.3", "r1.4"], props: [{ name: "className", kind: "string", value: "p-6", span: [0, 0], valueSpan: null }] }),
    "r1.0": node("r1.0", "h1", { text: "Records", textEditable: true, line: 5 }),
    "r1.1": node("r1.1", "Button", { text: "Add", textEditable: true, line: 6 }),
    "r1.2": node("r1.2", "img", { line: 7, props: [{ name: "src", kind: "string", value: "https://placehold.co/1", span: [0, 0], valueSpan: null }] }),
    "r1.3": node("r1.3", "Link", { text: "Open", textEditable: true, line: 8, props: [{ name: "href", kind: "string", value: "/nowhere", span: [0, 0], valueSpan: null }] }),
    "r1.4": node("r1.4", "CardHeader", { children: ["r1.4.0"], line: 9 }),
    "r1.4.0": node("r1.4.0", "Input", { line: 10, props: [{ name: "id", kind: "string", value: "email", span: [0, 0], valueSpan: null }] }),
  },
};

const doc: PageDoc = {
  page: { id: "PAGE-001", name: "Records", route: "/records", purpose: "" },
  coded: true, revision: "abc", model, source: { view: "<div/>", load: "" }, registry,
  pages: [{ id: "PAGE-001", key: "records", name: "Records", route: "/records", params: [] },
          { id: "PAGE-002", key: "record", name: "Record", route: "/records/[id]", params: ["id"] }],
  workflows: [{ id: "FLOW-001", key: "closeCase", name: "Close Case", description: "", inputs: [], launchedFrom: ["PAGE-001"] }],
  entities: [], theme: {}, history: [],
};

describe("plain names", () => {
  it("speaks in kinds and text, never tags", () => {
    expect(plainType(model.nodes["r1"], registry)).toBe("Section");
    expect(plainName(model.nodes["r1.0"], registry)).toBe("Heading “Records”");
    expect(plainName(model.nodes["r1.1"], registry)).toBe("Button “Add”");
    expect(plainType(model.nodes["r1.4"], registry)).toBe("Card header");
    expect(breadcrumb(model, "r1.4.0", registry).map((b) => b.label)).toEqual(["Section", "Card header", "Field"]);
  });

  it("finds the View's root among helper roots and the topmost of a selection", () => {
    expect(mainRoot(model)).toBe("r1");
    expect(topmost(model, ["r1.4", "r1.4.0", "r1.0"])).toEqual(["r1.4", "r1.0"]);
  });
});

describe("readiness", () => {
  it("finds broken links, unlabelled fields, silent buttons, placeholders and unwired workflows", () => {
    const codes = checkModel(doc).map((f) => f.code).sort();
    expect(codes).toEqual(["broken-link", "idle-button", "no-alt", "no-label", "placeholder", "unwired-workflow"]);
    const link = checkModel(doc).find((f) => f.code === "broken-link")!;
    expect(link.plain).toBe("Link “Open” opens “/nowhere”, which is not a page of this app.");
    expect(link.nodeId).toBe("r1.3");
  });

  it("accepts a parameterised route and groups by severity", () => {
    const ok = { ...doc, model: { ...model, nodes: { ...model.nodes,
      "r1.3": node("r1.3", "Link", { props: [{ name: "href", kind: "string", value: "/records/42", span: [0, 0], valueSpan: null }] }) } } };
    expect(checkModel(ok).some((f) => f.code === "broken-link")).toBe(false);
    const groups = groupFindings(doc, [{ file: "view.tsx", line: 3, code: "TS2322", raw: "x", plain: "Line 3 of the page: not accepted", severity: "must-fix" }]);
    expect(groups.mustFix[0].code).toBe("TS2322");
    expect(groups.mustFix.map((f) => f.code).sort()).toEqual(["TS2322", "broken-link", "no-alt", "no-label", "unwired-workflow"]);
    expect(groups.recommended.map((f) => f.code)).toEqual(["idle-button", "placeholder"]);
    expect(groups.ready).toEqual([]);
  });

  it("marks a finding on the node and on every ancestor for the layer tree", () => {
    const marks = findingsByNode(model, checkModel(doc));
    expect(marks["r1.4.0"]).toBe(1);
    expect(marks["r1.4"]).toBe(1);
    expect(marks["r1"]).toBeGreaterThanOrEqual(4);
  });
});

describe("templates", () => {
  const wf: WorkflowRef = {
    id: "FLOW-001", key: "createRecord", name: "Create Record", description: "", launchedFrom: [],
    inputs: [
      { name: "fullName", kind: "field", type: "string", required: true, description: "Full name", entity: null, options: [] },
      { name: "gender", kind: "field", type: "enum", required: true, description: "", entity: null, options: ["Male", "Female"] },
      { name: "age", kind: "field", type: "integer", required: false, description: "", entity: null, options: [] },
      { name: "record", kind: "record", type: "string", required: true, description: "", entity: "Record", options: [] },
    ],
  };

  it("writes a form from a workflow's inputs against the SDK", () => {
    const jsx = formJsx(wf, { fixed: { record: "props.record.id" }, columns: 2 });
    expect(jsx).toContain("workflow={workflows.createRecord}");
    expect(jsx).toContain('fullName: { label: "Full Name", help: "Full name" },');
    expect(jsx).toContain('gender: { label: "Gender", kind: "select", options: [{ label: "Male", value: "Male" }, { label: "Female", value: "Female" }] },');
    expect(jsx).toContain('age: { label: "Age (optional)", kind: "number" },');
    expect(jsx).toContain("record: { value: props.record.id },");
    expect(jsx).toContain("columns={2}");
  });

  it("writes a table over the page's data with an empty state", () => {
    const jsx = tableJsx("rows", entityColumns({ id: "E", name: "Record", typeName: "Record",
      fields: [{ name: "id", type: "uuid", required: true, label: "Id", options: [] },
               { name: "fullName", type: "string", required: true, label: "Full Name", options: [] },
               { name: "createdAt", type: "timestamp", required: true, label: "", options: [] }] }));
    expect(jsx).toContain("<TableHead>Full Name</TableHead>");
    expect(jsx).not.toContain("<TableHead>Id</TableHead>");
    expect(jsx).toContain('{String(row.fullName ?? "")}');
    expect(jsx).toContain("Nothing here yet.");
  });

  it("turns a button into one that opens a page or runs a workflow, keeping its text and colour", () => {
    const btn = node("r1.1", "Button", { text: "Add", textEditable: true, props: [{ name: "variant", kind: "string", value: "outline", span: [0, 0], valueSpan: null }] });
    const page: PageRef = { id: "PAGE-003", key: "newRecord", name: "New Record", route: "/records/new", params: [] };
    const ops = buttonActionOps(btn, { kind: "page", page });
    const replace = ops.find((o) => o.op === "replaceNode") as { jsx: string };
    expect(replace.jsx).toBe('<Button asChild variant="outline">\n  <Link href={href(pages.newRecord)}>Add</Link>\n</Button>');
    expect(ops.filter((o) => o.op === "addImport")).toHaveLength(3);
    const run = buttonActionOps(btn, { kind: "workflow", workflow: wf }).find((o) => o.op === "replaceNode") as { jsx: string };
    expect(run.jsx).toBe(workflowButtonJsx(wf, { label: "Add" }));
    expect(pageHref({ id: "P", key: "record", name: "Record", route: "/records/[id]", params: ["id"] })).toEqual({ expr: 'href(pages.record, { id: "" })', needsParams: true });
  });

  it("reads what a button does from its shape", () => {
    expect(buttonAction(model.nodes["r1.1"], model).kind).toBe("none");
    const wfBtn = node("x", "WorkflowButton", { props: [{ name: "workflow", kind: "expr", value: "workflows.closeCase", span: [0, 0], valueSpan: null }] });
    expect(buttonAction(wfBtn, model)).toEqual({ kind: "workflow", detail: "closeCase" });
    const linkBtn = node("y", "Button", { children: ["r1.3"] });
    expect(buttonAction(linkBtn, model)).toEqual({ kind: "page", detail: "/nowhere" });
  });
});

// ---------------------------------------------------------------------------
// Preview navigation — a path the app moved to, back to the page it is
// ---------------------------------------------------------------------------

import { matchRoute, pageForPath } from "../Canvas";

describe("preview navigation", () => {
  const pages = [
    { id: "list", route: "/records" }, { id: "new", route: "/records/new" }, { id: "one", route: "/records/[id]" },
    { id: "edit", route: "/records/[id]/edit" }, { id: "home", route: "/" },
  ];
  it("reads a route's parameters from a path", () => {
    expect(matchRoute("/records/42", "/records/[id]")).toEqual({ id: "42" });
    expect(matchRoute("/records/42/edit", "/records/[id]/edit")).toEqual({ id: "42" });
    expect(matchRoute("/records/42/edit", "/records/[id]")).toBeNull();
    expect(matchRoute("/", "/")).toEqual({});
  });
  it("prefers a static page over a parameterised one and keeps the query", () => {
    expect(pageForPath("/records/new", pages)?.id).toBe("new");
    expect(pageForPath("/records/sample-record-2?tab=history", pages)).toEqual({ id: "one", params: { id: "sample-record-2" }, search: { tab: "history" } });
    expect(pageForPath("/records/", pages)?.id).toBe("list");
    expect(pageForPath("/nowhere", pages)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Charts — a widget the page reads in load and draws in view
// ---------------------------------------------------------------------------

import { dataAccess, measureLabel, widgetOfNode, widgetOps, widgetRemovalOps } from "../lib/templates";
import type { WidgetRef } from "../types";

describe("charts", () => {
  const widget: WidgetRef = { id: "WIDGET-001", key: "revenueByStatus", page: "PAGE-001", label: "Revenue by status", description: "", kind: "chart", unit: "currency", size: "md",
    chart: { mark: "bar" }, order: 1, source: { op: "query", entity: "Order", measures: [{ key: "sum_total", aggregation: "sum", field: "total" }], dimensions: [{ field: "status" }], filter: {} } };

  it("reaches the data through the View's parameter, extending a destructured one", () => {
    expect(dataAccess({ ...model, viewParam: { kind: "identifier", name: "props" } }, "x")).toEqual({ expr: "props.x", ops: [] });
    expect(dataAccess({ ...model, viewParam: { kind: "pattern", names: ["rows"], span: [0, 0] } }, "x")).toEqual({ expr: "x", ops: [{ op: "ensureProp", name: "x" }] });
  });

  it("writes the load key, the imports and the card as one transaction", () => {
    const ops = widgetOps({ ...model, viewParam: { kind: "pattern", names: [], span: [0, 0] } }, widget, { parentId: "r1", index: 0 });
    expect(ops.filter((o) => "file" in o && o.file === "load").map((o) => o.op)).toEqual(["addImport", "addImport", "addReturnKey"]);
    expect(ops.find((o) => o.op === "addReturnKey")).toEqual({ op: "addReturnKey", file: "load", key: "revenueByStatus", expr: "await runWidget(widgets.revenueByStatus)" });
    expect(ops[ops.length - 1]).toEqual({ op: "insert", parentId: "r1", index: 0, jsx: "<WidgetView widget={widgets.revenueByStatus} data={revenueByStatus} />" });
    expect(ops.some((o) => o.op === "ensureProp")).toBe(true);
  });

  it("finds a card's widget by its handle and removes both the card and the key", () => {
    const card = node("r1.9", "WidgetView", { props: [{ name: "widget", kind: "expr", value: "widgets.revenueByStatus", span: [0, 0], valueSpan: null }] });
    expect(widgetOfNode(card, [widget])?.id).toBe("WIDGET-001");
    expect(widgetOfNode(card, [])).toBeNull();
    expect(widgetRemovalOps(card, widget)).toEqual([{ op: "remove", ids: ["r1.9"] }, { op: "removeReturnKey", file: "load", key: "revenueByStatus" }]);
  });

  it("names measures in plain words", () => {
    expect(measureLabel({ aggregation: "count" }, "Order")).toBe("How many order records");
    expect(measureLabel({ aggregation: "sum", field: "total" }, "Order")).toBe("Total total");
    expect(measureLabel({ aggregation: "avg", field: "unitPrice" }, "Order")).toBe("Average unit price");
  });
});

// ---------------------------------------------------------------------------
// Interactions and conditions
// ---------------------------------------------------------------------------

import { conditionExpr, parseCondition } from "../GenericSettings";
import { getGroupValue as getSlot, setGroupValue as setSlot } from "../lib/classes";

describe("interactions", () => {
  it("turns a button into one that opens a dialog or shows a message, and reads it back", () => {
    const btn = node("r1.1", "Button", { text: "Add", textEditable: true });
    const dialog = buttonActionOps(btn, { kind: "dialog" }).find((o) => o.op === "replaceNode") as { jsx: string };
    expect(dialog.jsx).toContain("<DialogTrigger asChild>\n    <Button>Add</Button>");
    expect(dialog.jsx).toContain("<DialogTitle>Add</DialogTitle>");
    const msg = buttonActionOps(btn, { kind: "message", text: "Saved!" }).find((o) => o.op === "replaceNode") as { jsx: string };
    expect(msg.jsx).toBe('<Button onClick={() => toast("Saved!")}>Add</Button>');
    const withMsg = node("x", "Button", { props: [{ name: "onClick", kind: "expr", value: '() => toast("Saved!")', span: [0, 0], valueSpan: null }] });
    expect(buttonAction(withMsg, model)).toEqual({ kind: "message", detail: "Saved!" });
    const trigger = node("r1.4", "DialogTrigger"); const inside = node("r1.4.0", "Button");
    expect(buttonAction(inside, { nodes: { ...model.nodes, "r1.4": trigger } })).toEqual({ kind: "dialog", detail: "Opens a dialog" });
  });

  it("keeps a hover colour in its own slot", () => {
    const classes = setSlot("rounded-md bg-card", "background", "hover", "bg-muted");
    expect(classes).toBe("rounded-md bg-card hover:bg-muted");
    expect(getSlot(classes, "background", "")).toBe("bg-card");
    expect(getSlot(classes, "background", "hover")).toBe("bg-muted");
    expect(setSlot(classes, "background", "hover", null)).toBe("rounded-md bg-card");
  });

  it("reads and writes a plain-words condition", () => {
    const d: PageDoc = { ...doc, model: { ...model, viewParam: { kind: "identifier", name: "props" }, loadKeys: ["current"], loadShapes: { current: { kind: "record", entity: "Record" } } } };
    const shown = node("r1.9", "Badge", { condition: 'props.current?.gender === "Female"' });
    const c = parseCondition(d, shown)!;
    expect([c.source.id, c.field, c.op, c.value]).toEqual(["current", "gender", "is", "Female"]);
    expect(conditionExpr(c)).toBe('props.current?.gender === "Female"');
    const has = parseCondition(d, node("r1.9", "Badge", { condition: "props.current" }))!;
    expect(has.op).toBe("has");
    expect(conditionExpr({ ...c, op: "empty" })).toBe("!props.current?.gender");
    expect(parseCondition(d, node("r1.9", "Badge", { condition: "isAdmin(props.user)" }))).toBeNull();
  });
});

import { MARKS, markProblem } from "../lib/templates";

describe("every chart the app draws", () => {
  it("offers all ten marks and says what each needs", () => {
    expect(MARKS.map((m) => m.value)).toEqual(["bar", "line", "area", "pie", "donut", "funnel", "radar", "treemap", "heatmap", "scatter"]);
    expect(markProblem("bar", 1, 1)).toBeNull();
    expect(markProblem("heatmap", 1, 1)).toBe("needs a second grouping (“also split by”)");
    expect(markProblem("scatter", 1, 1)).toBe("needs a second number (“and also”)");
    expect(markProblem("scatter", 1, 2)).toBeNull();
    expect(markProblem("pie", 2, 1)).toBe("groups by one thing only — remove the split");
    expect(markProblem("pie", 1, 2)).toBe("shows one number only — remove the extra");
    expect(markProblem("bar", 2, 2)).toBe("with a split, shows one number only");
  });
});
