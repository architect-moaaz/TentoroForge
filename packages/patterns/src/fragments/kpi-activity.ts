/**
 * KPI + Activity dashboard — welcome screen with personal stats and recent activity.
 */

import type { IRNode } from "@tentoroforge/ir";
import type { EntitySpec } from "../types.js";
import { pluralize, slugify, findStatusField } from "../field-analysis.js";

export function kpiActivityRoot(entities: EntitySpec[], appName: string): IRNode {
  // KPI cards — personalized stats
  const kpiCards: IRNode[] = [];

  for (const entity of entities.slice(0, 2)) {
    const slug = slugify(pluralize(entity.name));
    const statusField = findStatusField(entity);

    kpiCards.push({
      node: "Card",
      padding: "md",
      hoverable: true,
      action: { type: "navigate" as const, to: `/${slug}` },
      children: [
        { node: "Text", content: `{{source:my${entity.name}Stats.count}} ${pluralize(entity.name).toLowerCase()}`, typography: "heading-3" as const } as IRNode,
        { node: "Text", content: statusField ? `{{source:my${entity.name}Stats.pending}} pending` : "assigned to you", typography: "body-sm" as const } as IRNode,
        { node: "Text", content: "View →", typography: "caption" as const, color: "primary" } as IRNode,
      ],
    } as IRNode);
  }

  // Activity feed
  const activityItems: IRNode = {
    node: "Repeater",
    data: "source:recentActivity.items",
    itemKey: "id",
    gap: "sm",
    emptyState: {
      node: "EmptyState",
      icon: "activity",
      message: "No recent activity",
    } as IRNode,
    template: {
      node: "Row",
      gap: "sm",
      align: "center",
      padding: { y: "xs" as const },
      children: [
        { node: "Avatar", name: "{{item.actor}}", size: "sm" } as IRNode,
        {
          node: "Stack",
          gap: "xs",
          flex: 1,
          children: [
            { node: "Text", content: "{{item.description}}", typography: "body" as const } as IRNode,
            { node: "Text", content: "{{item.timestamp | relativeDate}}", typography: "caption" as const } as IRNode,
          ],
        } as IRNode,
      ],
    } as IRNode,
  } as IRNode;

  // Quick actions
  const quickActions: IRNode[] = entities.slice(0, 3).map((entity) => ({
    node: "Button",
    label: `New ${entity.name}`,
    icon: "plus",
    variant: "outline",
    action: { type: "navigate" as const, to: `/${slugify(pluralize(entity.name))}/new` },
  } as IRNode));

  return {
    node: "Stack",
    gap: "xl",
    padding: "lg",
    children: [
      // Welcome header
      {
        node: "Stack",
        gap: "xs",
        children: [
          { node: "Text", content: `Welcome back`, typography: "heading-1" as const } as IRNode,
          { node: "Text", content: `Here's what's happening in ${appName}`, typography: "body-sm" as const } as IRNode,
        ],
      } as IRNode,
      // KPI cards
      {
        node: "Grid",
        columns: { default: 1, sm: 2 },
        gap: "md",
        children: kpiCards,
      } as IRNode,
      // Activity + Quick Actions
      {
        node: "Grid",
        columns: { default: 1, lg: 2 },
        gap: "lg",
        children: [
          {
            node: "Card",
            padding: "md",
            children: [
              { node: "Text", content: "Recent Activity", typography: "heading-3" as const } as IRNode,
              { node: "Spacer", size: "sm" } as IRNode,
              activityItems,
            ],
          } as IRNode,
          {
            node: "Stack",
            gap: "md",
            children: [
              { node: "Text", content: "Quick Actions", typography: "heading-3" as const } as IRNode,
              ...quickActions,
            ],
          } as IRNode,
        ],
      } as IRNode,
    ],
  };
}
