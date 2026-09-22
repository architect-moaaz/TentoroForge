import { describe, expect, it } from "vitest";

import { bandOf, bindingExpr, fieldChoices, pageSources, readBinding, rowContext, sampleOf, sampleQuery, viaLabel, withExpr, withString } from "../lib/data";
import type { ModelNode, PageDoc, PageModel } from "../types";

function node(id: string, type: string, extra: Partial<ModelNode> = {}): ModelNode {
  return {
    id, parent: id.includes(".") ? id.slice(0, id.lastIndexOf(".")) : null, index: 0, type,
    kind: /^[a-z]/.test(type) ? "element" : "component", props: [], text: null, textEditable: false,
    inner: null, innerSpan: null, selfClosing: false, span: [0, 0], wrapperSpan: null, line: 1, endLine: 1,
    context: null, children: [], ...extra,
  };
}

const model: PageModel = {
  ok: true, roots: [{ id: "r0", owner: "View" }], imports: [], viewProps: ["props"], viewParam: { kind: "identifier", name: "props" },
  loadKeys: ["records", "total", "current", "male"],
  loadShapes: { records: { kind: "rows", entity: "Record", via: { how: "server", call: "list", entity: "Record" } }, total: { kind: "number", via: { how: "server", call: "count", entity: "Record" } },
                current: { kind: "record", entity: "Record", via: { how: "server", call: "record", entity: "Record" } }, male: { kind: "widget", widget: "male", via: { how: "widget", widget: "male" } } },
  nodes: {
    r0: node("r0", "div", { children: ["r0.0", "r0.1", "r0.2"] }),
    "r0.0": node("r0.0", "h1", { exprOnly: "props.current?.fullName ?? \"\"" }),
    "r0.1": node("r0.1", "tbody", { children: ["r0.1.0"] }),
    "r0.1.0": node("r0.1.0", "tr", { context: "repeat", repeat: { source: "props.records", variable: "row" }, children: ["r0.1.0.0"] }),
    "r0.1.0.0": node("r0.1.0.0", "td", { exprOnly: 'String(row.age ?? "")' }),
    "r0.2": node("r0.2", "span", { text: "Hello", textEditable: true }),
  },
};

const doc: PageDoc = {
  page: { id: "P", name: "Records", route: "/records", purpose: "" }, coded: true, revision: "r", model, source: { view: "", load: "" },
  registry: { version: "1", components: [] }, pages: [], workflows: [], theme: {}, history: [],
  entities: [{ id: "E", name: "Record", typeName: "Record", fields: [
    { name: "id", type: "uuid", required: true, label: "Id", options: [] }, { name: "fullName", type: "string", required: true, label: "Full Name", options: [] },
    { name: "gender", type: "string", required: true, label: "Gender", options: ["Male", "Female"] }, { name: "age", type: "integer", required: true, label: "Age", options: [] },
    { name: "createdAt", type: "datetime", required: true, label: "Created", options: [] }] }],
  widgets: [{ id: "W", key: "male", page: "P", label: "Male records", description: "", kind: "metric", unit: "number", size: "sm", chart: null, order: 1, source: { op: "query", entity: "Record", measures: [{ key: "count", aggregation: "count" }], dimensions: [], filter: {} } }],
  samples: { Record: [
    { id: "s1", fullName: "Amara Okafor", gender: "Male", age: 22, createdAt: "2026-09-01T09:00:00.000Z" },
    { id: "s2", fullName: "Bao Nguyen", gender: "Female", age: 29, createdAt: "2026-09-04T09:00:00.000Z" },
    { id: "s3", fullName: "Chiara Rossi", gender: "Male", age: 36, createdAt: "2026-10-02T09:00:00.000Z" }] },
};

