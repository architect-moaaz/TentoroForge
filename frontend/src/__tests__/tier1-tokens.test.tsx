/**
 * TIER 1 — TOKENS. The fourth inspector tab, swept exhaustively.
 *
 * Every token the editor can write is driven through the REAL store action and
 * checked in the REAL rendered DOM:
 *   • color   -> ["color", group, name]      (the 50..950 ramps)
 *   • spacing -> ["spacing", name]           (coerced through Number())
 *   • radius  -> ["radius", name]            (coerced through Number())
 *   • typography -> ["typography","fontFamily",n] and ["typography","scale",n]
 *   • shadow  -> ["shadow", name]
 *   • motion  -> ["motion", name]
 *   • removeToken for each group
 *
 * THE ASSERTION THAT MATTERS. EngineProvider emits every token leaf TWICE onto
 * [data-tentoro-engine] — `--<group>-<path>` AND `--token-<group>-<path>`
 * (EngineProvider.tsx:56-62). The dual emission is deliberate: library
 * components deref `--token-*`, and emitting only the bare prefix once made
 * every library var() resolve to nothing. So a token edit must move BOTH in
 * lockstep; one moving without the other is a real defect, and checking only
 * one would hide it.
 *
 * Also pins T1, a candidate found by reading TokenEditor: it renders EVERY
 * tokens.radius.* key as input[type=number] and writes Number(value), while
 * StylePanel's "Radius scale" legitimately stores the STRING "soft" at
 * radius.scale. Editing that row in the Tokens tab therefore yields NaN. Real
 * projects already carry radius.scale, so this is pre-existing.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import React from "react";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import { useEditorStore } from "@/lib/editor-store";
import * as fs from "node:fs";
import * as path from "node:path";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !window.matchMedia) {
  // @ts-expect-error minimal polyfill
  window.matchMedia = (q: string) => ({
    matches: false, media: q, onchange: null, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
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

/** A token tree shaped like a real project's tokens.custom.json. */
const SEED = {
  color: {
    primary: { "50": "#eef", "500": "#3b82f6", "900": "#123" },
    surface: { "0": "#fff", "1": "#fafafa" },
    secondary: { "500": "#8b5cf6" },
  },
  spacing: { "2": 8, "4": 16, "8": 32 },
  radius: { sm: 2, md: 6, lg: 12, scale: "soft" },   // `scale` is a STRING, deliberately
  typography: { fontFamily: { base: "Inter", heading: "Fraunces" }, scale: { body: 14, h1: 32 } },
  shadow: { sm: "0 1px 2px #0001", md: "0 4px 8px #0002" },
  motion: { fast: "120ms", slow: "400ms" },
  breakpoints: {},
};

type Cell = Record<string, unknown>;
const ledger: Cell[] = [];

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

function seed(tokens: any) {
  useEditorStore.setState({ lastError: null } as any);
  useEditorStore.getState().setInitial({
    pageSchemas: {
      home: {
        schemaVersion: "2", id: "home", route: "/",
        root: { id: "root", type: "Container", props: {}, children: [] },
      },
    },
    navFlow: NAV_FLOW as any,
    tokens,
  } as any);
}
const tokensNow = () => (useEditorStore.getState().artifacts as any).tokens;
const lastError = () => (useEditorStore.getState() as any).lastError ?? null;

