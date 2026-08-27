import type { TokenGroups } from "@tentoroforge/library";

/** Parse a CSS value like "1rem", "16px", or bare number string to pixels (rem base = 16px). */
function parseToPx(value: string, remBase = 16): number {
  if (value.endsWith("rem")) return parseFloat(value) * remBase;
  if (value.endsWith("px")) return parseFloat(value);
  return parseFloat(value);
}

/**
 * Given a target pixel size and the active theme, return the name of the nearest
 * spacing token whose computed pixel value is closest to targetPx.
 * Returns null if there are no spacing tokens.
 */
export function snapToSpacingToken(targetPx: number, theme: TokenGroups): string | null {
  const spacing = (theme as any).spacing as Record<string, string> | undefined;
  if (!spacing) return null;

  let nearest: { name: string; distance: number } | null = null;
  for (const [name, value] of Object.entries(spacing)) {
    if (typeof value !== "string") continue;
    const valuePx = parseToPx(value);
    if (isNaN(valuePx)) continue;
    const distance = Math.abs(targetPx - valuePx);
    if (!nearest || distance < nearest.distance) {
      nearest = { name, distance };
    }
  }
  return nearest?.name ?? null;
}
