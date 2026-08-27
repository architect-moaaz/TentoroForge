import { defaultTokens } from "@tentoroforge/library";

// Converts defaultTokens (canonical namespace) into the nested objects
// Tailwind expects. The new token shape is already nested, so most groups
// pass through directly.
//
// Cast to `any` here so this file stays independent of the built dist's
// stale declaration and always reads the live defaultTokens shape at runtime.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const tokens = defaultTokens as any;

// Collapse single-key objects whose only key is "default" to a flat string.
// e.g. { border: { default: "#e4e4e7" } } → { border: "#e4e4e7" }
function collapseDefaults(
  group: Record<string, string | Record<string, string>>,
): Record<string, string | Record<string, string>> {
  const out: Record<string, string | Record<string, string>> = {};
  for (const [k, v] of Object.entries(group)) {
    if (typeof v === "object" && Object.keys(v).length === 1 && "default" in v) {
      out[k] = (v as Record<string, string>).default;
    } else {
      out[k] = v;
    }
  }
  return out;
}

// Strip the semantic sub-object from spacing so Tailwind only sees the
// numeric scale values (e.g. "4" → "1rem").
function spacingScale(
  spacing: Record<string, string | Record<string, string>>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(spacing)) {
    if (typeof v === "string") out[k] = v;
  }
  return out;
}

export const tailwindTokens: {
  colors: Record<string, string | Record<string, string>>;
  spacing: Record<string, string>;
  fontSize: Record<string, string>;
  borderRadius: Record<string, string>;
  boxShadow: Record<string, string>;
} = {
  colors: collapseDefaults(tokens.color),
  spacing: spacingScale(tokens.spacing),
  fontSize: tokens.typography.scale,
  borderRadius: tokens.radius,
  boxShadow: tokens.shadow,
};
