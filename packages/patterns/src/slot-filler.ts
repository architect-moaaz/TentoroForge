/**
 * Slot Filler — replaces PlaceholderSlot nodes with concrete IR subtrees.
 *
 * The LLM generates page skeletons with $slot markers.
 * This module fills those markers with entity-specific IR nodes
 * using the existing fragment library.
 */

import type { IRNode, PageIR, PlaceholderSlotNode } from "@tentoroforge/ir";
import type { EntitySpec, PatternConfig, FieldSpec } from "./types.js";
import { resolvePattern } from "./resolver.js";
import { simpleTableRoot, denseTableRoot, sidebarDetailRoot, cardGridRoot } from "./fragments/browse.js";
import { kanbanRoot } from "./fragments/kanban.js";
import { timelineRoot } from "./fragments/timeline.js";
import { pageFormRoot, sectionedFormRoot } from "./fragments/forms.js";
import { simpleDetailRoot, tabbedDetailRoot, profileDetailRoot } from "./fragments/detail.js";
import { authLoginRoot, authSignupRoot } from "./fragments/shell.js";
import { slugify, pluralize, countEditableFields, toLabel } from "./field-analysis.js";

/** Build a PatternConfig from an entity (local version since resolver doesn't export it) */
function buildConfig(entity: EntitySpec): PatternConfig {
  const fields = entity.fields || [];
  const titleField = fields.find((f) => /name|title/i.test(f.name)) || fields[0];
  const statusField = fields.find((f) => f.name === "status" || f.type === "enum");
  const dateField = fields.find((f) => f.type === "date" || f.type === "datetime");
  const imageField = fields.find((f) => f.type === "image" || f.type === "avatar");
  const previewFields = fields.filter((f) => !f.name.endsWith("_id") && f.name !== "id").slice(0, 5);

  return {
    titleField,
    statusField,
    dateField,
    imageField,
    previewFields,
    hasSearch: entity.capabilities?.includes("search") ?? false,
    hasFilters: entity.capabilities?.includes("filter") ?? false,
    hasPagination: true,
  };
}

// ---------------------------------------------------------------------------
// Context for slot filling
// ---------------------------------------------------------------------------

export interface SlotFillerContext {
  appName: string;
  entities: EntitySpec[];
  entityMap: Map<string, EntitySpec>;
  configCache: Map<string, PatternConfig>;
}

export function buildSlotFillerContext(
  appName: string,
  entities: EntitySpec[],
): SlotFillerContext {
  const entityMap = new Map<string, EntitySpec>();
  const configCache = new Map<string, PatternConfig>();

  for (const entity of entities) {
    entityMap.set(entity.name, entity);
    entityMap.set(entity.name.toLowerCase(), entity);
    // Also map pluralized and slugified names
    entityMap.set(pluralize(entity.name).toLowerCase(), entity);
    entityMap.set(slugify(entity.name), entity);
    configCache.set(entity.name, buildConfig(entity));
  }

  return { appName, entities, entityMap, configCache };
}

// ---------------------------------------------------------------------------
// Main fill function
// ---------------------------------------------------------------------------

/**
 * Fill all PlaceholderSlot nodes in a page skeleton.
 * Also auto-repairs missing required props on input nodes.
 * Returns a new PageIR with all slots replaced.
 */
export function fillPageSlots(skeleton: PageIR, ctx: SlotFillerContext): PageIR {
  const filled = fillNode(skeleton.root, ctx);
  const repaired = repairMissingProps(filled, skeleton.$id || "page");
  return {
    ...skeleton,
    root: repaired,
  };
}

/**
 * Auto-repair missing required props on input nodes.
 * Adds default bind values, empty options arrays, etc.
 */
function repairMissingProps(node: IRNode, pageId: string, depth: number = 0): IRNode {
  const INPUT_NODES = new Set(["TextInput", "TextArea", "Select", "Checkbox", "Toggle", "RadioGroup", "DatePicker", "FilePicker", "Slider", "ColorPicker", "RichTextEditor"]);

  let repaired = { ...node } as Record<string, unknown> & { node: string };

  // Fix missing bind on inputs
  if (INPUT_NODES.has(node.node)) {
    if (!repaired.bind) {
      const label = (repaired.label as string) || (repaired.placeholder as string) || `field_${depth}`;
      const fieldName = label.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");
      repaired.bind = `state:form.${fieldName}`;
    }
    // Fix missing options on Select
    if (node.node === "Select" && !repaired.options) {
      repaired.options = [{ value: "option1", label: "Option 1" }, { value: "option2", label: "Option 2" }];
    }
    // Fix missing options on RadioGroup
    if (node.node === "RadioGroup" && !repaired.options) {
      repaired.options = [{ value: "a", label: "Option A" }, { value: "b", label: "Option B" }];
    }
  }

  // Fix missing label on Button
  if (node.node === "Button" && !repaired.label) {
    repaired.label = "Button";
  }

  // Recurse into children
  if ("children" in repaired && Array.isArray(repaired.children)) {
    repaired = {
      ...repaired,
      children: (repaired.children as IRNode[]).map((child, i) => repairMissingProps(child, pageId, depth * 10 + i)),
    };
  }

  return repaired as IRNode;
}

