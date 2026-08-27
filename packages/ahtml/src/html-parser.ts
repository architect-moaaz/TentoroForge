/**
 * AHTML Parser — extracts structured annotations from annotated HTML.
 *
 * Parses HTML with cheerio and builds a semantic model of pages,
 * data sources, state bindings, actions, slots, and repeaters.
 */

import * as cheerio from "cheerio";
import type {
  AnnotatedPage,
  AnnotatedElement,
  DataSourceBinding,
  StateBinding,
  FieldBinding,
  ActionBinding,
  SlotBinding,
  RepeaterBinding,
  ComponentBinding,
  ModalBinding,
} from "./types.js";
import {
  ATTR_PAGE_ID, ATTR_ROUTE, ATTR_TITLE, ATTR_AUTH_REQUIRED, ATTR_AUTH_ROLES,
  ATTR_SOURCE, ATTR_SOURCE_METHOD, ATTR_SOURCE_PATH, ATTR_SOURCE_PARAMS,
  ATTR_SLOT, ATTR_ENTITY, ATTR_SLOT_CONFIG,
  ATTR_REPEAT, ATTR_REPEAT_KEY, ATTR_REPEAT_EMPTY,
  ATTR_FIELD, ATTR_FIELD_RENDER,
  ATTR_BIND, ATTR_BIND_TYPE,
  ATTR_ACTION, ATTR_ACTION_TO, ATTR_ACTION_SOURCE, ATTR_ACTION_CONFIRM, ATTR_ACTION_VALUE,
  ATTR_VISIBLE, ATTR_VISIBLE_NOT,
  ATTR_COMPONENT, ATTR_COMPONENT_PROPS,
  ATTR_MODAL_ID, ATTR_MODAL_SIZE,
} from "./schema.js";
import type { AHTMLActionType, AHTMLBindType, AHTMLSlotType, AHTMLComponentType, AHTMLModalSize } from "./schema.js";

// ---------------------------------------------------------------------------
// Page-level extraction
// ---------------------------------------------------------------------------

export interface ParsedPage {
  /** Page metadata */
  pageId: string;
  route: string;
  title?: string;
  auth?: { required: boolean; roles?: string[] };

  /** Data sources defined in <meta> tags */
  dataSources: Record<string, DataSourceBinding>;

  /** State definitions from <meta> tags */
  state: Record<string, unknown>;

  /** Modal definitions */
  modals: Record<string, { title: string; size?: string }>;

  /** Structured element tree */
  rootElement: AnnotatedElement;

  /** Raw body HTML (for LLM context) */
  bodyHtml: string;

  /** Summary of bindings for the LLM prompt */
  summary: PageSummary;
}

export interface PageSummary {
  /** All unique state bindings found */
  stateBindings: StateBinding[];
  /** All unique data sources referenced */
  dataSourceRefs: string[];
  /** All action bindings found */
  actions: ActionBinding[];
  /** All slot placeholders */
  slots: SlotBinding[];
  /** All repeaters */
  repeaters: RepeaterBinding[];
  /** All field bindings */
  fields: FieldBinding[];
  /** Component types used */
  componentTypes: string[];
}

// ---------------------------------------------------------------------------
// Main parse function
// ---------------------------------------------------------------------------

export function parseAnnotatedHtml(html: string): ParsedPage[] {
  const $ = cheerio.load(html);
  const pages: ParsedPage[] = [];

  // Extract data sources from <meta> tags
  const dataSources: Record<string, DataSourceBinding> = {};
  $("meta[data-source]").each((_, el) => {
    const $el = $(el);
    const name = $el.attr(ATTR_SOURCE)!;
    dataSources[name] = {
      name,
      method: ($el.attr(ATTR_SOURCE_METHOD) as any) || "GET",
      path: $el.attr(ATTR_SOURCE_PATH) || `/api/${name}`,
      params: $el.attr(ATTR_SOURCE_PARAMS) ? safeParse($el.attr(ATTR_SOURCE_PARAMS)!) : undefined,
    };
  });

  // Extract state from <meta> tags
  const state: Record<string, unknown> = {};
  $("meta[data-state]").each((_, el) => {
    const $el = $(el);
    const key = $el.attr("data-state")!;
    const valueStr = $el.attr("data-state-value");
    state[key] = valueStr ? safeParse(valueStr) : null;
  });

  // Find page root elements
  $("[data-page-id]").each((_, el) => {
    const $el = $(el);
    const pageId = $el.attr(ATTR_PAGE_ID)!;
    const route = $el.attr(ATTR_ROUTE) || "/";
    const title = $el.attr(ATTR_TITLE);
    const authRequired = $el.attr(ATTR_AUTH_REQUIRED) === "true";
    const authRoles = $el.attr(ATTR_AUTH_ROLES)?.split(",").filter(Boolean);

    // Parse modals
    const modals: Record<string, { title: string; size?: string }> = {};
    $("[data-modal-id]").each((_, modalEl) => {
      const $modal = $(modalEl);
      const id = $modal.attr(ATTR_MODAL_ID)!;
      const titleEl = $modal.find("h2").first();
      modals[id] = {
        title: titleEl.text() || id,
        size: $modal.attr(ATTR_MODAL_SIZE),
      };
    });

    // Parse element tree
    const rootElement = parseElement($el, $);

    // Collect summary
    const summary = collectSummary(rootElement);

    // Add data sources from summary refs that exist in global sources
    for (const ref of summary.dataSourceRefs) {
      if (!dataSources[ref]) {
        dataSources[ref] = {
          name: ref,
          method: "GET",
          path: `/api/${ref}`,
        };
      }
    }

    pages.push({
      pageId,
      route,
      title,
      auth: authRequired ? { required: true, roles: authRoles } : undefined,
      dataSources,
      state,
      modals,
      rootElement,
      bodyHtml: $el.html() || "",
      summary,
    });
  });

  return pages;
}

