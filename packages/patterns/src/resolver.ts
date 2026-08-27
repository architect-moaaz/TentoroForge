/**
 * Design Resolver — maps entity specs + view intents to pattern selections.
 *
 * Pure deterministic logic. No LLM involved.
 */

import type {
  EntitySpec, ViewIntent, PatternName, PatternSelection, PatternConfig,
} from "./types.js";
import {
  countDisplayableFields, countEditableFields,
  findTitleField, findStatusField, findDateField, findImageField,
  hasImageField, hasRichTextField, isPersonEntity, isTemporalEntity,
  rankFieldsForListPreview, groupFieldsByAffinity,
} from "./field-analysis.js";

// ---------------------------------------------------------------------------
// Main resolver
// ---------------------------------------------------------------------------

/**
 * Given an entity and a view intent, select the best pattern and configuration.
 */
export function resolvePattern(
  entity: EntitySpec,
  intent: ViewIntent,
): PatternSelection {
  const pattern = selectPattern(entity, intent);
  const config = buildConfig(entity, pattern, intent);

  return { pattern, entity, intent, config };
}

// ---------------------------------------------------------------------------
// Pattern selection by intent
// ---------------------------------------------------------------------------

function selectPattern(entity: EntitySpec, intent: ViewIntent): PatternName {
  switch (intent) {
    case "browse-and-act":
      return selectBrowsePattern(entity);
    case "create":
      return selectCreatePattern(entity);
    case "edit":
      return selectCreatePattern(entity); // same heuristics
    case "detail":
      return selectDetailPattern(entity);
    case "dashboard":
      return "stat-table-dashboard";
    case "settings":
      return "settings-sidebar";
    case "kanban":
      return "kanban";
    default:
      return "simple-table";
  }
}

function selectBrowsePattern(entity: EntitySpec): PatternName {
  const displayable = countDisplayableFields(entity);
  const statusField = findStatusField(entity);

  // Kanban if explicitly requested via capabilities
  if (entity.capabilities.includes("kanban") && statusField) {
    if (statusField.values && statusField.values.length >= 3 && statusField.values.length <= 8) {
      return "kanban";
    }
  }

  // Card grid for visual entities (has image)
  if (hasImageField(entity)) {
    return "card-grid";
  }

  // Timeline for temporal entities
  if (isTemporalEntity(entity)) {
    return "timeline";
  }

  // Sidebar-detail for entities with long text content (description, body, etc.)
  if (hasRichTextField(entity) && displayable >= 5) {
    return "sidebar-detail";
  }

  // Dense table for many fields or bulk capabilities
  if (displayable > 6 || entity.capabilities.includes("bulk-actions")) {
    return "dense-table";
  }

  // Simple table for everything else
  return "simple-table";
}

function selectCreatePattern(entity: EntitySpec): PatternName {
  const editable = countEditableFields(entity);

  // Wizard for explicit capability
  if (entity.capabilities.includes("wizard")) {
    return "wizard";
  }

  // Modal form for simple entities
  if (editable <= 5 && !hasRichTextField(entity)) {
    return "modal-form";
  }

  // Sectioned form for complex entities
  if (editable > 10) {
    const groups = groupFieldsByAffinity(entity);
    if (groups.length >= 3) {
      return "sectioned-form";
    }
  }

  // Page form for medium entities
  return "page-form";
}

function selectDetailPattern(entity: EntitySpec): PatternName {
  const displayable = countDisplayableFields(entity);

  // Profile for person entities
  if (isPersonEntity(entity)) {
    return "profile-detail";
  }

  // Tabbed for rich entities with related data
  if (
    displayable > 8 ||
    entity.capabilities.includes("comments") ||
    entity.capabilities.includes("activity-log") ||
    entity.capabilities.includes("attachments") ||
    (entity.relations && entity.relations.length > 0)
  ) {
    return "tabbed-detail";
  }

  // Simple for small entities
  return "simple-detail";
}

// ---------------------------------------------------------------------------
// Configuration builder
// ---------------------------------------------------------------------------

function buildConfig(
  entity: EntitySpec,
  pattern: PatternName,
  _intent: ViewIntent,
): PatternConfig {
  return {
    previewFields: rankFieldsForListPreview(entity),
    titleField: findTitleField(entity),
    statusField: findStatusField(entity),
    dateField: findDateField(entity),
    imageField: findImageField(entity),
    fieldGroups: pattern === "sectioned-form" ? groupFieldsByAffinity(entity) : undefined,
    hasSearch: entity.capabilities.includes("search"),
    hasFilters: entity.capabilities.includes("filter"),
    hasPagination: true, // default on for browse
  };
}

// ---------------------------------------------------------------------------
// Derive views from entity
// ---------------------------------------------------------------------------

/**
 * Given an entity, derive what views it needs.
 * Returns an array of view intents.
 */
export function deriveViewsForEntity(entity: EntitySpec): ViewIntent[] {
  const views: ViewIntent[] = [];

  // Every entity gets a browse view
  if (entity.capabilities.includes("list")) {
    views.push("browse-and-act");
  }

  // Detail if explicitly wanted or entity is complex
  if (entity.capabilities.includes("detail") || countDisplayableFields(entity) > 4) {
    views.push("detail");
  }

  // Create form if entity supports creation
  if (entity.capabilities.includes("create")) {
    views.push("create");
  }

  return views;
}
