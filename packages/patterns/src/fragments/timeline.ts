/**
 * Timeline pattern — chronological feed of events/activities.
 */

import type { IRNode } from "@tentoroforge/ir";
import type { EntitySpec, PatternConfig } from "../types.js";
import { pluralize, slugify, toLabel } from "../field-analysis.js";

export function timelineRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const plural = pluralize(entity.name);
  const slug = slugify(plural);

  const titleField = config.titleField || entity.fields.find((f) => f.type === "string");
  const dateField = config.dateField || entity.fields.find((f) => f.type === "datetime" || f.type === "date");

  const templateChildren: IRNode[] = [];

  // Timestamp
  if (dateField) {
    templateChildren.push({
      node: "Text",
      content: `{{item.${dateField.name} | relativeDate}}`,
      typography: "caption" as const,
      color: "muted",
    } as IRNode);
  }

  // Title/action
  if (titleField) {
    templateChildren.push({
      node: "Text",
      content: `{{item.${titleField.name}}}`,
      weight: "medium" as const,
    } as IRNode);
  }

  // Secondary fields
  const secondaryFields = entity.fields.filter(
    (f) => f !== titleField && f !== dateField && f.name !== "id" &&
    f.name !== "createdAt" && f.name !== "updatedAt" &&
    !["json", "file", "image"].includes(f.type),
  ).slice(0, 2);

  for (const field of secondaryFields) {
    templateChildren.push({
      node: "Text",
      content: `{{item.${field.name}}}`,
      typography: "body-sm" as const,
    } as IRNode);
  }

  return {
    node: "Stack",
    gap: "lg",
    padding: "lg",
    children: [
      {
        node: "Row",
        justify: "between",
        align: "center",
        children: [
          { node: "Text", content: plural, typography: "heading-2" as const } as IRNode,
          ...(config.hasFilters ? [{
            node: "Select",
            bind: "state:dateFilter",
            options: [
              { value: "all", label: "All time" },
              { value: "today", label: "Today" },
              { value: "week", label: "This week" },
              { value: "month", label: "This month" },
            ],
            size: "sm",
          } as IRNode] : []),
        ],
      } as IRNode,
      {
        node: "Repeater",
        data: `source:${slug}.items`,
        itemKey: "id",
        gap: "xs",
        emptyState: {
          node: "EmptyState",
          icon: "clock",
          message: `No ${plural.toLowerCase()} yet`,
        } as IRNode,
        template: {
          node: "Row",
          gap: "md",
          padding: { y: "sm" as const },
          children: [
            // Timeline dot
            {
              node: "Stack",
              align: "center",
              children: [
                { node: "Icon", name: "circle", size: "xs", color: "primary" } as IRNode,
              ],
            } as IRNode,
            // Content
            {
              node: "Stack",
              gap: "xs",
              flex: 1,
              children: templateChildren,
            } as IRNode,
          ],
        } as IRNode,
      } as IRNode,
    ],
  };
}
