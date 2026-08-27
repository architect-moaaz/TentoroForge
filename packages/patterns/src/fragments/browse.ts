/**
 * Browse pattern fragments — generate IR for list/browse views.
 */

import type { IRNode, ColumnDef } from "@tentoroforge/ir";
import type { EntitySpec, FieldSpec, PatternConfig } from "../types.js";
import { inferColumnRender, toLabel, pluralize, slugify } from "../field-analysis.js";

// ---------------------------------------------------------------------------
// Simple Table
// ---------------------------------------------------------------------------

export function simpleTableRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const plural = pluralize(entity.name);
  const slug = slugify(plural);

  return {
    node: "Stack",
    gap: "lg",
    padding: "lg",
    children: [
      headerRow(entity, config),
      dataTable(entity, config, slug),
    ],
  };
}

// ---------------------------------------------------------------------------
// Dense Table
// ---------------------------------------------------------------------------

export function denseTableRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const plural = pluralize(entity.name);
  const slug = slugify(plural);

  return {
    node: "Stack",
    gap: "lg",
    padding: "lg",
    children: [
      headerRow(entity, config),
      {
        node: "DataTable",
        data: `source:${slug}`,
        columns: buildColumns(entity, true),
        pagination: { pageSize: 25 },
        sorting: true,
        filtering: true,
        selection: entity.capabilities.includes("bulk-actions") ? "multiple" as const : "none" as const,
        density: "compact" as const,
        onRowClick: { type: "navigate" as const, to: `/${slug}/{{row.id}}` },
        emptyState: emptyState(entity),
      } as IRNode,
    ],
  };
}

// ---------------------------------------------------------------------------
// Sidebar-Detail
// ---------------------------------------------------------------------------

export function sidebarDetailRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const plural = pluralize(entity.name);
  const slug = slugify(plural);

  return {
    node: "Row",
    height: "screen",
    children: [
      // Sidebar
      {
        node: "Stack",
        width: "320px",
        gap: "xs",
        padding: { top: "md" as const },
        scroll: true,
        children: [
          {
            node: "Stack",
            padding: { x: "md" as const },
            gap: "sm",
            children: [
              { node: "Text", content: plural, typography: "heading-2" as const } as IRNode,
              ...(config.hasSearch ? [searchInput(slug)] : []),
              ...(config.statusField ? [statusFilter(config.statusField)] : []),
            ],
          } as IRNode,
          { node: "Divider" } as IRNode,
          compactList(entity, config, slug),
        ],
      } as IRNode,
      { node: "Divider", direction: "vertical" as const } as IRNode,
      // Detail panel
      {
        node: "Stack",
        flex: 1,
        padding: "lg",
        scroll: true,
        children: [
          {
            node: "Slot",
            switch: "state:selectedId",
            cases: {
              null: {
                node: "EmptyState",
                icon: "mouse-pointer-click",
                message: `Select a ${entity.name.toLowerCase()} from the sidebar`,
              } as IRNode,
              default: detailPanel(entity, config, slug),
            },
          } as IRNode,
        ],
      } as IRNode,
    ],
  };
}

// ---------------------------------------------------------------------------
// Card Grid
// ---------------------------------------------------------------------------

export function cardGridRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const plural = pluralize(entity.name);
  const slug = slugify(plural);

  return {
    node: "Stack",
    gap: "lg",
    padding: "lg",
    children: [
      headerRow(entity, config),
      {
        node: "Repeater",
        data: `source:${slug}.items`,
        itemKey: "id",
        direction: "grid" as const,
        columns: { default: 1, sm: 2, lg: 3 },
        gap: "md",
        emptyState: emptyState(entity),
        template: cardTemplate(entity, config, slug),
      } as IRNode,
    ],
  };
}

// ---------------------------------------------------------------------------
// Shared fragments
// ---------------------------------------------------------------------------