function fillNode(node: IRNode, ctx: SlotFillerContext): IRNode {
  // Check if this is a PlaceholderSlot
  if (node.node === "PlaceholderSlot") {
    const slot = node as unknown as PlaceholderSlotNode;
    const filled = fillSlot(slot, ctx);
    return filled || node; // Keep the placeholder if we can't fill it
  }

  // Recurse into children
  if ("children" in node && Array.isArray(node.children)) {
    return {
      ...node,
      children: node.children.map((child: IRNode) => fillNode(child, ctx)),
    };
  }

  // Recurse into form fields (fields are FormFieldDef, not IRNode, so skip recursion)
  // Form fields don't contain PlaceholderSlots

  // Recurse into tabs content
  if (node.node === "Tabs" && "tabs" in node && Array.isArray(node.tabs)) {
    return {
      ...node,
      tabs: (node.tabs as Array<{ id: string; label: string; content: IRNode }>).map(
        (tab) => ({ ...tab, content: fillNode(tab.content, ctx) }),
      ),
    };
  }

  // Recurse into card slots
  if (node.node === "Card") {
    const card = { ...node } as Record<string, unknown>;
    if (card.header && typeof card.header === "object" && "node" in (card.header as IRNode)) {
      card.header = fillNode(card.header as IRNode, ctx);
    }
    if (card.footer && typeof card.footer === "object" && "node" in (card.footer as IRNode)) {
      card.footer = fillNode(card.footer as IRNode, ctx);
    }
    return card as IRNode;
  }

  return node;
}

// ---------------------------------------------------------------------------
// Slot fillers — one per SlotType
// ---------------------------------------------------------------------------

function fillSlot(slot: PlaceholderSlotNode, ctx: SlotFillerContext): IRNode | null {
  const entity = slot.entity ? resolveEntity(slot.entity, ctx) : null;

  switch (slot.$slot) {
    case "entity-table":
      return fillEntityTable(entity, ctx);
    case "entity-form":
      return fillEntityForm(entity, ctx, slot.config);
    case "entity-detail":
      return fillEntityDetail(entity, ctx);
    case "auth-form":
      return fillAuthForm(ctx, slot.config);
    case "stat-cards":
      return fillStatCards(entity, ctx);
    case "crud-actions":
      return fillCrudActions(entity, ctx);
    case "detail-tabs":
      return fillDetailTabs(entity, ctx);
    case "branding":
      return fillBranding(ctx);
    case "recent-items":
      return fillRecentItems(entity, ctx);
    case "search-bar":
      return fillSearchBar(entity);
    case "status-filter":
      return fillStatusFilter(entity);
    case "empty-state":
      return fillEmptyState(entity);
    case "features-list":
      return fillFeaturesList(ctx);
    case "nav-sidebar":
    case "nav-topbar":
      return null; // Navigation is handled at the AppIR level, not per-page
    default:
      return null;
  }
}

function resolveEntity(name: string, ctx: SlotFillerContext): EntitySpec | null {
  return ctx.entityMap.get(name) || ctx.entityMap.get(name.toLowerCase()) || null;
}

// ---------------------------------------------------------------------------
// Individual slot fillers
// ---------------------------------------------------------------------------

function fillEntityTable(entity: EntitySpec | null, ctx: SlotFillerContext): IRNode {
  if (!entity) {
    return { node: "Text", content: "No entity specified for table", typography: "body-sm" as const } as IRNode;
  }
  const config = ctx.configCache.get(entity.name) || buildConfig(entity);
  // Check for view overrides
  const browsePattern = (entity as any).viewOverrides?.browse;
  if (browsePattern === "dense-table") return denseTableRoot(entity, config);
  if (browsePattern === "card-grid") return cardGridRoot(entity, config);
  if (browsePattern === "kanban") return kanbanRoot(entity, config);
  if (browsePattern === "timeline") return timelineRoot(entity, config);
  if (browsePattern === "sidebar-detail") return sidebarDetailRoot(entity, config);
  return simpleTableRoot(entity, config);
}

function fillEntityForm(
  entity: EntitySpec | null,
  ctx: SlotFillerContext,
  config?: Record<string, unknown>,
): IRNode {
  if (!entity) {
    return { node: "Text", content: "No entity specified for form", typography: "body-sm" as const } as IRNode;
  }
  const pConfig = ctx.configCache.get(entity.name) || buildConfig(entity);
  const editableCount = countEditableFields(entity);
  if (editableCount > 10) return sectionedFormRoot(entity, pConfig);
  return pageFormRoot(entity, pConfig);
}

function fillEntityDetail(entity: EntitySpec | null, ctx: SlotFillerContext): IRNode {
  if (!entity) {
    return { node: "Text", content: "No entity specified for detail", typography: "body-sm" as const } as IRNode;
  }
  const config = ctx.configCache.get(entity.name) || buildConfig(entity);
  const hasImage = entity.fields.some((f) => f.type === "image" || f.type === "avatar");
  if (hasImage) return profileDetailRoot(entity, config);
  if (entity.fields.length > 8) return tabbedDetailRoot(entity, config);
  return simpleDetailRoot(entity, config);
}

