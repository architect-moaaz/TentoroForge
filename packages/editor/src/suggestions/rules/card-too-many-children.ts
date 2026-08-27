import type { Rule } from "../types";

const MAX_CARD_CHILDREN = 6;

export const cardTooManyChildren: Rule = {
  id: "card-too-many-children",
  check(node) {
    if (node.type !== "Card") return [];
    const count = Array.isArray(node.children) ? node.children.length : 0;
    if (count <= MAX_CARD_CHILDREN) return [];
    return [
      {
        id: `card-too-many-children:${node.id}`,
        source: "rule" as const,
        ruleId: "card-too-many-children",
        nodeId: node.id,
        severity: "info" as const,
        title: "Card has too many direct children",
        description: `Card "${node.id}" has ${count} direct children (max recommended: ${MAX_CARD_CHILDREN}). Consider wrapping some children in a Stack.`,
      },
    ];
  },
};
