/**
 * Annotated HTML Schema — defines all data-* attributes used to encode
 * logic (bindings, actions, state, slots) in plain HTML+CSS.
 *
 * Each attribute maps 1:1 to a concept in @tentoroforge/ir types.
 */

// ---------------------------------------------------------------------------
// Attribute name constants
// ---------------------------------------------------------------------------

/** Page-level metadata */
export const ATTR_PAGE_ID = "data-page-id";
export const ATTR_ROUTE = "data-route";
export const ATTR_TITLE = "data-title";
export const ATTR_AUTH_REQUIRED = "data-auth-required";
export const ATTR_AUTH_ROLES = "data-auth-roles";

/** Data source binding */
export const ATTR_SOURCE = "data-source";
export const ATTR_SOURCE_METHOD = "data-source-method";
export const ATTR_SOURCE_PATH = "data-source-path";
export const ATTR_SOURCE_PARAMS = "data-source-params";

/** Slot system (replaces PlaceholderSlot) */
export const ATTR_SLOT = "data-slot";
export const ATTR_ENTITY = "data-entity";
export const ATTR_SLOT_CONFIG = "data-slot-config";

/** Repeater (replaces RepeaterNode) */
export const ATTR_REPEAT = "data-repeat";
export const ATTR_REPEAT_KEY = "data-repeat-key";
export const ATTR_REPEAT_EMPTY = "data-repeat-empty";

/** Field binding within repeated items */
export const ATTR_FIELD = "data-field";
export const ATTR_FIELD_RENDER = "data-field-render";

/** State binding */
export const ATTR_BIND = "data-bind";
export const ATTR_BIND_TYPE = "data-bind-type";

/** Actions */
export const ATTR_ACTION = "data-action";
export const ATTR_ACTION_TO = "data-action-to";
export const ATTR_ACTION_SOURCE = "data-action-source";
export const ATTR_ACTION_CONFIRM = "data-action-confirm";
export const ATTR_ACTION_VALUE = "data-action-value";

/** Conditional rendering */
export const ATTR_VISIBLE = "data-visible";
export const ATTR_VISIBLE_NOT = "data-visible-not";

/** Component type hints */
export const ATTR_COMPONENT = "data-component";
export const ATTR_COMPONENT_PROPS = "data-component-props";

/** Modals */
export const ATTR_MODAL_ID = "data-modal-id";
export const ATTR_MODAL_TRIGGER = "data-modal-trigger";
export const ATTR_MODAL_SIZE = "data-modal-size";

// ---------------------------------------------------------------------------
// Valid values
// ---------------------------------------------------------------------------

export const SLOT_TYPES = [
  "entity-table",
  "entity-form",
  "entity-detail",
  "auth-form",
  "stat-cards",
  "crud-actions",
  "detail-tabs",
  "features-list",
  "branding",
  "nav-sidebar",
  "nav-topbar",
  "recent-items",
  "search-bar",
  "status-filter",
  "empty-state",
] as const;

export type AHTMLSlotType = (typeof SLOT_TYPES)[number];

export const ACTION_TYPES = [
  "navigate",
  "mutate",
  "setState",
  "openModal",
  "closeModal",
  "toast",
  "invalidate",
  "sequence",
  "custom",
  "trigger-workflow",
] as const;

/** Workflow binding */
export const ATTR_ACTION_WORKFLOW = "data-action-workflow";

export type AHTMLActionType = (typeof ACTION_TYPES)[number];

export const BIND_TYPES = ["string", "number", "boolean"] as const;

export type AHTMLBindType = (typeof BIND_TYPES)[number];

export const COMPONENT_TYPES = [
  "Stack",
  "Row",
  "Grid",
  "DataTable",
  "Form",
  "Card",
  "Tabs",
  "Accordion",
  "Chart",
  "Repeater",
  "Slot",
  "AsyncSlot",
  "StatCard",
  "EmptyState",
  "ModalTrigger",
] as const;

export type AHTMLComponentType = (typeof COMPONENT_TYPES)[number];

export const MODAL_SIZES = ["sm", "md", "lg", "xl", "full"] as const;

export type AHTMLModalSize = (typeof MODAL_SIZES)[number];

// ---------------------------------------------------------------------------
// All recognized annotation attributes
// ---------------------------------------------------------------------------

export const ALL_ATTRIBUTES = [
  ATTR_PAGE_ID,
  ATTR_ROUTE,
  ATTR_TITLE,
  ATTR_AUTH_REQUIRED,
  ATTR_AUTH_ROLES,
  ATTR_SOURCE,
  ATTR_SOURCE_METHOD,
  ATTR_SOURCE_PATH,
  ATTR_SOURCE_PARAMS,
  ATTR_SLOT,
  ATTR_ENTITY,
  ATTR_SLOT_CONFIG,
  ATTR_REPEAT,
  ATTR_REPEAT_KEY,
  ATTR_REPEAT_EMPTY,
  ATTR_FIELD,
  ATTR_FIELD_RENDER,
  ATTR_BIND,
  ATTR_BIND_TYPE,
  ATTR_ACTION,
  ATTR_ACTION_TO,
  ATTR_ACTION_SOURCE,
  ATTR_ACTION_CONFIRM,
  ATTR_ACTION_VALUE,
  ATTR_VISIBLE,
  ATTR_VISIBLE_NOT,
  ATTR_COMPONENT,
  ATTR_COMPONENT_PROPS,
  ATTR_MODAL_ID,
  ATTR_MODAL_TRIGGER,
  ATTR_MODAL_SIZE,
] as const;

/** Template interpolation pattern: {{expression}} */
export const TEMPLATE_RE = /\{\{(.+?)\}\}/g;
