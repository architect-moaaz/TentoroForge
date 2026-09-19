/**
 * The store's transaction path: an edit is sent against the loaded revision,
 * the answer replaces what is held, a stale answer reloads rather than
 * overwrites, a refused answer leaves the page as it was, and undo is a
 * restore of the recorded revision.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({ toast: { warning: vi.fn(), error: vi.fn(), info: vi.fn(), success: vi.fn() } }));

const calls: { name: string; args: unknown[] }[] = [];
const api = {
  pages: vi.fn(), open: vi.fn(), apply: vi.fn(), restore: vi.fn(), check: vi.fn(), propose: vi.fn(),
  applyProposal: vi.fn(), discardProposal: vi.fn(), history: vi.fn(),
};
vi.mock("../api", async () => {
  const real = await vi.importActual<typeof import("../api")>("../api");
  return { ...real, editorApi: new Proxy({}, { get: (_, name: string) => (...args: unknown[]) => { calls.push({ name, args }); return (api as Record<string, ReturnType<typeof vi.fn>>)[name](...args); } }) };
});

import { EditorApiError } from "../api";
import { useEditorStore } from "../store";
import type { PageDoc, PageModel } from "../types";

function model(text: string): PageModel {
  return {
    ok: true, roots: [{ id: "r0", owner: "View" }], imports: [], loadKeys: [], viewProps: [],
    nodes: {
      r0: { id: "r0", parent: null, index: 0, type: "div", kind: "element", props: [], text: null, textEditable: false, inner: "", innerSpan: [0, 0], selfClosing: false, span: [0, 0], wrapperSpan: null, line: 1, endLine: 3, context: null, children: ["r0.0"] },
      "r0.0": { id: "r0.0", parent: "r0", index: 0, type: "h1", kind: "element", props: [], text, textEditable: true, inner: text, innerSpan: [0, 0], selfClosing: false, span: [0, 0], wrapperSpan: null, line: 2, endLine: 2, context: null, children: [] },
    },
  };
}

function doc(revision: string, text: string): PageDoc {
  return {
    page: { id: "PAGE-001", name: "Records", route: "/records", purpose: "" }, coded: true, revision, model: model(text),
    source: { view: `<h1>${text}</h1>`, load: "" }, registry: { version: "1", components: [] }, pages: [], workflows: [], entities: [], theme: {}, history: [],
  };
}

beforeEach(async () => {
  calls.length = 0;
  Object.values(api).forEach((f) => f.mockReset());
  api.pages.mockResolvedValue({ entryPage: "PAGE-001", pages: [{ id: "PAGE-001", name: "Records", route: "/records", purpose: "", pattern: null, access: "authenticated", coded: true, module: null, navigatesTo: [] }] });
  api.open.mockResolvedValue(doc("rev1", "Records"));
  await useEditorStore.getState().init("project-1");
});

describe("the store's transactions", () => {
  it("sends an edit against the loaded revision and holds what came back, undoable as one step", async () => {
    api.apply.mockResolvedValue({ revision: "rev2", model: model("Cases"), source: { view: "<h1>Cases</h1>", load: "" }, checked: false, unchanged: false, version: 3 });
    const s = useEditorStore.getState();
    s.select(["r0.0"]);
    expect(await s.setText("r0.0", "Cases")).toBe(true);
    const apply = calls.find((c) => c.name === "apply")!;
    expect(apply.args.slice(1)).toEqual(["PAGE-001", "rev1", [{ op: "setText", id: "r0.0", text: "Cases" }], "Change text"]);
    const st = useEditorStore.getState();
    expect(st.doc?.revision).toBe("rev2");
    expect(st.doc?.model?.nodes["r0.0"].text).toBe("Cases");
    expect(st.saveState).toBe("saved");
    expect(st.undoStack.map((u) => [u.label, u.before.revision, u.after.revision])).toEqual([["Change text", "rev1", "rev2"]]);
    expect(st.selection).toEqual(["r0.0"]);

    api.restore.mockResolvedValue({ revision: "rev1", model: model("Records"), source: { view: "<h1>Records</h1>", load: "" }, checked: false, unchanged: false, version: 4 });
    await useEditorStore.getState().undo();
    const restore = calls.find((c) => c.name === "restore")!;
    expect(restore.args.slice(1)).toEqual(["PAGE-001", "rev1", "rev2"]);
    expect(useEditorStore.getState().doc?.revision).toBe("rev1");
    expect(useEditorStore.getState().redoStack).toHaveLength(1);
  });

  it("reloads on a stale revision instead of overwriting", async () => {
    api.apply.mockRejectedValue(new EditorApiError({ status: 409, code: "stale", message: "The page changed", current: "rev9" }));
    api.open.mockResolvedValue(doc("rev9", "Someone else's title"));
    expect(await useEditorStore.getState().setText("r0.0", "Mine")).toBe(false);
    const st = useEditorStore.getState();
    expect(st.doc?.revision).toBe("rev9");
    expect(st.doc?.model?.nodes["r0.0"].text).toBe("Someone else's title");
    expect(st.undoStack).toEqual([]);
    expect(st.saveState).toBe("saved");
  });

  it("keeps the last valid page when a change is refused, and shows why", async () => {
    api.apply.mockRejectedValue(new EditorApiError({ status: 422, code: "does-not-compile", message: "That change would break the page, so it was not saved.",
      findings: [{ file: "view.tsx", line: 2, code: "TS2322", raw: "x", plain: "Line 2 of the page: not accepted", severity: "must-fix" }] }));
    expect(await useEditorStore.getState().setProp("r0.0", "size", { kind: "string", value: "huge" })).toBe(false);
    const st = useEditorStore.getState();
    expect(st.doc?.revision).toBe("rev1");
    expect(st.lastFindings[0].plain).toBe("Line 2 of the page: not accepted");
    expect(st.saveState).toBe("saved");
  });

  it("marks the save as failed when the connection is lost, without claiming it saved", async () => {
    api.apply.mockRejectedValue(new TypeError("Failed to fetch"));
    expect(await useEditorStore.getState().setText("r0.0", "x")).toBe(false);
    const st = useEditorStore.getState();
    expect(st.saveState).toBe("failed");
    expect(st.saveError).toBe("Failed to fetch");
    expect(st.doc?.revision).toBe("rev1");
  });

  it("drops a Smith proposal when the selection changes, and refuses to apply a stale one", async () => {
    const s = useEditorStore.getState();
    s.select(["r0.0"]);
    api.propose.mockResolvedValue({ id: "p1", pageId: "PAGE-001", baseRevision: "rev1", prompt: "bigger", annotation: "", selection: { type: "component", nodeIds: ["r0.0"] },
      summary: "Bigger title", explanation: "", needs: [], questions: [], replacements: [{ nodeId: "r0.0", type: "h1", before: "<h1>Records</h1>", after: "<h1 className=\"text-3xl\">Records</h1>" }],
      imports: [], expandsScope: [], refused: [], findings: [], valid: true, status: "ready", createdAt: "", timing: { generationMs: 1, validationMs: 1 } });
    await s.askSmith("bigger");
    expect(useEditorStore.getState().smith.proposal?.id).toBe("p1");
    useEditorStore.getState().select(["r0"]);
    expect(useEditorStore.getState().smith.proposal).toBeNull();

    useEditorStore.getState().select(["r0.0"]);
    await useEditorStore.getState().askSmith("bigger");
    useEditorStore.setState((st) => ({ doc: { ...st.doc!, revision: "rev2" } }));
    await useEditorStore.getState().applyProposal();
    expect(calls.some((c) => c.name === "applyProposal")).toBe(false);
    expect(useEditorStore.getState().smith.error).toContain("changed since");
  });
});
