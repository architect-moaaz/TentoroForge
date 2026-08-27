// Server-only: merges defaultTokens with src/theme/tokens.custom.json
// (if present). Used by root layout for CSS variable injection and by
// API routes (save, suggest) that need the active theme.
import "server-only";
import { defaultTokens } from "@tentoroforge/library";
import { loadCustomTokens } from "./load-custom";

const custom = loadCustomTokens();

function merge(a: any, b: any) {
  if (!b) return a;
  const out: any = {};
  for (const g of new Set([...Object.keys(a), ...Object.keys(b)])) {
    out[g] = { ...(a[g] ?? {}), ...(b[g] ?? {}) };
  }
  return out;
}

export const tokens = merge(defaultTokens, custom);
