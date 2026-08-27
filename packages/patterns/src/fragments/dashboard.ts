/**
 * Dashboard pattern fragments — generate IR for overview/dashboard pages.
 */

import type { IRNode } from "@tentoroforge/ir";
import type { EntitySpec, PatternConfig } from "../types.js";
import { findStatusField, pluralize, slugify, toLabel } from "../field-analysis.js";

// ---------------------------------------------------------------------------
// Stat + Table Dashboard
// ---------------------------------------------------------------------------

export function statTableDashboardRoot(entities: EntitySpec[]): IRNode {
  // Generate stat cards for each entity
  const statCards: IRNode[] = entities.map((entity) => {
    const slug = slugify(pluralize(entity.name));
    return {
      node: "StatCard",
      label: `Total ${pluralize(entity.name)}`,
      value: `source:${slug}Stats.total`,
      format: "number",
      icon: "hash",
      action: { type: "navigate" as const, to: `/${slug}` },
    } as IRNode;
  });

  // Status breakdown for entities with status fields
  const statusCards: IRNode[] = [];
  for (const entity of entities) {
    const statusField = findStatusField(entity);
    if (statusField && statusField.values) {
      for (const value of statusField.values.slice(0, 3)) {
        const slug = slugify(pluralize(entity.name));
        statusCards.push({
          node: "StatCard",
          label: `${toLabel(value)} ${pluralize(entity.name)}`,
          value: `source:${slug}Stats.${value}Count`,
          format: "number",
        } as IRNode);
      }
    }
  }

  const allStats = [...statCards, ...statusCards].slice(0, 4);

  // Recent items tables
  const recentTables: IRNode[] = entities.slice(0, 2).map((entity) => {
    const slug = slugify(pluralize(entity.name));
    const fields = entity.fields.filter(
      (f) => f.name !== "id" && !["richtext", "json", "text", "file"].includes(f.type),
    ).slice(0, 3);

    return {
      node: "Card",
      padding: "md",
      children: [
        {
          node: "Row",
          justify: "between",
          align: "center",
          children: [
            { node: "Text", content: `Recent ${pluralize(entity.name)}`, typography: "heading-3" as const } as IRNode,
            { node: "Text", content: "View all →", typography: "body-sm" as const, color: "primary" } as IRNode,
          ],
        } as IRNode,
        { node: "Spacer", size: "sm" } as IRNode,
        {
          node: "DataTable",
          data: `source:recent${pluralize(entity.name)}`,
          columns: fields.map((f) => ({
            field: f.name,
            header: f.label || toLabel(f.name),
            ...(f.type === "enum" ? { render: "badge" } : {}),
            ...(f.type === "date" || f.type === "datetime" ? { render: "date:relative" } : {}),
          })),
          onRowClick: { type: "navigate" as const, to: `/${slug}/{{row.id}}` },
          emptyState: {
            node: "EmptyState",
            icon: "inbox",
            message: `No recent ${pluralize(entity.name).toLowerCase()}`,
          } as IRNode,
        } as IRNode,
      ],
    } as IRNode;
  });

  return {
    node: "Stack",
    gap: "xl",
    padding: "lg",
    children: [
      { node: "Text", content: "Dashboard", typography: "heading-1" as const } as IRNode,
      {
        node: "Grid",
        columns: { default: 1, sm: 2, lg: allStats.length > 3 ? 4 : allStats.length },
        gap: "md",
        children: allStats,
      } as IRNode,
      ...(recentTables.length > 1
        ? [{
            node: "Grid",
            columns: { default: 1, lg: 2 },
            gap: "lg",
            children: recentTables,
          } as IRNode]
        : recentTables),
    ],
  };
}
