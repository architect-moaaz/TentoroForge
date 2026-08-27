import type { Rule } from "../types";

export const textWithoutContent: Rule = {
  id: "text-without-content",
  check(node) {
    if (node.type !== "Text") return [];
    if (node.props?.content) return [];
    if (node.bind) return [];
    return [
      {
        id: `text-without-content:${node.id}`,
        source: "rule" as const,
        ruleId: "text-without-content",
        nodeId: node.id,
        severity: "warn" as const,
        title: "Text node has no content",
        description: `Text "${node.id}" has neither a content prop nor a data binding. It will render empty.`,
      },
    ];
  },
};
