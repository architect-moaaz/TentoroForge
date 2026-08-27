/**
 * Annotated HTML types — structured representations extracted from
 * HTML strings with data-* annotations.
 */

import type { AHTMLActionType, AHTMLBindType, AHTMLSlotType, AHTMLComponentType, AHTMLModalSize } from "./schema.js";

// ---------------------------------------------------------------------------
// Top-level structures
// ---------------------------------------------------------------------------

/** A complete annotated HTML app (multiple pages + shared data sources) */
export interface AnnotatedApp {
  name: string;
  theme?: string;
  dataSources: Record<string, DataSourceBinding>;
  pages: AnnotatedPage[];
  navigation?: NavigationItem[];
}

/** A single page represented as annotated HTML */
export interface AnnotatedPage {
  /** Page identifier */
  pageId: string;
  /** URL route pattern */
  route: string;
  /** Page title */
  title?: string;
  /** Authentication requirements */
  auth?: {
    required: boolean;
    roles?: string[];
  };
  /** The annotated HTML content */
  html: string;
  /** Optional extracted CSS (from GrapeJS getCss()) */
  css?: string;
  /** Inline data source definitions for this page */
  dataSources?: Record<string, DataSourceBinding>;
}

// ---------------------------------------------------------------------------
// Data binding types
// ---------------------------------------------------------------------------

/** Data source configuration extracted from data-source-* attributes */
export interface DataSourceBinding {
  name: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  params?: Record<string, DataSourceParam>;
}

export interface DataSourceParam {
  type: AHTMLBindType;
  from?: string;
  default?: string | number | boolean;
}

/** State binding extracted from data-bind attribute */
export interface StateBinding {
  /** Full binding expression (e.g., "state:form.name") */
  expression: string;
  /** The state key (e.g., "form") */
  stateKey: string;
  /** The nested path (e.g., "name") */
  path?: string;
  /** Value type */
  type?: AHTMLBindType;
}

/** Field binding within a repeater context */
export interface FieldBinding {
  /** Field name (e.g., "name", "email") */
  field: string;
  /** Render hint (e.g., "badge", "date:relative", "avatar") */
  render?: string;
}

// ---------------------------------------------------------------------------
// Action types
// ---------------------------------------------------------------------------

/** Action configuration extracted from data-action-* attributes */
export interface ActionBinding {
  type: AHTMLActionType;
  /** Navigate target */
  to?: string;
  /** Mutation data source */
  source?: string;
  /** Confirmation prompt */
  confirm?: string;
  /** setState value */
  value?: string | number | boolean | null;
}

// ---------------------------------------------------------------------------
// Slot types
// ---------------------------------------------------------------------------

/** Slot placeholder extracted from data-slot attribute */
export interface SlotBinding {
  type: AHTMLSlotType;
  entity?: string;
  config?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Repeater types
// ---------------------------------------------------------------------------

/** Repeater configuration extracted from data-repeat-* attributes */
export interface RepeaterBinding {
  /** Data source reference */
  data: string;
  /** Item key field */
  key?: string;
  /** Empty state content selector or message */
  empty?: string;
}

// ---------------------------------------------------------------------------
// Component types
// ---------------------------------------------------------------------------

/** Component hint extracted from data-component-* attributes */
export interface ComponentBinding {
  type: AHTMLComponentType;
  props?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Modal types
// ---------------------------------------------------------------------------

/** Modal configuration */
export interface ModalBinding {
  id: string;
  size?: AHTMLModalSize;
}

// ---------------------------------------------------------------------------
// Structured element (parsed from HTML)
// ---------------------------------------------------------------------------

/** An HTML element with its annotations extracted into typed fields */
export interface AnnotatedElement {
  /** HTML tag name */
  tag: string;
  /** CSS classes */
  classes: string[];
  /** Inline styles */
  styles?: Record<string, string>;
  /** Text content (may contain {{template}} expressions) */
  textContent?: string;

  /** Data source binding */
  source?: DataSourceBinding;
  /** State binding */
  bind?: StateBinding;
  /** Field binding */
  field?: FieldBinding;
  /** Action binding */
  action?: ActionBinding;
  /** Slot binding */
  slot?: SlotBinding;
  /** Repeater binding */
  repeat?: RepeaterBinding;
  /** Component type hint */
  component?: ComponentBinding;
  /** Modal binding */
  modal?: ModalBinding;
  /** Visibility condition */
  visible?: string;
  /** Inverse visibility condition */
  visibleNot?: string;

  /** Child elements */
  children: AnnotatedElement[];
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

export interface NavigationItem {
  label: string;
  icon?: string;
  route?: string;
  children?: NavigationItem[];
}
