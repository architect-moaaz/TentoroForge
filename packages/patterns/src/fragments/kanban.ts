/**
 * Kanban board pattern — status-based column layout with cards.
 */

import type { IRNode } from "@tentoroforge/ir";
import type { EntitySpec, PatternConfig } from "../types.js";
import { toLabel, pluralize, slugify } from "../field-analysis.js";

export function kanbanRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const plural = pluralize(entity.name);
  const slug = slugify(plural);
  const statusField = config.statusField;

  if (!statusField?.values) {
    // Fallback: no status field, render simple table
    return {
      node: "Stack", gap: "lg", padding: "lg",
      children: [
        { node: "Text", content: `${plural} Board`, typography: "heading-2" as const } as IRNode,
        { node: "Text", content: "Kanban requires a status field with enum values.", typography: "body-sm" as const } as IRNode,
      ],
    };
  }

  const columns: IRNode[] = statusField.values.map((status) => ({
    node: "Stack",
    gap: "sm",
    flex: 1,
    children: [
      // Column header
      {
        node: "Row",
        gap: "sm",
        align: "center",
        padding: { x: "sm" as const },
        children: [
          { node: "Text", content: toLabel(status), typography: "body" as const, weight: "semibold" as const } as IRNode,
          { node: "Badge", content: `{{source:${slug}Counts.${status} || 0}}`, size: "sm", variant: "outline" } as IRNode,
        ],
      } as IRNode,
      // Column body: filtered repeater
      {
        node: "Repeater",
        data: `source:${slug}By${capitalize(status)}`,
        itemKey: "id",
        gap: "xs",
        emptyState: {
          node: "EmptyState",
          message: `No ${status.replace(/_/g, " ")} items`,
        } as IRNode,
        template: kanbanCard(entity, config, slug),
      } as IRNode,
    ],
  } as IRNode));

  return {
    node: "Stack",
    gap: "lg",
    padding: "lg",
    children: [
      // Header
      {
        node: "Row",
        justify: "between",
        align: "center",
        children: [
          { node: "Text", content: `${plural} Board`, typography: "heading-2" as const } as IRNode,
          ...(config.hasSearch ? [{
            node: "TextInput",
            bind: "state:search",
            placeholder: "Search...",
            icon: "search",
            debounce: 300,
          } as IRNode] : []),
          ...(entity.capabilities.includes("create") ? [{
            node: "Button",
            label: `New ${entity.name}`,
            icon: "plus",
            variant: "primary",
          } as IRNode] : []),
        ],
      } as IRNode,
      // Board columns
      {
        node: "Row",
        gap: "md",
        scroll: true,
        children: columns,
      } as IRNode,
    ],
  };
}

function kanbanCard(entity: EntitySpec, config: PatternConfig, slug: string): IRNode {
  const children: IRNode[] = [];

  if (config.titleField) {
    children.push({
      node: "Text",
      content: `{{item.${config.titleField.name}}}`,
      weight: "medium" as const,
      truncate: 2,
    } as IRNode);
  }

  const metaChildren: IRNode[] = [];
  if (config.dateField) {
    metaChildren.push({
      node: "Text",
      content: `{{item.${config.dateField.name} | relativeDate}}`,
      typography: "caption" as const,
    } as IRNode);
  }
  // Show assignee avatar if entity has a relation field
  const assigneeField = entity.fields.find((f) => f.type === "relation" && f.name.toLowerCase().includes("assign"));
  if (assigneeField) {
    metaChildren.push({
      node: "Avatar",
      name: `{{item.${assigneeField.name}}}`,
      size: "xs",
    } as IRNode);
  }

  if (metaChildren.length > 0) {
    children.push({
      node: "Row",
      justify: "between",
      align: "center",
      children: metaChildren,
    } as IRNode);
  }

  return {
    node: "Card",
    padding: "sm",
    hoverable: true,
    action: { type: "navigate" as const, to: `/${slug}/{{item.id}}` },
    children,
  } as IRNode;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
