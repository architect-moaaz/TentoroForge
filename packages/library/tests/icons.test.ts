import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { ICON_NAMES, resolveIcon, looksLikeIconName } from "../src/icons";

/**
 * docs/editor-audit/input-components-2.md finding #5 — "a real icon picker".
 *
 * Two defects met here: ICON_MAP was module-private (so no picker UI could
 * enumerate the valid names, and `iconPicker` degraded to a free-text field),
 * and `resolveIcon` only lowercased its argument, so the catalog's PascalCase
 * `"ChevronDown"` became "chevrondown" and matched nothing.
 */
describe("resolveIcon accepts both in-tree naming conventions", () => {
  it("resolves the canonical kebab key", () => {
    expect(resolveIcon("plus")).toBeTruthy();
    expect(resolveIcon("chevron-down")).toBeTruthy();
  });

  it("resolves the catalog's PascalCase spelling of the same icon", () => {
    // This is the case that used to return null: entry.icon = "ChevronDown".
    expect(resolveIcon("ChevronDown")).toBe(resolveIcon("chevron-down"));
    expect(resolveIcon("Plus")).toBe(resolveIcon("plus"));
    expect(resolveIcon("MousePointer")).toBe(resolveIcon("mouse-pointer"));
  });

  it("tolerates camelCase, snake_case and stray spacing too", () => {
    const expected = resolveIcon("chevron-down");
    expect(resolveIcon("chevronDown")).toBe(expected);
    expect(resolveIcon("chevron_down")).toBe(expected);
    expect(resolveIcon("Chevron Down")).toBe(expected);
  });

  it("still returns null for a name we do not have", () => {
    expect(resolveIcon("definitely-not-an-icon")).toBeNull();
    expect(resolveIcon("")).toBeNull();
    expect(resolveIcon(undefined)).toBeNull();
  });
});

describe("ICON_NAMES — the list the editor's icon picker enumerates", () => {
  it("is a non-empty, sorted, kebab-lowercase list", () => {
    expect(ICON_NAMES.length).toBeGreaterThan(100);
    expect([...ICON_NAMES]).toEqual([...ICON_NAMES].sort());
    for (const name of ICON_NAMES) expect(name).toMatch(/^[a-z0-9-]+$/);
  });

  it("every listed name resolves — the picker can never offer a dead option", () => {
    for (const name of ICON_NAMES) expect(resolveIcon(name), name).toBeTruthy();
  });

  it("includes the icons the palette defaults reach for", () => {
    expect(ICON_NAMES).toContain("plus");
    expect(ICON_NAMES).toContain("chevron-down");
    expect(ICON_NAMES).toContain("mouse-pointer");
  });
});

describe("looksLikeIconName separates a broken name from a deliberate glyph", () => {
  it("treats identifiers as names", () => {
    expect(looksLikeIconName("Plus")).toBe(true);
    expect(looksLikeIconName("chevron-down")).toBe(true);
  });
  it("treats typed glyphs as glyphs", () => {
    // IconButton renders these verbatim; they are not failed lookups.
    expect(looksLikeIconName("✕")).toBe(false);
    expect(looksLikeIconName("🗑")).toBe(false);
    expect(looksLikeIconName("→")).toBe(false);
  });
});

/**
 * Drift guard. Every `icon:` in the component catalog names a Lucide glyph the
 * palette, layer tree and icon picker want to draw; if it does not resolve the
 * author gets a hole. Reads the COMPILED catalog the same way
 * registry-parity.test.ts does, and skips when it has not been built.
 */
describe("every catalog entry.icon resolves", () => {
  const starterPath = resolve(__dirname, "../../registry/dist/starter.json");
  it("resolves each icon named in packages/registry/dist/starter.json", () => {
    if (!existsSync(starterPath)) {
      // `npm run build` in packages/registry has not run in this checkout.
      expect(true).toBe(true);
      return;
    }
    const catalog = JSON.parse(readFileSync(starterPath, "utf8")) as Record<string, any>;
    const entries: any[] = Array.isArray(catalog)
      ? catalog
      : Object.values(catalog.components ?? catalog);
    const unresolved = entries
      .map((e) => (e && typeof e === "object" ? e.icon : undefined))
      .filter((i): i is string => typeof i === "string" && i.length > 0)
      .filter((i) => resolveIcon(i) === null);
    expect(unresolved).toEqual([]);
  });
});

/**
 * The other half of the same drift. The file header has always claimed
 * ICON_MAP is "kept in sync with backend/services/shell_templates.py:_ICONS",
 * and nothing enforced it — which is how `"stethoscope"` (doctor / physician /
 * provider nav items) ended up emitted by the shell generator with no row
 * here, so those nav items rendered with no glyph at all.
 */
describe("every icon the shell generator emits resolves", () => {
  const shellPath = resolve(__dirname, "../../../backend/services/shell_templates.py");
  it("resolves each value in _ICONS and _FALLBACK_ICONS", () => {
    if (!existsSync(shellPath)) return; // frontend-only checkout
    const py = readFileSync(shellPath, "utf8");
    const list = (marker: string) => {
      const start = py.indexOf(marker);
      if (start < 0) return "";
      return py.slice(start, py.indexOf("]", start));
    };
    const emitted = new Set<string>();
    for (const m of list("_ICONS = [").matchAll(/\(\s*"[^"]+"\s*,\s*"([^"]+)"\s*\)/g)) {
      emitted.add(m[1]!);
    }
    for (const m of list("_FALLBACK_ICONS = [").matchAll(/"([a-z0-9-]+)"/g)) {
      emitted.add(m[1]!);
    }
    expect(emitted.size).toBeGreaterThan(10); // the parse actually found rows
    expect([...emitted].filter((i) => resolveIcon(i) === null)).toEqual([]);
  });
});
