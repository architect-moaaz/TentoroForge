import type { CSSProperties } from "react";
import type { StyleProps } from "@tentoroforge/schema";

export type Theme = Record<string, Record<string, string> | string>;

export function tokenToCssVar(ref: string): string {
  return `--token-${ref.replace(/\./g, "-")}`;
}

/**
 * Recursively walks a token tree and emits CSS custom properties.
 *
 * Handles three shapes:
 * 1. Top-level scalar string  → `--token-<key>: <value>`
 * 2. Flat map { "dotted.path": value } → `--token-dotted-path: value` (legacy)
 * 3. Nested object (Wave 2 new groups) → recurse, emitting `--token-<group>-<leaf>: value`
 *
 * All three are interoperable with `tokenToCssVar(ref)` for consumer lookups.
 */
function walkTokens(
  node: unknown,
  prefix: string,
  out: Record<string, string>,
): void {
  if (typeof node === "string" || typeof node === "number" || typeof node === "boolean") {
    // Leaf value — emit the CSS var. Convert to string for CSS compatibility.
    out[prefix] = String(node);
    return;
  }
  if (node && typeof node === "object" && !Array.isArray(node)) {
    for (const [key, value] of Object.entries(node)) {
      // Dotted keys (legacy flat-map pattern) are converted to dashes by tokenToCssVar.
      // Nested keys build on the prefix with a "-" separator.
      const segment = key.replace(/\./g, "-");
      walkTokens(value, `${prefix}-${segment}`, out);
    }
  }
}

export function compileTokens(theme: Theme): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [group, value] of Object.entries(theme)) {
    if (typeof value === "string") {
      // Top-level scalar (density, elevation, motionLevel, etc.)
      out[`--token-${group}`] = value;
    } else if (value && typeof value === "object") {
      // Group object — walk its entries.
      // Use walkTokens starting from `--token-<group>` for nested objects,
      // but for the flat-map legacy pattern the inner keys already contain dots.
      for (const [name, leaf] of Object.entries(value)) {
        // name may be "primary.500" (flat legacy) or "sm" / "display" (nested)
        const segment = name.replace(/\./g, "-");
        // LEGACY name (group dropped): --token-primary-500 / --token-sm.
        // Kept for existing consumers, but note radius.sm and shadow.sm
        // collide on --token-sm under this scheme.
        walkTokens(leaf, `--token-${segment}`, out);
        // CANONICAL name (group KEPT): --token-color-primary-500 /
        // --token-spacing-4 / --token-radius-sm. This is what every actual
        // consumer references (style-slot tokenVar, library resolveStyle) —
        // those refs resolved to NOTHING before, so all schema-level styling
        // (node.style token refs) was silently dead in generated apps.
        walkTokens(leaf, `--token-${group}-${segment}`, out);
      }
    }
  }
  return out;
}

const STYLE_KEY_TO_CSS: Record<string, string> = {
  color: "color",
  background: "backgroundColor",
  padding: "padding",
  paddingX: "paddingInline",
  paddingY: "paddingBlock",
  margin: "margin",
  marginX: "marginInline",
  marginY: "marginBlock",
  fontSize: "fontSize",
  fontWeight: "fontWeight",
  lineHeight: "lineHeight",
  letterSpacing: "letterSpacing",
  borderRadius: "borderRadius",
  borderColor: "borderColor",
  borderWidth: "borderWidth",
  shadow: "boxShadow",
  width: "width",
  height: "height",
  gap: "gap",
};

export function resolveStyle(style?: StyleProps): CSSProperties {
  const out: Record<string, string> = {};
  if (!style) return out;
  for (const [k, v] of Object.entries(style)) {
    if (typeof v !== "string") continue;
    const cssKey = STYLE_KEY_TO_CSS[k];
    if (!cssKey) continue;
    out[cssKey] = `var(${tokenToCssVar(v)})`;
  }
  return out as CSSProperties;
}
