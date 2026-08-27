/**
 * @tentoroforge/ahtml — Annotated HTML system
 *
 * Provides a lossless design-layer IR using plain HTML+CSS with data-*
 * annotations for logic (bindings, actions, state, slots).
 */

// Schema — attribute constants and valid values
export {
  // Attribute names
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
  // Valid values
  SLOT_TYPES,
  ACTION_TYPES,
  BIND_TYPES,
  COMPONENT_TYPES,
  MODAL_SIZES,
  ALL_ATTRIBUTES,
  TEMPLATE_RE,
} from "./schema.js";

export type {
  AHTMLSlotType,
  AHTMLActionType,
  AHTMLBindType,
  AHTMLComponentType,
  AHTMLModalSize,
} from "./schema.js";

// Types — structured representations
export type {
  AnnotatedApp,
  AnnotatedPage,
  DataSourceBinding,
  DataSourceParam,
  StateBinding,
  FieldBinding,
  ActionBinding,
  SlotBinding,
  RepeaterBinding,
  ComponentBinding,
  ModalBinding,
  AnnotatedElement,
  NavigationItem,
} from "./types.js";

// Validation
export { validateAnnotatedHtml } from "./validate.js";
export type { ValidationError, ValidationResult } from "./validate.js";

// IR-to-AHTML converter
export { irToAnnotatedHtml, pageIrToAnnotatedHtml, emitNodeToHtml } from "./ir-to-html.js";

// AHTML parser
export { parseAnnotatedHtml } from "./html-parser.js";
export type { ParsedPage, PageSummary } from "./html-parser.js";

// AHTML-to-TSX prompt builder
export { buildTsxContext, buildTsxPrompt } from "./html-to-tsx.js";
export type { TsxGenerationContext, PageTsxContext, TsxHints } from "./html-to-tsx.js";
