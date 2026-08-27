import type { Rule } from "../types";

export const iconButtonAriaLabel: Rule = {
  id: "iconbutton-aria-label",
  check(node) {
    if (node.type !== "IconButton") return [];
    if (node.props?.["aria-label"]) return [];
    return [
      {
        id: `iconbutton-aria-label:${node.id}`,
        source: "rule" as const,
        ruleId: "iconbutton-aria-label",
        nodeId: node.id,
        severity: "warn" as const,
        title: "IconButton missing aria-label",
        description: `IconButton "${node.id}" has no aria-label, which makes it inaccessible to screen readers.`,
      },
    ];
  },
};