function headerRow(entity: EntitySpec, config: PatternConfig): IRNode {
  const plural = pluralize(entity.name);
  const children: IRNode[] = [
    { node: "Text", content: plural, typography: "heading-2" as const } as IRNode,
  ];

  const rightChildren: IRNode[] = [];
  if (config.hasSearch) {
    rightChildren.push(searchInput(slugify(plural)));
  }
  if (entity.capabilities.includes("create")) {
    rightChildren.push({
      node: "Button",
      label: `New ${entity.name}`,
      icon: "plus",
      variant: "primary",
      action: { type: "navigate" as const, to: `/${slugify(plural)}/new` },
    } as IRNode);
  }

  return {
    node: "Row",
    justify: "between",
    align: "center",
    children: [
      ...children,
      ...(rightChildren.length > 0
        ? [{ node: "Row", gap: "sm", children: rightChildren } as IRNode]
        : []),
    ],
  };
}

function searchInput(slug: string): IRNode {
  return {
    node: "TextInput",
    bind: "state:search",
    placeholder: "Search...",
    icon: "search",
    debounce: 300,
  } as IRNode;
}

function statusFilter(statusField: FieldSpec): IRNode {
  const options = [
    { value: "all", label: "All" },
    ...(statusField.values || []).map((v) => ({ value: v, label: toLabel(v) })),
  ];
  return {
    node: "Select",
    bind: "state:statusFilter",
    options,
    size: "sm",
  } as IRNode;
}

function dataTable(entity: EntitySpec, config: PatternConfig, slug: string): IRNode {
  return {
    node: "DataTable",
    data: `source:${slug}`,
    columns: buildColumns(entity, false),
    pagination: true,
    sorting: true,
    onRowClick: { type: "navigate" as const, to: `/${slug}/{{row.id}}` },
    emptyState: emptyState(entity),
  } as IRNode;
}

function buildColumns(entity: EntitySpec, dense: boolean): ColumnDef[] {
  const displayable = entity.fields.filter(
    (f) => f.name !== "id" && !["richtext", "json", "text", "file"].includes(f.type),
  );
  const fields = dense ? displayable : displayable.slice(0, 6);

  return fields.map((f) => {
    const col: ColumnDef = {
      field: f.name,
      header: f.label || toLabel(f.name),
      sortable: f.sortable !== false,
    };
    const render = inferColumnRender(f);
    if (render) col.render = render;

    // Width hints
    if (f === entity.fields.find((x) => x.type === "string" && x.name !== "id")) {
      col.width = "2fr";
    } else if (f.type === "enum" || f.type === "boolean") {
      col.width = "120px";
    } else if (f.type === "date" || f.type === "datetime") {
      col.width = "120px";
    }

    return col;
  });
}

function compactList(entity: EntitySpec, config: PatternConfig, slug: string): IRNode {
  const titleField = config.titleField;
  const statusField = config.statusField;
  const dateField = config.dateField;

  const cardChildren: IRNode[] = [];

  if (titleField) {
    cardChildren.push({
      node: "Text",
      content: `{{item.${titleField.name}}}`,
      weight: "medium",
      truncate: 1,
    } as IRNode);
  }

  const metaRow: IRNode[] = [];
  if (statusField) {
    metaRow.push({
      node: "Badge",
      content: `{{item.${statusField.name}}}`,
      size: "sm",
    } as IRNode);
  }
  if (dateField) {
    metaRow.push({
      node: "Text",
      content: `{{item.${dateField.name} | relativeDate}}`,
      typography: "caption" as const,
    } as IRNode);
  }
  if (metaRow.length > 0) {
    cardChildren.push({
      node: "Row",
      gap: "sm",
      align: "center",
      children: metaRow,
    } as IRNode);
  }

  return {
    node: "Repeater",
    data: `source:${slug}.items`,
    itemKey: "id",
    gap: "xs",
    emptyState: emptyState(entity),
    template: {
      node: "Card",
      padding: "sm",
      hoverable: true,
      action: { type: "setState" as const, path: "selectedId", value: "{{item.id}}" },
      children: cardChildren,
    } as IRNode,
  } as IRNode;
}

