/**
 * TIER 1 — the deterministic full matrix.
 *
 * Drives the REAL editor-store, the REAL starterRegistry and the REAL Engine
 * (no paraphrase) over every one of the 133 palette components:
 *   • all 474 registry prop descriptors
 *   • all 11 reachable style keys per component
 *   • the bind / unbind round trip
 *
 * It MEASURES; it does not gate. A component behaving badly is recorded and the
 * sweep continues, because a suite that dies on the first failure says nothing
 * about the other 2,000 cells.
 *
 * ── Why this file is shaped the way it is ────────────────────────────────────
 * Three rounds of false findings earlier in this work all had the same cause:
 * the probe was broken and blamed the product. So every cell carries its own
 * PRECONDITIONS, and a cell whose preconditions fail is recorded as
 * HARNESS-BLOCKED — never as a defect. Specifically:
 *   - the action payload field names are `propName` / `styleKey`+`value` /
 *     `path`; getting them wrong is a silent no-op that reads as "dead control"
 *   - `dispatch` runs validateForCommit and, on error, sets `lastError` and
 *     RETURNS without committing (editor-store.ts:154) — a rejected edit is a
 *     real finding, but a different one from "the control did nothing"
 *   - `updateStyle` with "" DELETES the key by design (apply.ts:152-158)
 *   - `resolveStyle` silently drops keys outside its 19-entry map, by design
 *
 * Observables asserted for style come from applyStyleSlot
 * (renderer/runtime/style-slot.ts:13-58) and are exact, not fuzzy:
 *   padding→style.padding, radius→style.borderRadius, shadow→style.boxShadow,
 *   background→style.background   (each `var(--token-<ref dots→dashes>)`)
 *   width, height, minWidth, maxWidth, minHeight, maxHeight
 *                                 (emitted RAW, deliberately not token-wrapped)
 *   motion                        (a data-motion ATTRIBUTE, absent when "none")
 *
 * Output: tests/matrix/tier1-ledger.json — one row per cell, including cells
 * that could not be reached and why. Silent truncation would itself be a defect.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import React from "react";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import { starterRegistry } from "@forge/registry";
import { validateDrop, buildDroppedNode } from "@/components/canvas/hooks/useDrop";
import { useEditorStore } from "@/lib/editor-store";
import * as fs from "node:fs";
import * as path from "node:path";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !window.matchMedia) {
  // @ts-expect-error minimal polyfill
  window.matchMedia = (q: string) => ({
    matches: false, media: q, onchange: null,
    addListener() {}, removeListener() {}, addEventListener() {},
    removeEventListener() {}, dispatchEvent() { return false; },
  });
}
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}

const NAV_FLOW = {
  version: "1.0", initialPage: "home",
  pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }],
  transitions: [], guards: {},
};
const EMPTY_TOKENS = {
  color: {}, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {},
};

/**
 * The 11 reachable style keys, each with the EMITTED form to look for.
 *
 * `emitted` is deliberately separate from `value`. A first version of this file
 * searched descendants for the token REF ("spacing.4") while the DOM actually
 * carries the resolved var ("var(--token-spacing-4)"), so 496 correctly-styled
 * cells were recorded as NOT-OBSERVED. The evidence that corrected it:
 * `data-node-id` lands on a wrapper <span> for LIBRARY components, carrying only
 * sizing, while padding/radius/shadow/background are applied to the inner
 * element. Structural nodes (Container, Stack) carry everything on one <div>.
 * Both are correct; only the probe was wrong.
 */
const STYLE_PROBES: Array<{
  key: string; value: string; emitted: string; note: string;
  onEl: (el: HTMLElement) => boolean;
}> = [
  { key: "padding", value: "spacing.4", emitted: "var(--token-spacing-4)",
    note: "style.padding", onEl: (el) => el.style.padding === "var(--token-spacing-4)" },
  { key: "radius", value: "radius.md", emitted: "var(--token-radius-md)",
    note: "style.borderRadius", onEl: (el) => el.style.borderRadius === "var(--token-radius-md)" },
  { key: "shadow", value: "shadow.md", emitted: "var(--token-shadow-md)",
    note: "style.boxShadow", onEl: (el) => el.style.boxShadow === "var(--token-shadow-md)" },
  { key: "background", value: "color.surface.1", emitted: "var(--token-color-surface-1)",
    note: "style.background", onEl: (el) => el.style.background.includes("var(--token-color-surface-1)") },
  { key: "width", value: "321px", emitted: "321px", note: "style.width RAW",
    onEl: (el) => el.style.width === "321px" },
  { key: "height", value: "123px", emitted: "123px", note: "style.height RAW",
    onEl: (el) => el.style.height === "123px" },
  { key: "minWidth", value: "77px", emitted: "77px", note: "style.minWidth RAW",
    onEl: (el) => el.style.minWidth === "77px" },
  { key: "maxWidth", value: "888px", emitted: "888px", note: "style.maxWidth RAW",
    onEl: (el) => el.style.maxWidth === "888px" },
  { key: "minHeight", value: "55px", emitted: "55px", note: "style.minHeight RAW",
    onEl: (el) => el.style.minHeight === "55px" },
  { key: "maxHeight", value: "999px", emitted: "999px", note: "style.maxHeight RAW",
    onEl: (el) => el.style.maxHeight === "999px" },
  { key: "motion", value: "fade", emitted: 'data-motion="fade"', note: "data-motion attribute",
    onEl: (el) => el.getAttribute("data-motion") === "fade" },
];

