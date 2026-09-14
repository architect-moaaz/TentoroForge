/**
 * REPRODUCTION — "the All / sm / md / lg / xl switcher at the top of the Props
 * panel does nothing on input components".
 *
 * The panel writes a responsive envelope when a non-default breakpoint is
 * active (PropertiesPanel.writePropAtBp): `"md"` becomes
 * `{ default: "md", sm: "lg" }`. This asks the only two questions that decide
 * whether that edit survives:
 *
 *   1. does the store COMMIT it, or does validateForCommit reject the action
 *      (editor-store.ts:154 — a rejected dispatch sets lastError and returns,
 *      which on screen is a control that snaps back and no other feedback)?
 *   2. if it commits, does the Engine RESOLVE it back to a usable value?
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useEditorStore } from "@/lib/editor-store";
import { starterRegistry } from "@forge/registry";
import { validateForCommit } from "@forge/patches";

const NAV_FLOW = {
  version: "1.0", initialPage: "home",
  pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }],
  transitions: [], guards: {},
};
const EMPTY_TOKENS = {
  color: {}, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {},
};

function seedWith(node: any) {
  useEditorStore.getState().setInitial({
    pageSchemas: {
      home: {
        schemaVersion: "2", id: "home", route: "/",
        root: { id: "root", type: "Container", props: {}, children: [node] },
      },
    },
    navFlow: NAV_FLOW as any,
    tokens: EMPTY_TOKENS,
  } as any);
}
const home = () => (useEditorStore.getState().artifacts as any).pageSchemas.home;

/** Exactly what PropertiesPanel.writePropAtBp produces for a non-default bp. */
function writePropAtBp(currentRaw: any, bp: string, newValue: any): any {
  const BP = new Set(["default", "sm", "md", "lg", "xl"]);
  const isResp = (v: any) => v && typeof v === "object" && !Array.isArray(v)
    && Object.keys(v).length > 0 && Object.keys(v).every((k) => BP.has(k));
  if (bp === "default") return isResp(currentRaw) ? { ...currentRaw, default: newValue } : newValue;
  if (isResp(currentRaw)) return { ...currentRaw, [bp]: newValue };
  return { default: currentRaw, [bp]: newValue };
}

const INPUT_COMPONENTS = (Object.values(starterRegistry) as any[])
  .filter((e) => e.category === "input" && !e.hidden)
  .map((e) => e.name);

describe("REPRO — breakpoint override on input components", () => {
  beforeEach(() => {
    useEditorStore.setState({ lastError: null } as any);
  });

  it("reports how many input components accept a responsive prop value", () => {
    const rejected: Array<{ name: string; prop: string; err: string }> = [];
    const committed: string[] = [];
    const skipped: string[] = [];

    for (const name of INPUT_COMPONENTS) {
      const entry = (starterRegistry as any)[name];
      // First prop the panel would show — the one a user reaches for first.
      const propName = Object.keys(entry.props ?? {})[0];
      if (!propName) { skipped.push(name); continue; }

      const node = { id: "n1", type: name, props: { ...(entry.props?.[propName]?.default !== undefined
        ? { [propName]: entry.props[propName].default } : {}) }, children: [] };
      seedWith(node);

      const raw = (home().root.children[0].props ?? {})[propName];
      const responsive = writePropAtBp(raw, "sm", "lg");

      useEditorStore.getState().dispatch({
        type: "updateProp", pageId: "home", nodeId: "n1",
        propName, value: responsive,
      } as any);

      const after = home().root.children[0].props?.[propName];
      const err = (useEditorStore.getState() as any).lastError;
      const landed = JSON.stringify(after) === JSON.stringify(responsive);
      if (landed) committed.push(name);
      else rejected.push({ name, prop: propName, err: String(err ?? "(no lastError)").slice(0, 120) });
    }

    console.log(`[REPRO] input components: ${INPUT_COMPONENTS.length}`);
    console.log(`[REPRO] committed responsive value: ${committed.length}`);
    console.log(`[REPRO] REJECTED (edit silently dropped): ${rejected.length}`);
    for (const r of rejected.slice(0, 12)) {
      console.log(`   ✗ ${r.name}.${r.prop} — ${r.err}`);
    }
    if (skipped.length) console.log(`[REPRO] skipped (no props): ${skipped.join(", ")}`);

    expect(INPUT_COMPONENTS.length).toBeGreaterThan(0);
  });

  it("checks validateForCommit directly on a responsive envelope", () => {
    seedWith({ id: "n1", type: "Input", props: { name: "email", type: "text" }, children: [] });
    const arts = useEditorStore.getState().artifacts as any;
    const withResp = JSON.parse(JSON.stringify(arts));
    withResp.pageSchemas.home.root.children[0].props.type = { default: "text", sm: "password" };
    const errs = validateForCommit(withResp, starterRegistry as any);
    console.log("[REPRO] validateForCommit on responsive prop →",
      errs.length === 0 ? "ACCEPTED" : `REJECTED: ${errs.slice(0, 2).join(" | ")}`);
    expect(Array.isArray(errs)).toBe(true);
  });
});
