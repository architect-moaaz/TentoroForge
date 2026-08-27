import type { Rule } from "../types";

export const repeatNeedsKeypath: Rule = {
  id: "repeat-needs-keypath",
  check(node) {
    if (node.type !== "Repeat") return [];
    if (node.props?.keyPath) return [];
    return [
      {
        id: `repeat-needs-keypath:${node.id}`,
        source: "rule" as const,
        ruleId: "repeat-needs-keypath",
        nodeId: node.id,
        severity: "info" as const,
        title: "Repeat missing keyPath",
        description: `Repeat "${node.id}" has no keyPath prop. Set keyPath to a unique field (e.g. "id") for stable list rendering.`,
      },
    ];
  },
};
