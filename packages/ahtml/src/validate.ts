/**
 * Annotated HTML Validator — validates HTML strings against the AHTML schema.
 *
 * Uses cheerio to parse HTML and check that all data-* attributes contain
 * valid values and required co-attributes are present.
 */

import * as cheerio from "cheerio";
import {
  ATTR_PAGE_ID,
  ATTR_ROUTE,
  ATTR_SLOT,
  ATTR_ENTITY,
  ATTR_SOURCE,
  ATTR_SOURCE_METHOD,
  ATTR_SOURCE_PATH,
  ATTR_REPEAT,
  ATTR_BIND,
  ATTR_BIND_TYPE,
  ATTR_ACTION,
  ATTR_ACTION_TO,
  ATTR_ACTION_SOURCE,
  ATTR_COMPONENT,
  ATTR_COMPONENT_PROPS,
  ATTR_MODAL_ID,
  ATTR_MODAL_SIZE,
  ATTR_VISIBLE,
  ATTR_VISIBLE_NOT,
  SLOT_TYPES,
  ACTION_TYPES,
  BIND_TYPES,
  COMPONENT_TYPES,
  MODAL_SIZES,
} from "./schema.js";

// ---------------------------------------------------------------------------
// Validation result
// ---------------------------------------------------------------------------

export interface ValidationError {
  /** CSS selector path to the offending element */
  selector: string;
  /** The attribute that caused the error */
  attribute: string;
  /** Human-readable error message */
  message: string;
  /** Error severity */
  severity: "error" | "warning";
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
  warnings: ValidationError[];
  /** Summary: count of pages, slots, bindings, actions found */
  stats: {
    pages: number;
    slots: number;
    bindings: number;
    actions: number;
    repeaters: number;
    dataSources: number;
    components: number;
  };
}

// ---------------------------------------------------------------------------
// Validate function
// ---------------------------------------------------------------------------