/** A value that differs from the descriptor's default, chosen by declared type. */
function probeValue(d: any, salt: string): { value: unknown; kind: string } | null {
  switch (d.type) {
    case "string":  return { value: `ZQX${salt}ZQX`, kind: "string" };
    case "number":  return { value: (typeof d.default === "number" ? d.default : 0) + 7, kind: "number" };
    case "boolean": return { value: !(d.default === true), kind: "boolean" };
    case "enum": {
      const opts = (d.options ?? []) as string[];
      if (!opts.length) return null;
      const alt = opts.find((o) => o !== d.default) ?? opts[0];
      return { value: alt, kind: "enum" };
    }
    case "binding": return { value: `{{probe_${salt}}}`, kind: "binding" };
    case "action":  return { value: { type: "navigate", to: `/probe-${salt}` }, kind: "action" };
    default:        return null;
  }
}

type Cell = Record<string, unknown>;
const ledger: Cell[] = [];

function makePage(children: any[] = []) {
  return {
    schemaVersion: "2", id: "home", route: "/",
    root: { id: "root", type: "Container", props: {}, children },
  };
}
function seed(page: any) {
  useEditorStore.setState({ lastError: null } as any);
  useEditorStore.getState().setInitial({
    pageSchemas: { home: page }, navFlow: NAV_FLOW as any, tokens: EMPTY_TOKENS,
  } as any);
}
const home = () => (useEditorStore.getState().artifacts as any).pageSchemas.home;
const lastError = () => (useEditorStore.getState() as any).lastError ?? null;
const findNode = (id: string) =>
  (home().root.children ?? []).find((c: any) => c?.id === id) ?? null;

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function render() {
  await act(async () => {
    root.render(
      <EngineProvider designSpec={{}} navFlow={NAV_FLOW as any} cssVarTokens={{}}>
        <Engine schema={home()} previewData={{}} />
      </EngineProvider>,
    );
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

describe("TIER 1 — full editor matrix", () => {
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("drives every component through every prop and every style key", async () => {
    const names = Object.keys(starterRegistry);

    for (const name of names) {
      const entry = (starterRegistry as any)[name];

      // ---- PRECONDITION: the component must be insertable at all -----------
      if (!validateDrop("Container", name).ok) {
        ledger.push({ component: name, cell: "insert", status: "HARNESS-BLOCKED",
                      detail: `validateDrop refused into Container: ${validateDrop("Container", name).reason ?? "?"}` });
        continue;
      }

      // ================= PROPS =============================================
      const propEntries = Object.entries(entry.props ?? {});
      if (!propEntries.length) {
        ledger.push({ component: name, cell: "props", status: "NA",
                      detail: "registry declares no props (Menubar is the only such entry)" });
      }

      for (const [propName, d] of propEntries as Array<[string, any]>) {
        seed(makePage([]));
        const node = buildDroppedNode(name);
        useEditorStore.getState().dispatch({
          type: "insertNode", pageId: "home", parentId: "root", index: 0, node,
        } as any);
        if (!findNode(node.id)) {
          ledger.push({ component: name, prop: propName, cell: "prop", status: "HARNESS-BLOCKED",
                        detail: `insertNode did not commit: ${lastError() ?? "no lastError"}` });
          continue;
        }

        const probe = probeValue(d, "aa");
        if (!probe) {
          ledger.push({ component: name, prop: propName, cell: "prop", status: "SKIPPED",
                        detail: `no probe value for declared type "${d.type}"`, control: d.control });
          continue;
        }

        await render();
        const before = container.querySelector(`[data-node-id="${node.id}"]`)?.outerHTML ?? "";

        useEditorStore.setState({ lastError: null } as any);
        useEditorStore.getState().dispatch({
          type: "updateProp", pageId: "home", nodeId: node.id, propName, value: probe.value,
        } as any);

        const rejected = lastError();
        const committed = findNode(node.id)?.props?.[propName];
        const landed = JSON.stringify(committed) === JSON.stringify(probe.value);

        await render();
        const after = container.querySelector(`[data-node-id="${node.id}"]`)?.outerHTML ?? "";
        const domChanged = after !== before;
        const visible = probe.kind === "string" && after.includes(String(probe.value));

        // ---- NEGATIVE CONTROL: rewriting the SAME value must change nothing
        const beforeNoop = after;
        useEditorStore.getState().dispatch({
          type: "updateProp", pageId: "home", nodeId: node.id, propName, value: probe.value,
        } as any);
        await render();
        const afterNoop = container.querySelector(`[data-node-id="${node.id}"]`)?.outerHTML ?? "";
        const noopClean = afterNoop === beforeNoop;

        ledger.push({
          component: name, prop: propName, cell: "prop",
          control: d.control, type: d.type, group: d.group,
          status: rejected ? "REJECTED" : landed ? "WRITE-OK" : "WRITE-LOST",
          rejected: rejected ?? null,
          landed, domChanged, visible, noopClean,
        });
      }

      // ================= STYLE =============================================
      // One node, all 11 keys applied, then a single render — the observables
      // are independent, so this is exhaustive without 11 render cycles.
      seed(makePage([]));
      const sNode = buildDroppedNode(name);
      useEditorStore.getState().dispatch({
        type: "insertNode", pageId: "home", parentId: "root", index: 0, node: sNode,
      } as any);
      if (!findNode(sNode.id)) {
        ledger.push({ component: name, cell: "style", status: "HARNESS-BLOCKED",
                      detail: `insertNode did not commit: ${lastError() ?? "no lastError"}` });
        continue;
      }

      for (const p of STYLE_PROBES) {
        useEditorStore.getState().dispatch({
          type: "updateStyle", pageId: "home", nodeId: sNode.id, styleKey: p.key, value: p.value,
        } as any);
      }
      const styleObj = findNode(sNode.id)?.style ?? {};
      await render();
      const el = container.querySelector(`[data-node-id="${sNode.id}"]`) as HTMLElement | null;

      for (const p of STYLE_PROBES) {
        const inArtifact = (styleObj as any)[p.key] === p.value;
        if (!el) {
          ledger.push({ component: name, cell: "style", styleKey: p.key, status: "HARNESS-BLOCKED",
                        detail: "node not in DOM after render", inArtifact });
          continue;
        }
        const applied = p.onEl(el);
        // Library components put data-node-id on a wrapper that carries only
        // sizing; the token-wrapped keys land on the inner element. Search the
        // EMITTED form, never the token ref — that mistake cost 496 false cells.
        const deep = !applied && el.outerHTML.includes(p.emitted);
        ledger.push({
          component: name, cell: "style", styleKey: p.key, expected: p.note,
          status: inArtifact ? (applied ? "APPLIED" : deep ? "APPLIED-DESCENDANT" : "NOT-OBSERVED")
                             : "WRITE-LOST",
          inArtifact,
        });
      }

      // ---- clearing a style key must DELETE it (documented behaviour) ------
      useEditorStore.getState().dispatch({
        type: "updateStyle", pageId: "home", nodeId: sNode.id, styleKey: "width", value: "",
      } as any);
      const cleared = (findNode(sNode.id)?.style ?? {}) as any;
      ledger.push({
        component: name, cell: "style-clear", styleKey: "width",
        status: cleared.width === undefined ? "CLEARED-OK" : "CLEAR-FAILED",
        detail: "updateStyle('') deletes the key — apply.ts:152-158",
      });

      // ================= BINDINGS ==========================================
      const bindable = (propEntries as Array<[string, any]>)[0];
      if (bindable) {
        const [bp] = bindable;
        useEditorStore.setState({ lastError: null } as any);
        useEditorStore.getState().dispatch({
          type: "bindProp", pageId: "home", nodeId: sNode.id, propName: bp, binding: "user.name",
        } as any);
        const bound = findNode(sNode.id)?.props?.[bp];
        const isBound = typeof bound === "object"
          ? (bound as any)?.$binding === "user.name"
          : String(bound).includes("user.name");
        useEditorStore.getState().dispatch({
          type: "unbindProp", pageId: "home", nodeId: sNode.id, propName: bp,
          literalValue: (bindable[1] as any).default ?? "",
        } as any);
        const unbound = findNode(sNode.id)?.props?.[bp];
        ledger.push({
          component: name, cell: "binding", prop: bp,
          status: isBound ? (JSON.stringify(unbound) !== JSON.stringify(bound) ? "ROUNDTRIP-OK" : "UNBIND-FAILED")
                          : "BIND-FAILED",
          bound: JSON.stringify(bound)?.slice(0, 80),
          unbound: JSON.stringify(unbound)?.slice(0, 80),
        });
      }
    }

    // ---- write the ledger -------------------------------------------------
    const outDir = path.resolve(process.cwd(), "..", "tests", "matrix");
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, "tier1-ledger.json"),
                     JSON.stringify(ledger, null, 1), "utf-8");

    const tally = (pred: (c: Cell) => boolean) => ledger.filter(pred).length;
    const byStatus: Record<string, number> = {};
    for (const c of ledger) byStatus[String(c.status)] = (byStatus[String(c.status)] ?? 0) + 1;

    console.log(`[TIER1] components=${Object.keys(starterRegistry).length} cells=${ledger.length}`);
    console.log(`[TIER1] status ${JSON.stringify(byStatus)}`);
    console.log(`[TIER1] prop cells=${tally((c) => c.cell === "prop")} ` +
                `style cells=${tally((c) => c.cell === "style")} ` +
                `binding cells=${tally((c) => c.cell === "binding")}`);
    const noopDirty = ledger.filter((c) => c.cell === "prop" && c.noopClean === false);
    console.log(`[TIER1] NEGATIVE-CONTROL failures (probe unsound): ${noopDirty.length}`);

    expect(ledger.length).toBeGreaterThan(0);
  }, 1_800_000);
});
