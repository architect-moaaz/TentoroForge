// Main entry point
export { generateApp } from "./generate-app.js";

// Resolver
export { resolvePattern, deriveViewsForEntity } from "./resolver.js";

// Types
export type {
  AppSpec,
  EntitySpec,
  FieldSpec,
  FieldType,
  EntityCapability,
  RelationSpec,
  ViewIntent,
  ViewSpec,
  UserContext,
  PatternName,
  PatternSelection,
  PatternConfig,
  FieldGroup,
} from "./types.js";

// Field analysis utilities
export {
  countDisplayableFields,
  countEditableFields,
  findTitleField,
  findStatusField,
  findDateField,
  findImageField,
  hasImageField,
  hasRichTextField,
  isPersonEntity,
  isTemporalEntity,
  rankFieldsForListPreview,
  rankFieldsForTable,
  groupFieldsByAffinity,
  inferInputType,
  inferColumnRender,
  inferTextInputType,
  pluralize,
  slugify,
  toLabel,
} from "./field-analysis.js";

// Data source generation
export {
  generateDataSources,
  generateDashboardDataSources,
  generateAuthDataSources,
} from "./datasources.js";
