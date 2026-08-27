import type { Registry } from "./types";

/**
 * Compact, token-budget-friendly summary of a registry. Fed to the LLM
 * as part of the writeArtifacts tool's system prompt. Example output:
 *
 *   Button (leaf)  { label:string, variant:primary|secondary|ghost, ... }
 *   Container […children]  { direction:vertical|horizontal, ... }
 *   ...
 */
export function registryDigest(registry: Registry): string {
  return Object.values(registry).map(e => {
    const slots = e.slots.type === "list" ? "[…children]"
                : e.slots.type === "single" ? "[child]"
                : "(leaf)";
    const props = Object.entries(e.props).map(([n, d]) =>
      d.type === "enum" ? `${n}:${(d.options || []).join("|")}` : `${n}:${d.type}`
    ).join(", ");
    return `${e.name} ${slots}  { ${props} }`;
  }).join("\n");
}
