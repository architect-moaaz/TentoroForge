import { promises as fs } from "node:fs";
import path from "node:path";
import { defaultTokens } from "@tentoroforge/library";

function deepMerge(base: any, overlay: any): any {
  if (overlay === null || overlay === undefined) return base;
  if (typeof overlay !== "object" || Array.isArray(overlay)) return overlay;
  const out: any = { ...(base || {}) };
  for (const [k, v] of Object.entries(overlay)) out[k] = deepMerge(out[k], v);
  return out;
}

export async function loadTokens(projectRoot: string): Promise<Record<string, unknown>> {
  const customPath = path.join(projectRoot, "src", "theme", "tokens.custom.json");
  try {
    const raw = await fs.readFile(customPath, "utf8");
    const custom = JSON.parse(raw);
    return deepMerge(defaultTokens, custom);
  } catch {
    return defaultTokens as Record<string, unknown>;
  }
}
