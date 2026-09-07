import { tokenToCssVar } from "../../runtime/tokens";
import { applyStyleSlot } from "../../runtime/style-slot";

/**
 * Spacer — a fixed, non-shrinking gap between siblings.
 *
 * `size` arrives in two dialects and only one of them used to work:
 *   - a dotted token ref ("tokens.spacing.6"), which the schema's TokenRef
 *     models and `tokenToCssVar` turns into --token-spacing-6; and
 *   - the registry's own enum (xs | sm | md | lg | xl | 2xl), which is what
 *     the properties panel writes and what a palette drop materialises.
 *
 * The bare enum was routed through the same `tokenToCssVar`, producing
 * `var(--token-md)`. compileTokens emits --token-md from BOTH the radius and
 * the shadow group (group prefix dropped for the legacy alias) and shadow wins,
 * so a dropped Spacer asked for `width: var(--token-md)` and got a box-shadow
 * string — an invalid declaration, discarded by the browser. Rendered proof
 * before this change: `<div data-node-id="B_Spacer" style="width:var(--token-md);
 * height:var(--token-md)">` measuring 1280x0. A component whose entire job is
 * to occupy space occupied none of it.
 *
 * The enum is therefore mapped to the spacing scale explicitly, with the
 * literal rem as the var() fallback so the Spacer still has its height on a
 * page whose token stylesheet has not loaded (or was overridden away).
 */
const ENUM_SIZE: Record<string, string> = {
  none: "0px",
  xs:   `var(${tokenToCssVar("spacing.1")}, 0.25rem)`,
  sm:   `var(${tokenToCssVar("spacing.2")}, 0.5rem)`,
  md:   `var(${tokenToCssVar("spacing.4")}, 1rem)`,
  lg:   `var(${tokenToCssVar("spacing.6")}, 1.5rem)`,
  xl:   `var(${tokenToCssVar("spacing.8")}, 2rem)`,
  "2xl": `var(${tokenToCssVar("spacing.12")}, 3rem)`,
};

function sizeValue(size: unknown): string {
  if (typeof size !== "string" || size === "") return ENUM_SIZE.md;
  if (ENUM_SIZE[size]) return ENUM_SIZE[size];
  // Anything with a CSS unit is a literal the schema author meant verbatim.
  if (/^-?[\d.]+(px|rem|em|%|vh|vw)$/.test(size)) return size;
  return `var(${tokenToCssVar(size)}, 1rem)`;
}

export function Spacer({ node }: { node: any }) {
  const size = sizeValue(node.props?.size);
  const slotProps = applyStyleSlot(node.style);
  return (
    <div
      data-node-id={node.id}
      style={{
        width: size,
        height: size,
        flexShrink: 0,
        ...slotProps.style,
      }}
      data-motion={slotProps["data-motion"]}
    />
  );
}
