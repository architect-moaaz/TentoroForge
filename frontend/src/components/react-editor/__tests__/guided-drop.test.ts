/**
 * A chart dropped on the page asks its questions there and then.
 *
 * A chart, a number tile and a form are "guided": they need answers (which
 * records, what to count) before anything can be inserted. Dropping one used
 * to select the target, switch the left panel to Add and toast "click it in
 * Add" — a drop that put nothing on the page and asked the person to do it
 * again (NK, 2026-09-22: "when I drag and drop the chart I cannot see it").
 * The drop now opens the guide itself, and the answer lands where the chart
 * was dropped.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { useEditorStore } from "../store";
import type { ComponentDef, PageDoc, PageModel } from "../types";

const model: PageModel = {
  ok: true, roots: [{ id: "r0", owner: "View" }], imports: [], loadKeys: [], viewProps: [],
  nodes: {
    r0: { id: "r0", parent: null, index: 0, type: "div", kind: "element", props: [], text: null, textEditable: false, inner: "", innerSpan: [0, 0], selfClosing: false, span: [0, 0], wrapperSpan: null, line: 1, endLine: 3, context: null, children: ["r0.0"] },
    "r0.0": { id: "r0.0", parent: "r0", index: 0, type: "h1", kind: "element", props: [], text: "Records", textEditable: true, inner: "Records", innerSpan: [0, 0], selfClosing: false, span: [0, 0], wrapperSpan: null, line: 2, endLine: 2, context: null, children: [] },
  },
};

const chart = { id: "chart", label: "Chart", category: "Data", status: "ready", guide: "chart", jsx: "<Chart />", imports: [] } as unknown as ComponentDef;
const card = { id: "card", label: "Card", category: "Layout", status: "ready", guide: null, jsx: "<Card />", imports: [] } as unknown as ComponentDef;

const doc: PageDoc = {
  page: { id: "PAGE-001", name: "Records", route: "/records", purpose: "" }, coded: true, revision: "rev1", model,
  source: { view: "<h1>Records</h1>", load: "" }, registry: { version: "1", components: [chart, card] },
  pages: [], workflows: [], entities: [], theme: {}, history: [],
};

beforeEach(() => {
  useEditorStore.setState({ doc, projectId: "project-1", mode: "design", selection: [], pendingGuide: null, leftTab: "pages" });
});

describe("dropping a guided kind", () => {
  it("opens its questions at once, aimed at the drop spot, and inserts nothing yet", async () => {
    const s = useEditorStore.getState();
    // Dropped on the lower half of the heading: after it, inside its parent.
    expect(await s.dropComponent("chart", "r0.0", { y: 0.9 })).toBe(false);
    const st = useEditorStore.getState();
    expect(st.pendingGuide).toEqual({ compId: "chart", parentId: "r0", index: 1 });
    expect(st.selection).toEqual(["r0"]);
    expect(st.leftTab).toBe("pages"); // nobody is sent to Add to do it again
  });

  it("closes cleanly", () => {
    useEditorStore.getState().setPendingGuide({ compId: "chart", parentId: "r0", index: null });
    useEditorStore.getState().setPendingGuide(null);
    expect(useEditorStore.getState().pendingGuide).toBeNull();
  });
});
