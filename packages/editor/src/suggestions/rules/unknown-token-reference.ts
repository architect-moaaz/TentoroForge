import type { Rule } from "../types";

/**
 * Walks node.style and flags any value of the form { $token: "group.name" }
 * where the referenced token does not exist in ctx.theme[group][name].
 */
export const unknownTokenReference: Rule = {
  id: "unknown-token-reference",
  check(node, ctx) {
    if (!ctx.theme) return [];
    const style = node.style;
    if (!style || typeof style !== "object") return [];

    const out: ReturnType<Rule["check"]> = [];

    for (const [styleKey, val] of Object.entries(style)) {
      if (val && typeof val === "object" && "$token" in (val as object)) {
        const ref = (val as { $token: string }).$token;
        const dotIdx = ref.indexOf(".");
        if (dotIdx === -1) continue; // malformed ref — skip
        const group = ref.slice(0, dotIdx);
        const name = ref.slice(dotIdx + 1);
        const groupTokens = ctx.theme[group];
        if (!groupTokens || !(name in groupTokens)) {
          out.push({
            id: `unknown-token-reference:${node.id}:${styleKey}`,
            source: "rule" as const,
            ruleId: "unknown-token-reference",
            nodeId: node.id,
            severity: "warn" as const,
            title: "Unknown token reference",
            description: `Style key "${styleKey}" on "${node.id}" references token "${ref}" which does not exist in the active theme.`,
          });
        }
      }
    }

    return out;
  },
};
