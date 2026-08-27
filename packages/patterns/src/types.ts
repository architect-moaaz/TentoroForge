/**
 * Entity Spec Types — the input to the pattern system.
 *
 * An AppSpec describes what the app does (entities, fields, capabilities).
 * The pattern system converts this to IR (how it looks and behaves).
 */

// ---------------------------------------------------------------------------
// Field types
// ---------------------------------------------------------------------------

export type FieldType =
  | "string"
  | "number"
  | "boolean"
  | "date"
  | "datetime"
  | "email"
  | "url"
  | "tel"
  | "richtext"
  | "text"       // long text (not rich)
  | "enum"
  | "image"
  | "avatar"
  | "file"
  | "json"
  | "relation"
  | "string[]"
  | "number[]";

export interface FieldSpec {
  name: string;
  type: FieldType;
  label?: string;
  required?: boolean;
  /** For enum type — the allowed values */
  values?: string[];
  /** For relation type — the target entity name */
  relationTo?: string;
  /** For relation type — cardinality */
  relationType?: "one-to-one" | "many-to-one" | "one-to-many" | "many-to-many";
  /** Display this field in list/card previews */
  displayInList?: boolean;
  /** This field is searchable */
  searchable?: boolean;
  /** This field is filterable */
  filterable?: boolean;
  /** This field is sortable */
  sortable?: boolean;
  /** Default value */
  defaultValue?: unknown;
  /** For string fields — max length */
  maxLength?: number;
  /** For number fields — min/max */
  min?: number;
  max?: number;
  /** For image/avatar — treat as the entity's visual identity */
  isIdentityImage?: boolean;
}

// ---------------------------------------------------------------------------
// Entity
// ---------------------------------------------------------------------------

export interface EntitySpec {
  name: string;
  pluralName?: string;
  description?: string;
  fields: FieldSpec[];
  capabilities: EntityCapability[];
  /** Relations declared at entity level (alternative to field-level) */
  relations?: RelationSpec[];
}

export type EntityCapability =
  | "list"
  | "search"
  | "filter"
  | "create"
  | "edit"
  | "delete"
  | "detail"
  | "assign"
  | "bulk-actions"
  | "export"
  | "import"
  | "comments"
  | "activity-log"
  | "attachments"
  | "kanban"
  | "calendar"
  | "wizard";

export interface RelationSpec {
  from: string;   // field name on this entity
  to: string;     // target entity name
  type: "one-to-one" | "many-to-one" | "one-to-many" | "many-to-many";
  displayField?: string; // which field on the target to show
}

// ---------------------------------------------------------------------------
// View intents
// ---------------------------------------------------------------------------

export type ViewIntent =
  | "browse-and-act"
  | "create"
  | "edit"
  | "detail"
  | "dashboard"
  | "settings"
  | "kanban";

export interface ViewSpec {
  intent: ViewIntent;
  primary?: boolean;
  description?: string;
  /** Override the auto-selected pattern */
  forcePattern?: string;
}

// ---------------------------------------------------------------------------
// App spec (top-level input)
// ---------------------------------------------------------------------------

export interface AppSpec {
  name: string;
  description?: string;
  entities: EntitySpec[];
  /** Cross-entity relationships */
  relationships?: RelationSpec[];
  /** User context for pattern selection heuristics */
  userContext?: UserContext;
  /** Explicit views to generate (if omitted, auto-derived) */
  views?: Record<string, ViewSpec[]>;
}

export interface UserContext {
  domain?: string;       // e.g., "engineering team", "real estate"
  scale?: string;        // e.g., "~50 users, ~500 active tasks"
  priority?: "speed" | "aesthetics" | "density"; // UI density hint
}

// ---------------------------------------------------------------------------
// Pattern selection result
// ---------------------------------------------------------------------------

export type PatternName =
  // Browse
  | "simple-table"
  | "dense-table"
  | "sidebar-detail"
  | "card-grid"
  | "kanban"
  | "timeline"
  // Detail
  | "simple-detail"
  | "tabbed-detail"
  | "profile-detail"
  // Form
  | "modal-form"
  | "page-form"
  | "sectioned-form"
  | "wizard"
  // Dashboard
  | "stat-table-dashboard"
  | "chart-dashboard"
  | "kpi-activity"
  // Config
  | "settings-sidebar"
  // Shell
  | "auth-login"
  | "auth-signup"
  | "empty-state"
  | "error-page";

export interface PatternSelection {
  pattern: PatternName;
  entity: EntitySpec;
  intent: ViewIntent;
  /** Configuration hints for the pattern generator */
  config: PatternConfig;
}

export interface PatternConfig {
  /** Fields to show in list/card preview (top 3-4) */
  previewFields: FieldSpec[];
  /** The primary text field (title/name) */
  titleField?: FieldSpec;
  /** The status/stage enum field */
  statusField?: FieldSpec;
  /** The date field for timeline/calendar */
  dateField?: FieldSpec;
  /** The image/avatar field */
  imageField?: FieldSpec;
  /** Grouped fields for sectioned forms */
  fieldGroups?: FieldGroup[];
  /** Whether to add search */
  hasSearch: boolean;
  /** Whether to add filters */
  hasFilters: boolean;
  /** Whether to add pagination */
  hasPagination: boolean;
}

export interface FieldGroup {
  title: string;
  fields: FieldSpec[];
}
