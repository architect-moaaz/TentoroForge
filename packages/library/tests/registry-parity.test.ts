import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { buildDefaultRegistry } from "../src/buildDefaultRegistry";

/**
 * Drift guard: keeps the three component lists in sync so the AI generation
 * pipeline can actually emit AND render every component we ship.
 *
 * The three lists that must agree:
 *   1. `starterRegistry` (source, packages/registry/src/starter.ts)  →
 *      compiled to `dist/starter.json` by `npm run build` in the registry pkg.
 *      This JSON is what `backend/services/schema_prompt.py` reads to tell the
 *      LLM "Available components:" — i.e. the generator's vocabulary.
 *   2. `buildDefaultRegistry()` (this package) — the runtime registry the
 *      renderer/preview uses to dispatch a node type to a React component.
 *
 * Failure mode this prevents (the Waves 1–6 regression): a component listed in
 * starter.json (so the AI is told it can use it) but NOT registered at runtime
 * renders as a "⚠ <Type>" placeholder. Conversely, registering at runtime
 * without exporting to starter.json means the AI never emits it.
 *
 * The backend reads the COMPILED artifact, so this test compares against
 * `dist/starter.json` directly. If it's missing, run `npm run build` in
 * packages/registry.
 */

// starter.json names that are intentionally NOT in the library runtime registry:
//  - structural / layout primitives dispatched by the renderer CORE
//    (packages/renderer dispatch), never by the library registry.
//  - TableSortable: a catalog-only entry with no schema node in the
//    discriminated union, so the AI cannot emit a valid node for it (pre-existing
//    half-wire, tracked separately).
const CORE_DISPATCHED_ALLOWLIST = new Set([
  "Container",
  "Stack",
  "Row",
  "Grid",
  "Spacer",
  "Slot",
  "Repeat",
  "Conditional",
  "DataBoundary",
  "TableSortable",
]);

// Every component added across Waves 1–6. Each MUST be runtime-registered.
const WAVE_COMPONENTS = [
  // Wave 1
  "Switch", "NumberInput", "RadioGroup", "Slider", "FileUpload", "Combobox",
  // Wave 2
  "DropdownMenu", "Popover", "Tooltip", "Drawer", "ContextMenu", "HoverCard", "Menubar",
  // Wave 3
  "Progress", "Spinner", "Banner", "TimePicker", "ColorPicker", "InputOTP", "Rating", "MaskedInput",
  // Wave 4
  "Tag", "Stat", "DescriptionList", "List", "SegmentedControl", "Tree", "Transfer", "Cascader",
  // Wave 5
  "Calendar", "Kanban", "RichTextEditor", "Carousel", "Lightbox", "CodeBlock", "QRCode",
  // Wave 6
  "CameraCapture", "Scanner", "ValidationChecklist",
] as const;

// Commerce runtime-primitive components (CART slice).
const COMMERCE_COMPONENTS = ["AddToCart", "CartBadge", "CartPanel", "CartPage"] as const;

function runtimeNames(): Set<string> {
  return new Set(buildDefaultRegistry().list().map((e) => e.name));
}

function starterJsonNames(): string[] {
  // vitest runs with cwd at the library package root; the registry artifact is a
  // sibling package. Try a few candidates so the test is robust to the runner.
  const candidates = [
    resolve(process.cwd(), "../registry/dist/starter.json"),
    resolve(process.cwd(), "packages/registry/dist/starter.json"),
    resolve(process.cwd(), "../../packages/registry/dist/starter.json"),
  ];
  const path = candidates.find((p) => existsSync(p));
  if (!path) {
    throw new Error(
      `dist/starter.json not found (looked in: ${candidates.join(", ")}). ` +
        `Run \`npm run build\` in packages/registry to regenerate the LLM component vocabulary.`,
    );
  }
  return Object.keys(JSON.parse(readFileSync(path, "utf8")));
}

describe("registry parity (generation drift guard)", () => {
  it("every AI-visible component (starter.json) is runtime-registered or core-dispatched", () => {
    const runtime = runtimeNames();
    const missing = starterJsonNames().filter(
      (name) => !runtime.has(name) && !CORE_DISPATCHED_ALLOWLIST.has(name),
    );
    expect(
      missing,
      `These components are in starter.json (so the AI will try to emit them) ` +
        `but are NOT registered in buildDefaultRegistry — they would render as ` +
        `"⚠ <Type>". Register them in buildDefaultRegistry.tsx (or add to the ` +
        `core-dispatched allowlist if structural): ${missing.join(", ")}`,
    ).toEqual([]);
  });

  it("all 39 Wave 1–6 components are registered at runtime", () => {
    const runtime = runtimeNames();
    const missing = WAVE_COMPONENTS.filter((name) => !runtime.has(name));
    expect(missing, `Wave components missing from runtime registry: ${missing.join(", ")}`).toEqual([]);
  });

  it("all 39 Wave 1–6 components are present in the LLM vocabulary (starter.json)", () => {
    const vocab = new Set(starterJsonNames());
    const missing = WAVE_COMPONENTS.filter((name) => !vocab.has(name));
    expect(
      missing,
      `Wave components missing from starter.json (rebuild packages/registry): ${missing.join(", ")}`,
    ).toEqual([]);
  });

  it("all commerce cart components are registered at runtime AND in starter.json", () => {
    const runtime = runtimeNames();
    const vocab = new Set(starterJsonNames());
    const missingRuntime = COMMERCE_COMPONENTS.filter((n) => !runtime.has(n));
    const missingVocab = COMMERCE_COMPONENTS.filter((n) => !vocab.has(n));
    expect(missingRuntime, `Commerce components missing from runtime registry: ${missingRuntime.join(", ")}`).toEqual([]);
    expect(missingVocab, `Commerce components missing from starter.json (rebuild packages/registry): ${missingVocab.join(", ")}`).toEqual([]);
  });

  it("registers a meaningful number of components at runtime (sanity)", () => {
    expect(runtimeNames().size).toBeGreaterThanOrEqual(90);
  });
});