function detailPanel(entity: EntitySpec, config: PatternConfig, slug: string): IRNode {
  const detailSource = `${slugify(entity.name)}Detail`;
  const fields = entity.fields.filter(
    (f) => f.name !== "id" && f.name !== "createdAt" && f.name !== "updatedAt",
  );

  const fieldPairs: IRNode[] = [];
  for (const field of fields) {
    if (field.type === "richtext" || field.type === "text") continue; // shown separately
    fieldPairs.push({
      node: "Stack",
      gap: "xs",
      children: [
        { node: "Text", content: field.label || toLabel(field.name), typography: "caption" as const } as IRNode,
        field.type === "enum"
          ? { node: "Badge", content: `{{source:${detailSource}.${field.name}}}` } as IRNode
          : { node: "Text", content: `{{source:${detailSource}.${field.name}}}` } as IRNode,
      ],
    } as IRNode);
  }

  // Long text fields at bottom
  const longFields = fields.filter((f) => f.type === "richtext" || f.type === "text");
  const longFieldNodes: IRNode[] = longFields.map((f) => ({
    node: "Stack",
    gap: "xs",
    children: [
      { node: "Text", content: f.label || toLabel(f.name), typography: "caption" as const } as IRNode,
      { node: "Text", content: `{{source:${detailSource}.${f.name}}}` } as IRNode,
    ],
  } as IRNode));

  return {
    node: "AsyncSlot",
    data: `source:${detailSource}`,
    params: { id: "state:selectedId" },
    loading: { node: "Skeleton", variant: "text" as const, lines: 8 } as IRNode,
    children: [
      {
        node: "Stack",
        gap: "lg",
        children: [
          // Title + key status
          {
            node: "Row",
            justify: "between",
            align: "center",
            children: [
              config.titleField
                ? { node: "Text", content: `{{source:${detailSource}.${config.titleField.name}}}`, typography: "heading-2" as const } as IRNode
                : { node: "Text", content: entity.name, typography: "heading-2" as const } as IRNode,
            ],
          } as IRNode,
          // Field grid
          {
            node: "Grid",
            columns: 2,
            gap: "md",
            children: fieldPairs,
          } as IRNode,
          // Long text fields
          ...(longFieldNodes.length > 0
            ? [{ node: "Divider" } as IRNode, ...longFieldNodes]
            : []),
        ],
      } as IRNode,
    ],
  } as IRNode;
}

function cardTemplate(entity: EntitySpec, config: PatternConfig, slug: string): IRNode {
  const children: IRNode[] = [];

  if (config.imageField) {
    children.push({
      node: "Image",
      src: `{{item.${config.imageField.name}}}`,
      alt: `{{item.${config.titleField?.name || "name"}}}`,
      aspect: "video" as const,
      fit: "cover" as const,
      radius: "md" as const,
    } as IRNode);
  }

  if (config.titleField) {
    children.push({
      node: "Text",
      content: `{{item.${config.titleField.name}}}`,
      weight: "medium" as const,
      truncate: 1,
    } as IRNode);
  }

  const metaRow: IRNode[] = [];
  if (config.statusField) {
    metaRow.push({
      node: "Badge",
      content: `{{item.${config.statusField.name}}}`,
      size: "sm",
    } as IRNode);
  }
  if (config.dateField) {
    metaRow.push({
      node: "Text",
      content: `{{item.${config.dateField.name} | relativeDate}}`,
      typography: "caption" as const,
    } as IRNode);
  }
  if (metaRow.length > 0) {
    children.push({ node: "Row", gap: "sm", align: "center", children: metaRow } as IRNode);
  }

  return {
    node: "Card",
    hoverable: true,
    action: { type: "navigate" as const, to: `/${slug}/{{item.id}}` },
    children,
  } as IRNode;
}

function emptyState(entity: EntitySpec): IRNode {
  return {
    node: "EmptyState",
    icon: "inbox",
    title: `No ${pluralize(entity.name).toLowerCase()} found`,
    message: entity.capabilities.includes("create")
      ? `Create your first ${entity.name.toLowerCase()} to get started.`
      : `No ${pluralize(entity.name).toLowerCase()} match your filters.`,
  } as IRNode;
}