describe("the page's data in a person's words", () => {
  it("names each thing the page loads by what it is", () => {
    expect(pageSources(doc).map((s) => [s.id, s.label, s.expr])).toEqual([
      ["records", "The list of records", "props.records"], ["total", "Total (a number)", "props.total"],
      ["current", "The record this page shows", "props.current"], ["male", "Male records", "props.male"]]);
  });

  it("says where each thing comes from, in a sentence", () => {
    expect(pageSources(doc).map((s) => s.via)).toEqual([
      "Read on the server from records", "Counted on the server across records",
      "Read on the server from records, the one the page is about", "Worked out on the server by this widget's query"]);
    expect(viaLabel({ kind: "string", via: { how: "address" } }, null)).toBe("Taken from the page's address (URL)");
    expect(viaLabel({ kind: "unknown", via: { how: "api", url: "/api/rates" } }, null)).toBe("Fetched from /api/rates");
    expect(viaLabel({ kind: "string", via: { how: "fixed" } }, null)).toBe("A fixed value written into the page");
    expect(viaLabel({ kind: "string" }, null)).toBeUndefined();
  });

  it("knows the row a repeated cell sits in", () => {
    const row = rowContext(doc, "r0.1.0.0")!;
    expect(row.label).toBe("Each record in the list");
    expect(row.expr).toBe("row");
    expect(rowContext(doc, "r0.2")).toBeNull();
  });

  it("offers a record's fields with an example, and a list's count", () => {
    const [current, records] = [pageSources(doc)[2], pageSources(doc)[0]];
    expect(fieldChoices(doc, current).map((f) => [f.name, f.sample])).toEqual([["fullName", "Amara Okafor"], ["gender", "Male"], ["age", 22], ["createdAt", "2026-09-01T09:00:00.000Z"]]);
    expect(fieldChoices(doc, records)).toEqual([{ name: "length", label: "How many there are", type: "number", sample: 3 }]);
    expect(sampleOf(doc, current, "createdAt")).toMatch(/2026/);
  });

  it("reads what an element shows back into a source and a field", () => {
    const heading = readBinding(doc, model.nodes["r0.0"]);
    expect(heading).toMatchObject({ kind: "field", field: "fullName" });
    expect((heading as { source: { id: string } }).source.id).toBe("current");
    const cell = readBinding(doc, model.nodes["r0.1.0.0"]);
    expect(cell).toMatchObject({ kind: "field", field: "age" });
    expect((cell as { source: { row?: boolean } }).source.row).toBe(true);
    expect(readBinding(doc, model.nodes["r0.2"])).toEqual({ kind: "text" });
    expect(readBinding(doc, node("x", "p", { exprOnly: "format(props.total)" }))).toEqual({ kind: "custom", code: "format(props.total)" });
  });

  it("writes a binding as safe text: nullable records, numbers as strings, strings bare", () => {
    const [records, , current] = pageSources(doc);
    expect(bindingExpr(current, "fullName", { text: true, type: "string" })).toBe('props.current?.fullName ?? ""');
    expect(bindingExpr(rowContext(doc, "r0.1.0.0")!, "age", { text: true, type: "integer" })).toBe('String(row.age ?? "")');
    expect(bindingExpr(rowContext(doc, "r0.1.0.0")!, "fullName", { text: true, type: "string" })).toBe("row.fullName");
    expect(bindingExpr(records, "length", { text: true, type: "number" })).toBe('String(props.records.length ?? "")');
  });

  it("edits object entries without touching what it does not know", () => {
    const entries = [{ key: "label", kind: "string" as const, value: "Name", code: '"Name"' }, { key: "validate", kind: "expr" as const, code: "(v) => v.length > 1" }];
    const out = withString(entries, "label", "Full name");
    expect(out.find((e) => e.key === "validate")?.code).toBe("(v) => v.length > 1");
    expect(out.find((e) => e.key === "label")).toEqual({ key: "label", kind: "string", value: "Full name", code: '"Full name"' });
    expect(withString(entries, "label", "")).toHaveLength(1);
    expect(withExpr(entries, "value", "props.current.id").find((e) => e.key === "value")?.code).toBe("props.current.id");
  });

  it("previews a chart's query over the sample rows", () => {
    const rows = doc.samples!.Record;
    expect(sampleQuery(rows, { measures: [{ key: "count", aggregation: "count" }], dimensions: [{ field: "gender" }] })).toEqual([{ gender: "Male", count: 2 }, { gender: "Female", count: 1 }]);
    expect(sampleQuery(rows, { measures: [{ key: "avg_age", aggregation: "avg", field: "age" }], dimensions: [{ field: "createdAt", bucket: "month" }] })).toEqual([{ createdAt: "2026-09", avg_age: 25.5 }, { createdAt: "2026-10", avg_age: 36 }]);
    expect(sampleQuery(rows, { measures: [{ key: "count", aggregation: "count" }], dimensions: [{ field: "gender" }], filter: { gender: ["Female"] } })).toEqual([{ gender: "Female", count: 1 }]);
    expect(sampleQuery(rows, { measures: [{ key: "total_age", aggregation: "sum", field: "age" }], dimensions: [], limit: 1 })).toEqual([{ total_age: 87 }]);
  });
});

describe("a number grouped into ranges", () => {
  const rows = [{ age: 12 }, { age: 25 }, { age: 30 }, { age: 44 }, { age: 70 }, { age: null }];
  const ranges = [{ label: "Under 18", to: 18 }, { label: "18–30", from: 18, to: 31 }, { from: 31, to: 61 }, { label: "61+", from: 61 }];

  it("labels each band, keeps the declared order, and drops values in no band", () => {
    const out = sampleQuery(rows, { measures: [{ key: "n", aggregation: "count" }], dimensions: [{ field: "age", ranges }] });
    expect(out).toEqual([
      { age: "Under 18", n: 1 }, { age: "18–30", n: 2 }, { age: "31–61", n: 1 }, { age: "61+", n: 1 },
    ]);
  });

  it("reads a value exactly on an edge into the band it starts", () => {
    expect(bandOf(18, ranges)).toBe("18–30");
    expect(bandOf(31, ranges)).toBe("31–61");
    expect(bandOf("x", ranges)).toBeUndefined();
  });
});
