/**
 * EVIDENCE — why do 22 components refuse a bindProp on their first prop?
 *
 * `bindProp` writes `{ $binding }` unconditionally (patches/src/apply.ts), so an
 * absent value can only mean the dispatch was REJECTED by validateForCommit,
 * which sets lastError and returns without committing (editor-store.ts:154).
 * The Tier-1 run did not capture lastError on binding cells — this closes that
 * gap and prints the actual rejection message rather than inferring one.
 */
import { describe, it, expect } from "vitest";
import { starterRegistry } from "@forge/registry";
import { buildDroppedNode } from "@/components/canvas/hooks/useDrop";
import { useEditorStore } from "@/lib/editor-store";

const NAV_FLOW = {
  version: "1.0", initialPage: "home",
  pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }],
  transitions: [], guards: {},
};
const EMPTY_TOKENS = { color: {}, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {} };

const SUSPECTS = ["Breadcrumb","Tabs","Table","AppShell","Sparkline","DataGrid","EditableLineGrid",
  "Timeline","TableSortable","ApprovalStepper","FilterBar","CommandPalette","ActivityFeed",
  "KeyValueList","SplitArc","Tree","Transfer","Calendar","Kanban","ResourceTimeline","Carousel","Lightbox"];
const CONTROLS = ["Button", "Badge", "Input", "Card"]; // known-good, to prove the probe works

function seed() {
  useEditorStore.setState({ lastError: null } as any);
  useEditorStore.getState().setInitial({
    pageSchemas: {
      home: {
        schemaVersion: "2", id: "home", route: "/",
        root: { id: "root", type: "Container", props: {}, children: [] },
      },
    },
    navFlow: NAV_FLOW as any, tokens: EMPTY_TOKENS,
  } as any);
}
const home = () => (useEditorStore.getState().artifacts as any).pageSchemas.home;
const err = () => (useEditorStore.getState() as any).lastError ?? null;

describe("EVIDENCE — bindProp rejections", () => {
  it("prints the rejection reason per component", () => {
    for (const name of [...CONTROLS, ...SUSPECTS]) {
      const entry = (starterRegistry as any)[name];
      const first = Object.keys(entry?.props ?? {})[0];
      if (!first) { console.log(`[BIND] ${name.padEnd(20)} (no props)`); continue; }

      seed();
      const store = useEditorStore.getState();
      const node = buildDroppedNode(name);
      store.dispatch({ type: "insertNode", pageId: "home", parentId: "root", index: 0, node } as any);
      const inserted = !!(home().root.children ?? []).find((c: any) => c.id === node.id);

      useEditorStore.setState({ lastError: null } as any);
      store.dispatch({
        type: "bindProp", pageId: "home", nodeId: node.id, propName: first, binding: "user.name",
      } as any);

      const after = (home().root.children ?? []).find((c: any) => c.id === node.id);
      const val = after?.props?.[first];
      const rejection = err();
      const d = entry.props[first];

      console.log(
        `[BIND] ${name.padEnd(20)} prop=${first.padEnd(14)} type=${String(d.type).padEnd(8)} ` +
        `inserted=${inserted} committed=${val !== undefined} ` +
        (rejection ? `REJECTED: ${String(rejection).replace(/\s+/g, " ").slice(0, 150)}` : "ok"),
      );
    }
    expect(true).toBe(true);
  }, 300_000);
});