// ---------------------------------------------------------------------------
// Element tree parsing
// ---------------------------------------------------------------------------

function parseElement($el: cheerio.Cheerio<any>, $: cheerio.CheerioAPI): AnnotatedElement {
  const tag = ($el.prop("tagName")?.toLowerCase() ?? "div") as string;
  const classStr = $el.attr("class") || "";
  const classes = classStr.split(/\s+/).filter(Boolean);

  const element: AnnotatedElement = {
    tag,
    classes,
    children: [],
  };

  // Inline styles
  const styleStr = $el.attr("style");
  if (styleStr) {
    element.styles = parseInlineStyles(styleStr);
  }

  // Text content (direct text nodes only)
  const directText = $el.contents().filter((_, node) => node.type === "text").text().trim();
  if (directText) {
    element.textContent = directText;
  }

  // Data source
  const source = $el.attr(ATTR_SOURCE);
  if (source) {
    element.source = {
      name: source,
      method: ($el.attr(ATTR_SOURCE_METHOD) as any) || "GET",
      path: $el.attr(ATTR_SOURCE_PATH) || `/api/${source}`,
      params: $el.attr(ATTR_SOURCE_PARAMS) ? safeParse($el.attr(ATTR_SOURCE_PARAMS)!) : undefined,
    };
  }

  // State binding
  const bind = $el.attr(ATTR_BIND);
  if (bind) {
    const parts = bind.replace(/^state:/, "").split(".");
    element.bind = {
      expression: bind,
      stateKey: parts[0],
      path: parts.length > 1 ? parts.slice(1).join(".") : undefined,
      type: $el.attr(ATTR_BIND_TYPE) as AHTMLBindType | undefined,
    };
  }

  // Field binding
  const field = $el.attr(ATTR_FIELD);
  if (field) {
    element.field = {
      field,
      render: $el.attr(ATTR_FIELD_RENDER),
    };
  }

  // Action
  const action = $el.attr(ATTR_ACTION);
  if (action) {
    element.action = {
      type: action as AHTMLActionType,
      to: $el.attr(ATTR_ACTION_TO),
      source: $el.attr(ATTR_ACTION_SOURCE),
      confirm: $el.attr(ATTR_ACTION_CONFIRM),
      value: $el.attr(ATTR_ACTION_VALUE) ? safeParse($el.attr(ATTR_ACTION_VALUE)!) : undefined,
    };
  }

  // Slot
  const slot = $el.attr(ATTR_SLOT);
  if (slot) {
    element.slot = {
      type: slot as AHTMLSlotType,
      entity: $el.attr(ATTR_ENTITY),
      config: $el.attr(ATTR_SLOT_CONFIG) ? safeParse($el.attr(ATTR_SLOT_CONFIG)!) : undefined,
    };
  }

  // Repeater
  const repeat = $el.attr(ATTR_REPEAT);
  if (repeat) {
    element.repeat = {
      data: repeat,
      key: $el.attr(ATTR_REPEAT_KEY),
      empty: $el.attr(ATTR_REPEAT_EMPTY),
    };
  }

  // Component hint
  const component = $el.attr(ATTR_COMPONENT);
  if (component) {
    element.component = {
      type: component as AHTMLComponentType,
      props: $el.attr(ATTR_COMPONENT_PROPS) ? safeParse($el.attr(ATTR_COMPONENT_PROPS)!) : undefined,
    };
  }

  // Modal
  const modalId = $el.attr(ATTR_MODAL_ID);
  if (modalId) {
    element.modal = {
      id: modalId,
      size: $el.attr(ATTR_MODAL_SIZE) as AHTMLModalSize | undefined,
    };
  }

  // Visibility
  const visible = $el.attr(ATTR_VISIBLE);
  if (visible) element.visible = visible;

  const visibleNot = $el.attr(ATTR_VISIBLE_NOT);
  if (visibleNot) element.visibleNot = visibleNot;

  // Parse children recursively
  $el.children().each((_, childEl) => {
    element.children.push(parseElement($(childEl), $));
  });

  return element;
}

// ---------------------------------------------------------------------------
// Summary collection
// ---------------------------------------------------------------------------

function collectSummary(root: AnnotatedElement): PageSummary {
  const stateBindings: StateBinding[] = [];
  const dataSourceRefs = new Set<string>();
  const actions: ActionBinding[] = [];
  const slots: SlotBinding[] = [];
  const repeaters: RepeaterBinding[] = [];
  const fields: FieldBinding[] = [];
  const componentTypes = new Set<string>();

  function walk(el: AnnotatedElement): void {
    if (el.bind) stateBindings.push(el.bind);
    if (el.source) dataSourceRefs.add(el.source.name);
    if (el.action) actions.push(el.action);
    if (el.slot) slots.push(el.slot);
    if (el.repeat) {
      repeaters.push(el.repeat);
      dataSourceRefs.add(el.repeat.data);
    }
    if (el.field) fields.push(el.field);
    if (el.component) componentTypes.add(el.component.type);

    for (const child of el.children) {
      walk(child);
    }
  }

  walk(root);

  return {
    stateBindings,
    dataSourceRefs: Array.from(dataSourceRefs),
    actions,
    slots,
    repeaters,
    fields,
    componentTypes: Array.from(componentTypes),
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function safeParse(json: string): any {
  try {
    return JSON.parse(json);
  } catch {
    return json;
  }
}

function parseInlineStyles(style: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const part of style.split(";")) {
    const [key, ...valueParts] = part.split(":");
    if (key && valueParts.length) {
      result[key.trim()] = valueParts.join(":").trim();
    }
  }
  return result;
}
