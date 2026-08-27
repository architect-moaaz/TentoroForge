/**
 * Detail pattern fragments — generate IR for detail/view pages.
 */

import type { IRNode } from "@tentoroforge/ir";
import type { EntitySpec, PatternConfig } from "../types.js";
import { toLabel, slugify, pluralize } from "../field-analysis.js";

// ---------------------------------------------------------------------------
// Simple Detail
// ---------------------------------------------------------------------------

export function simpleDetailRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const slug = slugify(entity.name);
  const source = `${slug}Detail`;

  const shortFields = entity.fields.filter(
    (f) => f.name !== "id" && !["richtext", "text", "json"].includes(f.type) &&
    f.name !== "createdAt" && f.name !== "updatedAt",
  );
  const longFields = entity.fields.filter(
    (f) => f.type === "richtext" || f.type === "text",
  );

  const fieldGrid: IRNode[] = shortFields.map((f) => ({
    node: "Stack",
    gap: "xs",
    children: [
      { node: "Text", content: f.label || toLabel(f.name), typography: "caption" as const } as IRNode,
      f.type === "enum"
        ? { node: "Badge", content: `{{source:${source}.${f.name}}}` } as IRNode
        : f.type === "boolean"
          ? { node: "Badge", content: `{{source:${source}.${f.name}}}`, variant: "outline" } as IRNode
          : { node: "Text", content: `{{source:${source}.${f.name}}}` } as IRNode,
    ],
  } as IRNode));

  return {
    node: "Stack",
    gap: "lg",
    padding: "lg",
    children: [
      // Back + title
      {
        node: "Row",
        justify: "between",
        align: "center",
        children: [
          {
            node: "Row",
            gap: "sm",
            align: "center",
            children: [
              {
                node: "Button",
                label: "Back",
                variant: "ghost",
                icon: "arrow-left",
                action: { type: "navigate" as const, to: `/${slugify(pluralize(entity.name))}` },
              } as IRNode,
              config.titleField
                ? { node: "Text", content: `{{source:${source}.${config.titleField.name}}}`, typography: "heading-2" as const } as IRNode
                : { node: "Text", content: entity.name, typography: "heading-2" as const } as IRNode,
            ],
          } as IRNode,
          {
            node: "Row",
            gap: "sm",
            children: [
              ...(entity.capabilities.includes("edit") ? [{
                node: "Button",
                label: "Edit",
                variant: "outline",
                icon: "pencil",
                action: { type: "navigate" as const, to: `/${slugify(pluralize(entity.name))}/{{params.id}}/edit` },
              } as IRNode] : []),
              ...(entity.capabilities.includes("delete") ? [{
                node: "Button",
                label: "Delete",
                variant: "danger",
                icon: "trash-2",
                action: { type: "mutate" as const, source: `delete${entity.name}`, confirm: `Delete this ${entity.name.toLowerCase()}?` },
              } as IRNode] : []),
            ],
          } as IRNode,
        ],
      } as IRNode,
      // Field grid
      {
        node: "Grid",
        columns: { default: 1, md: 2 },
        gap: "md",
        children: fieldGrid,
      } as IRNode,
      // Long text fields
      ...(longFields.length > 0
        ? [
            { node: "Divider" } as IRNode,
            ...longFields.map((f) => ({
              node: "Stack",
              gap: "xs",
              children: [
                { node: "Text", content: f.label || toLabel(f.name), typography: "caption" as const } as IRNode,
                { node: "Text", content: `{{source:${source}.${f.name}}}` } as IRNode,
              ],
            } as IRNode)),
          ]
        : []),
    ],
  };
}

// ---------------------------------------------------------------------------
// Tabbed Detail
// ---------------------------------------------------------------------------

