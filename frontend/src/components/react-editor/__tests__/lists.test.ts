import { describe, expect, it } from "vitest";

import { listKeyFor, listOf, optionsSummary, repeatableSources } from "../lib/lists";
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
  loadKeys: ["records", "current", "custom"],
  loadShapes: {
    records: { kind: "rows", entity: "Record", via: { how: "server", call: "list", entity: "Record" }, options: { sort: "age", order: "desc", limit: 3, where: { gender: "Male" } } },
    current: { kind: "record", entity: "Record", via: { how: "server", call: "record", entity: "Record" } },
    custom: { kind: "rows", entity: "Record", via: { how: "server", call: "list", entity: "Record" }, optionsCustom: true },
  },
  nodes: {
    r0: node("r0", "div", { children: ["r0.0", "r0.1"] }),
    "r0.0": node("r0.0", "Card", { kind: "component", context: "repeat", repeat: { source: "props.records", variable: "row" }, children: ["r0.0.0"] }),
    "r0.0.0": node("r0.0.0", "p", { exprOnly: "row.fullName" }),
    "r0.1": node("r0.1", "span", { text: "Hello", textEditable: true }),
  },
};
const doc: PageDoc = {
  page: { id: "P", name: "Records", route: "/records", purpose: "" }, coded: true, revision: "r", model, source: { view: "", load: "" },
  registry: { version: "1", components: [] }, pages: [], workflows: [], theme: {}, history: [], widgets: [], samples: {},
  entities: [{ id: "E", name: "Record", typeName: "Record", fields: [
    { name: "id", type: "uuid", required: true, label: "Id", options: [] }, { name: "fullName", type: "string", required: true, label: "Full Name", options: [] },
    { name: "gender", type: "string", required: true, label: "Gender", options: ["Male", "Female"] }, { name: "age", type: "integer", required: true, label: "Age", options: [] }] }],
};

describe("a list on the page", () => {
  it("is found from the repeated element and from anything inside it", () => {
    expect(listOf(doc, "r0.0")?.key).toBe("records");
    expect(listOf(doc, "r0.0.0")?.key).toBe("records");
    expect(listOf(doc, "r0.0")?.editable).toBe(true);
    expect(listOf(doc, "r0.1")).toBeNull();
  });

  it("says how it is read in a sentence, and when code decides", () => {
    const l = listOf(doc, "r0.0")!;
    expect(optionsSummary(l.options, l.entity)).toBe("highest or newest age first, only where gender is Male, 3 at most");
    expect(optionsSummary(null, l.entity)).toBe("every row, in the order they were added");
    expect(repeatableSources(doc).map((s) => s.id)).toEqual(["records", "custom"]);
  });

  it("names a new list after its entity, without clashing", () => {
    expect(listKeyFor("Record", ["records"])).toBe("records2");
    expect(listKeyFor("OrderLine", [])).toBe("orderLines");
    expect(listKeyFor("Address", [])).toBe("address");
  });
});