function fillAuthForm(ctx: SlotFillerContext, config?: Record<string, unknown>): IRNode {
  const variant = (config?.variant as string) || "login";
  if (variant === "signup") return authSignupRoot(ctx.appName);
  return authLoginRoot(ctx.appName);
}

function fillStatCards(entity: EntitySpec | null, ctx: SlotFillerContext): IRNode {
  const entities = entity ? [entity] : ctx.entities.slice(0, 4);
  return {
    node: "Grid",
    columns: { default: 2, lg: entities.length } as any,
    gap: "md",
    children: entities.map((e) => ({
      node: "StatCard",
      label: pluralize(toLabel(e.name)),
      value: `source:${slugify(pluralize(e.name))}.length`,
      format: "number" as const,
      icon: "list",
    } as IRNode)),
  } as IRNode;
}

function fillCrudActions(entity: EntitySpec | null, ctx: SlotFillerContext): IRNode {
  if (!entity) return { node: "Spacer", size: "xs" } as IRNode;
  const slug = slugify(pluralize(entity.name));
  return {
    node: "Row",
    justify: "between",
    align: "center",
    children: [
      { node: "Text", content: pluralize(toLabel(entity.name)), typography: "heading-2" as const } as IRNode,
      {
        node: "Button",
        label: `New ${toLabel(entity.name)}`,
        variant: "primary" as const,
        icon: "plus",
        action: { type: "navigate" as const, to: `/${slug}/new` },
      } as IRNode,
    ],
  } as IRNode;
}

function fillDetailTabs(entity: EntitySpec | null, ctx: SlotFillerContext): IRNode {
  if (!entity) return { node: "Spacer", size: "xs" } as IRNode;
  const config = ctx.configCache.get(entity.name) || buildConfig(entity);
  return tabbedDetailRoot(entity, config);
}

function fillBranding(ctx: SlotFillerContext): IRNode {
  return {
    node: "Stack",
    align: "center",
    gap: "sm",
    children: [
      { node: "Text", content: ctx.appName, typography: "heading-2" as const, color: "primary" } as IRNode,
    ],
  } as IRNode;
}

function fillRecentItems(entity: EntitySpec | null, ctx: SlotFillerContext): IRNode {
  const target = entity || ctx.entities[0];
  if (!target) return { node: "Text", content: "No data", typography: "body-sm" as const } as IRNode;
  const slug = slugify(pluralize(target.name));
  const previewFields = target.fields.filter((f) => !f.name.endsWith("_id") && f.name !== "id").slice(0, 4);
  return {
    node: "Stack",
    gap: "sm",
    children: [
      { node: "Text", content: `Recent ${pluralize(toLabel(target.name))}`, typography: "heading-3" as const } as IRNode,
      {
        node: "DataTable",
        data: `source:${slug}`,
        columns: previewFields.map((f) => ({ field: f.name, header: toLabel(f.name) })),
        pagination: { pageSize: 5 } as any,
        onRowClick: { type: "navigate" as const, to: `/${slug}/{{row.id}}` },
      } as IRNode,
    ],
  } as IRNode;
}

function fillSearchBar(entity: EntitySpec | null): IRNode {
  return {
    node: "TextInput",
    bind: "state:search",
    placeholder: `Search ${entity ? pluralize(toLabel(entity.name)).toLowerCase() : "items"}...`,
    icon: "search",
  } as IRNode;
}

function fillStatusFilter(entity: EntitySpec | null): IRNode {
  if (!entity) return { node: "Spacer", size: "xs" } as IRNode;
  const statusField = entity.fields.find((f) => f.name === "status" || f.type === "enum");
  if (!statusField || !statusField.values) {
    return { node: "Spacer", size: "xs" } as IRNode;
  }
  return {
    node: "Select",
    bind: "state:statusFilter",
    placeholder: "All statuses",
    options: statusField.values.map((v: string) => ({ value: v, label: toLabel(v) })),
    clearable: true,
  } as IRNode;
}

function fillEmptyState(entity: EntitySpec | null): IRNode {
  const name = entity ? pluralize(toLabel(entity.name)).toLowerCase() : "items";
  return {
    node: "EmptyState",
    icon: "inbox",
    title: `No ${name} yet`,
    message: `Get started by creating your first ${entity ? toLabel(entity.name).toLowerCase() : "item"}.`,
    action: entity
      ? { label: `Create ${toLabel(entity.name)}`, action: { type: "navigate" as const, to: `/${slugify(pluralize(entity.name))}/new` } }
      : undefined,
  } as IRNode;
}

function fillFeaturesList(ctx: SlotFillerContext): IRNode {
  return {
    node: "Stack",
    gap: "md",
    children: ctx.entities.slice(0, 4).map((e) => ({
      node: "Row",
      gap: "sm",
      align: "center",
      children: [
        { node: "Icon", name: "check-circle", size: "sm", color: "success" } as IRNode,
        { node: "Text", content: `${toLabel(e.name)} management`, typography: "body" as const } as IRNode,
      ],
    } as IRNode)),
  } as IRNode;
}