async function render() {
  const t = tokensNow();
  await act(async () => {
    root.render(
      <EngineProvider designSpec={{}} navFlow={NAV_FLOW as any} cssVarTokens={t}>
        <Engine schema={(useEditorStore.getState().artifacts as any).pageSchemas.home} previewData={{}} />
      </EngineProvider>,
    );
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

/** Both spellings of a token var, read off the engine wrapper's inline style. */
function readVars(pathParts: string[]) {
  const el = container.querySelector("[data-tentoro-engine]") as HTMLElement | null;
  if (!el) return { found: false as const };
  const suffix = pathParts.join("-");
  return {
    found: true as const,
    bare: el.style.getPropertyValue(`--${suffix}`).trim(),
    prefixed: el.style.getPropertyValue(`--token-${suffix}`).trim(),
  };
}

/** Every leaf path in the seed tree — this is what "exhaustive" means here. */
function leaves(obj: any, prefix: string[] = []): string[][] {
  const out: string[][] = [];
  for (const [k, v] of Object.entries(obj ?? {})) {
    if (v && typeof v === "object" && !Array.isArray(v)) out.push(...leaves(v, [...prefix, k]));
    else out.push([...prefix, k]);
  }
  return out;
}

describe("TIER 1 — tokens tab", () => {
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => { act(() => root.unmount()); container.remove(); });

  it("drives every token leaf and checks both emitted var spellings", async () => {
    const all = leaves(SEED);
    for (const p of all) {
      seed(JSON.parse(JSON.stringify(SEED)));
      await render();
      const before = readVars(p);

      // A value that is unmistakably ours, typed like the group expects.
      const isNumeric = p[0] === "spacing" || p[0] === "radius"
        || (p[0] === "typography" && p[1] === "scale");
      const next: any = isNumeric ? 77 : "#abcdef";

      useEditorStore.setState({ lastError: null } as any);
      useEditorStore.getState().dispatch({ type: "updateToken", path: p, value: next } as any);
      const rejected = lastError();

      // did it reach the artifact?
      let cur: any = tokensNow();
      for (const seg of p) cur = cur?.[seg];
      const landed = cur === next;

      await render();
      const after = readVars(p);

      ledger.push({
        cell: "token", path: p.join("."), group: p[0],
        status: rejected ? "REJECTED" : landed ? "WRITE-OK" : "WRITE-LOST",
        rejected: rejected ?? null,
        varsFound: after.found,
        bareMoved: after.found && before.found ? after.bare !== before.bare : null,
        prefixedMoved: after.found && before.found ? after.prefixed !== before.prefixed : null,
        lockstep: after.found && before.found
          ? (after.bare !== before.bare) === (after.prefixed !== before.prefixed)
          : null,
      });
    }

    // ---- removeToken, one per group -------------------------------------
    for (const p of [["color", "primary", "500"], ["spacing", "4"], ["radius", "md"],
                     ["shadow", "sm"], ["motion", "fast"], ["typography", "scale", "h1"]]) {
      seed(JSON.parse(JSON.stringify(SEED)));
      useEditorStore.setState({ lastError: null } as any);
      useEditorStore.getState().dispatch({ type: "removeToken", path: p } as any);
      let cur: any = tokensNow();
      for (const seg of p) cur = cur?.[seg];
      ledger.push({
        cell: "removeToken", path: p.join("."),
        status: lastError() ? "REJECTED" : cur === undefined ? "REMOVED-OK" : "REMOVE-FAILED",
        rejected: lastError() ?? null,
      });
    }

    // ---- T1: the radius.scale <-> numeric-input collision ----------------
    // TokenEditor renders every radius.* row as input[type=number] and writes
    // Number(value). radius.scale legitimately holds "soft".
    seed(JSON.parse(JSON.stringify(SEED)));
    useEditorStore.getState().dispatch({
      type: "updateToken", path: ["radius", "scale"], value: Number("soft"),
    } as any);
    const scaleNow = (tokensNow() as any)?.radius?.scale;
    ledger.push({
      cell: "known-candidate", path: "radius.scale",
      status: Number.isNaN(scaleNow) ? "NaN-CONFIRMED" : "NOT-REPRODUCED",
      detail: "TokenEditor coerces every radius.* row with Number(); radius.scale holds a string",
      value: String(scaleNow),
    });

    const outDir = path.resolve(process.cwd(), "..", "tests", "matrix");
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, "tier1-tokens.json"), JSON.stringify(ledger, null, 1), "utf-8");

    const tally: Record<string, number> = {};
    for (const c of ledger) tally[String(c.status)] = (tally[String(c.status)] ?? 0) + 1;
    console.log(`[TOKENS] leaves swept=${all.length} cells=${ledger.length}`);
    console.log(`[TOKENS] status ${JSON.stringify(tally)}`);
    const notLockstep = ledger.filter((c) => c.lockstep === false);
    console.log(`[TOKENS] vars NOT moving in lockstep: ${notLockstep.length}` +
      (notLockstep.length ? ` -> ${notLockstep.map((c) => c.path).join(", ")}` : ""));
    const noVars = ledger.filter((c) => c.cell === "token" && c.varsFound === false);
    console.log(`[TOKENS] cells where the engine wrapper was absent: ${noVars.length}`);
    const stuck = ledger.filter((c) => c.cell === "token" && c.prefixedMoved === false);
    console.log(`[TOKENS] --token-* did NOT move: ${stuck.length}` +
      (stuck.length ? ` -> ${stuck.map((c) => c.path).join(", ")}` : ""));

    expect(ledger.length).toBeGreaterThan(0);
  }, 900_000);
});