export function validateAnnotatedHtml(html: string): ValidationResult {
  const $ = cheerio.load(html);
  const errors: ValidationError[] = [];
  const warnings: ValidationError[] = [];
  const stats = {
    pages: 0,
    slots: 0,
    bindings: 0,
    actions: 0,
    repeaters: 0,
    dataSources: 0,
    components: 0,
  };

  // Track page IDs for uniqueness
  const pageIds = new Set<string>();

  // Check every element with any data-* annotation
  $("[data-page-id], [data-slot], [data-source], [data-repeat], [data-bind], [data-action], [data-component], [data-modal-id], [data-visible], [data-visible-not]").each((_, el) => {
    const $el = $(el);
    const selector = buildSelector($el, $);

    // Page validation
    const pageId = $el.attr(ATTR_PAGE_ID);
    if (pageId !== undefined) {
      stats.pages++;
      if (!pageId) {
        errors.push({ selector, attribute: ATTR_PAGE_ID, message: "Page ID must not be empty", severity: "error" });
      } else if (pageIds.has(pageId)) {
        errors.push({ selector, attribute: ATTR_PAGE_ID, message: `Duplicate page ID: "${pageId}"`, severity: "error" });
      } else {
        pageIds.add(pageId);
      }

      const route = $el.attr(ATTR_ROUTE);
      if (!route) {
        errors.push({ selector, attribute: ATTR_ROUTE, message: "Page element requires data-route", severity: "error" });
      } else if (!route.startsWith("/")) {
        errors.push({ selector, attribute: ATTR_ROUTE, message: `Route must start with "/": "${route}"`, severity: "error" });
      }
    }

    // Slot validation
    const slotType = $el.attr(ATTR_SLOT);
    if (slotType !== undefined) {
      stats.slots++;
      if (!SLOT_TYPES.includes(slotType as any)) {
        errors.push({ selector, attribute: ATTR_SLOT, message: `Invalid slot type: "${slotType}". Valid: ${SLOT_TYPES.join(", ")}`, severity: "error" });
      }

      // Entity-bound slots should have data-entity
      const entitySlots = ["entity-table", "entity-form", "entity-detail", "stat-cards", "crud-actions", "detail-tabs", "recent-items", "status-filter"];
      if (entitySlots.includes(slotType!) && !$el.attr(ATTR_ENTITY)) {
        warnings.push({ selector, attribute: ATTR_ENTITY, message: `Slot "${slotType}" should specify data-entity`, severity: "warning" });
      }
    }

    // Data source validation
    const source = $el.attr(ATTR_SOURCE);
    if (source !== undefined) {
      stats.dataSources++;
      if (!source) {
        errors.push({ selector, attribute: ATTR_SOURCE, message: "Data source name must not be empty", severity: "error" });
      }

      const method = $el.attr(ATTR_SOURCE_METHOD);
      if (method && !["GET", "POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase())) {
        errors.push({ selector, attribute: ATTR_SOURCE_METHOD, message: `Invalid HTTP method: "${method}"`, severity: "error" });
      }

      const path = $el.attr(ATTR_SOURCE_PATH);
      if (!path) {
        warnings.push({ selector, attribute: ATTR_SOURCE_PATH, message: "Data source should specify data-source-path", severity: "warning" });
      }
    }

    // Repeater validation
    const repeat = $el.attr(ATTR_REPEAT);
    if (repeat !== undefined) {
      stats.repeaters++;
      if (!repeat) {
        errors.push({ selector, attribute: ATTR_REPEAT, message: "Repeater data reference must not be empty", severity: "error" });
      }
    }

    // Binding validation
    const bind = $el.attr(ATTR_BIND);
    if (bind !== undefined) {
      stats.bindings++;
      if (!bind) {
        errors.push({ selector, attribute: ATTR_BIND, message: "Binding expression must not be empty", severity: "error" });
      }

      const bindType = $el.attr(ATTR_BIND_TYPE);
      if (bindType && !BIND_TYPES.includes(bindType as any)) {
        errors.push({ selector, attribute: ATTR_BIND_TYPE, message: `Invalid bind type: "${bindType}". Valid: ${BIND_TYPES.join(", ")}`, severity: "error" });
      }
    }

    // Action validation
    const action = $el.attr(ATTR_ACTION);
    if (action !== undefined) {
      stats.actions++;
      if (!ACTION_TYPES.includes(action as any)) {
        errors.push({ selector, attribute: ATTR_ACTION, message: `Invalid action type: "${action}". Valid: ${ACTION_TYPES.join(", ")}`, severity: "error" });
      }

      // Navigate requires data-action-to
      if (action === "navigate" && !$el.attr(ATTR_ACTION_TO)) {
        errors.push({ selector, attribute: ATTR_ACTION_TO, message: "Navigate action requires data-action-to", severity: "error" });
      }

      // Mutate requires data-action-source
      if (action === "mutate" && !$el.attr(ATTR_ACTION_SOURCE)) {
        errors.push({ selector, attribute: ATTR_ACTION_SOURCE, message: "Mutate action requires data-action-source", severity: "error" });
      }
    }

    // Component validation
    const component = $el.attr(ATTR_COMPONENT);
    if (component !== undefined) {
      stats.components++;
      if (!COMPONENT_TYPES.includes(component as any)) {
        warnings.push({ selector, attribute: ATTR_COMPONENT, message: `Unknown component type: "${component}". Known: ${COMPONENT_TYPES.join(", ")}`, severity: "warning" });
      }

      const propsStr = $el.attr(ATTR_COMPONENT_PROPS);
      if (propsStr) {
        try {
          JSON.parse(propsStr);
        } catch {
          errors.push({ selector, attribute: ATTR_COMPONENT_PROPS, message: "data-component-props must be valid JSON", severity: "error" });
        }
      }
    }

    // Modal validation
    const modalId = $el.attr(ATTR_MODAL_ID);
    if (modalId !== undefined) {
      if (!modalId) {
        errors.push({ selector, attribute: ATTR_MODAL_ID, message: "Modal ID must not be empty", severity: "error" });
      }

      const size = $el.attr(ATTR_MODAL_SIZE);
      if (size && !MODAL_SIZES.includes(size as any)) {
        errors.push({ selector, attribute: ATTR_MODAL_SIZE, message: `Invalid modal size: "${size}". Valid: ${MODAL_SIZES.join(", ")}`, severity: "error" });
      }
    }

    // Visibility validation (just check non-empty)
    const visible = $el.attr(ATTR_VISIBLE);
    if (visible !== undefined && !visible) {
      errors.push({ selector, attribute: ATTR_VISIBLE, message: "Visibility expression must not be empty", severity: "error" });
    }

    const visibleNot = $el.attr(ATTR_VISIBLE_NOT);
    if (visibleNot !== undefined && !visibleNot) {
      errors.push({ selector, attribute: ATTR_VISIBLE_NOT, message: "Inverse visibility expression must not be empty", severity: "error" });
    }
  });

  return {
    valid: errors.length === 0,
    errors,
    warnings,
    stats,
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildSelector($el: cheerio.Cheerio<any>, $: cheerio.CheerioAPI): string {
  const tag = $el.prop("tagName")?.toLowerCase() ?? "unknown";
  const id = $el.attr("id");
  if (id) return `${tag}#${id}`;

  const pageId = $el.attr(ATTR_PAGE_ID);
  if (pageId) return `${tag}[data-page-id="${pageId}"]`;

  const slot = $el.attr(ATTR_SLOT);
  if (slot) return `${tag}[data-slot="${slot}"]`;

  const component = $el.attr(ATTR_COMPONENT);
  if (component) return `${tag}[data-component="${component}"]`;

  const classes = $el.attr("class");
  if (classes) {
    const first = classes.split(/\s+/).slice(0, 2).join(".");
    return `${tag}.${first}`;
  }

  return tag;
}