export function tabbedDetailRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const slug = slugify(entity.name);
  const source = `${slug}Detail`;

  const tabs: any[] = [];

  // Details tab
  const detailFields = entity.fields.filter(
    (f) => f.name !== "id" && f.name !== "createdAt" && f.name !== "updatedAt",
  );
  const fieldNodes: IRNode[] = detailFields.map((f) => ({
    node: "Stack",
    gap: "xs",
    children: [
      { node: "Text", content: f.label || toLabel(f.name), typography: "caption" as const } as IRNode,
      f.type === "enum"
        ? { node: "Badge", content: `{{source:${source}.${f.name}}}` } as IRNode
        : { node: "Text", content: `{{source:${source}.${f.name}}}` } as IRNode,
    ],
  } as IRNode));

  tabs.push({
    id: "details",
    label: "Details",
    content: {
      node: "Grid",
      columns: { default: 1, md: 2 },
      gap: "md",
      children: fieldNodes,
    } as IRNode,
  });

  // Activity tab (if capable)
  if (entity.capabilities.includes("activity-log") || entity.capabilities.includes("comments")) {
    tabs.push({
      id: "activity",
      label: "Activity",
      content: {
        node: "EmptyState",
        icon: "message-square",
        message: "Activity log coming soon",
      } as IRNode,
    });
  }

  // Related tab (if has relations)
  if (entity.relations && entity.relations.length > 0) {
    tabs.push({
      id: "related",
      label: "Related",
      content: {
        node: "EmptyState",
        icon: "link",
        message: "Related items coming soon",
      } as IRNode,
    });
  }

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
          {
            node: "Row",
            gap: "sm",
            align: "center",
            children: [
              {
                node: "Button",
                label: "Back",
                variant: "ghost",
                icon: "arrow-left",
                action: { type: "navigate" as const, to: `/${slugify(pluralize(entity.name))}` },
              } as IRNode,
              config.titleField
                ? { node: "Text", content: `{{source:${source}.${config.titleField.name}}}`, typography: "heading-2" as const } as IRNode
                : { node: "Text", content: entity.name, typography: "heading-2" as const } as IRNode,
              ...(config.statusField ? [{
                node: "Badge",
                content: `{{source:${source}.${config.statusField.name}}}`,
              } as IRNode] : []),
            ],
          } as IRNode,
          {
            node: "Row",
            gap: "sm",
            children: [
              ...(entity.capabilities.includes("edit") ? [{
                node: "Button", label: "Edit", variant: "outline", icon: "pencil",
              } as IRNode] : []),
            ],
          } as IRNode,
        ],
      } as IRNode,
      // Tabs
      {
        node: "Tabs",
        defaultTab: "details",
        tabs,
      } as IRNode,
    ],
  };
}

// ---------------------------------------------------------------------------
// Profile Detail
// ---------------------------------------------------------------------------

export function profileDetailRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const slug = slugify(entity.name);
  const source = `${slug}Detail`;

  const nonIdentityFields = entity.fields.filter(
    (f) => f.name !== "id" && !f.isIdentityImage &&
    f.type !== "avatar" && f.type !== "image" &&
    f.name !== "createdAt" && f.name !== "updatedAt",
  );

  return {
    node: "Stack",
    gap: "lg",
    padding: "lg",
    children: [
      {
        node: "Button",
        label: "Back",
        variant: "ghost",
        icon: "arrow-left",
        action: { type: "navigate" as const, to: `/${slugify(pluralize(entity.name))}` },
      } as IRNode,
      // Hero header
      {
        node: "Row",
        gap: "lg",
        align: "center",
        children: [
          config.imageField
            ? { node: "Avatar", src: `{{source:${source}.${config.imageField.name}}}`, name: `{{source:${source}.${config.titleField?.name || "name"}}}`, size: "xl" } as IRNode
            : { node: "Avatar", name: `{{source:${source}.${config.titleField?.name || "name"}}}`, size: "xl" } as IRNode,
          {
            node: "Stack",
            gap: "xs",
            children: [
              config.titleField
                ? { node: "Text", content: `{{source:${source}.${config.titleField.name}}}`, typography: "heading-1" as const } as IRNode
                : { node: "Text", content: "Profile", typography: "heading-1" as const } as IRNode,
              { node: "Text", content: `{{source:${source}.email}}`, typography: "body-sm" as const } as IRNode,
            ],
          } as IRNode,
        ],
      } as IRNode,
      { node: "Divider" } as IRNode,
      // Field grid
      {
        node: "Grid",
        columns: { default: 1, md: 2, lg: 3 },
        gap: "md",
        children: nonIdentityFields.map((f) => ({
          node: "Stack",
          gap: "xs",
          children: [
            { node: "Text", content: f.label || toLabel(f.name), typography: "caption" as const } as IRNode,
            { node: "Text", content: `{{source:${source}.${f.name}}}` } as IRNode,
          ],
        } as IRNode)),
      } as IRNode,
    ],
  };
}
