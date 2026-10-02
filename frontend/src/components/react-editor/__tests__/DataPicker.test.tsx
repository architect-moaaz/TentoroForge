/**
 * A value with no parts still picks.
 *
 * A number the page loads (`props.total`) has one choice in "Which part": its
 * value, which `fieldChoices` names "". A Radix <Select.Item> refuses an empty
 * value — it means "clear the selection" — so opening the settings of an
 * element bound to such a source crashed the whole editor
 * (2026-09-22: "A <Select.Item /> must have a value prop that is not an
 * empty string", from SettingsDrawer down to DataPicker).
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { pageSources } from "../lib/data";
import { DataPicker } from "../DataPicker";
import type { ModelNode, PageDoc, PageModel } from "../types";

function node(id: string, type: string, extra: Partial<ModelNode> = {}): ModelNode {
  return {
    id, parent: id.includes(".") ? id.slice(0, id.lastIndexOf(".")) : null, index: 0, type,
    kind: "element", props: [], text: null, textEditable: false,
    inner: null, innerSpan: null, selfClosing: false, span: [0, 0], wrapperSpan: null, line: 1, endLine: 1,
    context: null, children: [], ...extra,
  };
}

const model: PageModel = {
  ok: true, roots: [{ id: "r0", owner: "View" }], imports: [], viewProps: ["props"],
  viewParam: { kind: "identifier", name: "props" },
  loadKeys: ["total"],
  loadShapes: { total: { kind: "number", via: { how: "server", call: "count", entity: "Record" } } },
  nodes: { r0: node("r0", "span", { exprOnly: 'String(props.total ?? "")' }) },
};

const doc: PageDoc = {
  page: { id: "P", name: "Records", route: "/records", purpose: "" }, coded: true, revision: "r", model,
  source: { view: "", load: "" }, registry: { version: "1", components: [] }, pages: [], workflows: [],
  theme: {}, history: [], entities: [{ id: "E", name: "Record", typeName: "Record", fields: [] }],
  widgets: [], samples: {},
};

function render(ui: React.ReactElement) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(ui));
  return host;
}

describe("DataPicker on a source with no parts", () => {
  const total = pageSources(doc).find((s) => s.id === "total")!;

  it("renders the value bound to a number without crashing", () => {
    const host = render(<DataPicker doc={doc} nodeId="r0" value={{ source: total, field: "" }} onChange={() => {}} />);
    expect(host.textContent).toContain("Its value");
  });
});
