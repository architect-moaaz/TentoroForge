/**
 * IR Validator — validates an IR document against the node registry and schema rules.
 *
 * Returns a list of errors. Empty list = valid IR.
 */

import type { AppIR, PageIR, IRNode, ActionDef, DataSourceDef } from "./types.js";
import { isValidNodeType, getNodeSpec, getRequiredProps } from "./registry.js";

// ---------------------------------------------------------------------------
// Error types
// ---------------------------------------------------------------------------

export interface ValidationError {
  path: string; // e.g., "pages[0].root.children[1]"
  code: string;
  message: string;
  severity: "error" | "warning";
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export function validateIR(ir: AppIR): ValidationError[] {
  const errors: ValidationError[] = [];
  const ctx: ValidationContext = {
    errors,
    dataSources: new Set(Object.keys(ir.dataSources ?? {})),
    fragments: new Set(Object.keys(ir.fragments ?? {})),
    pages: new Map(),
    currentPageState: new Set(),
    currentPageModals: new Set(),
  };

  // Build page index
  for (const page of ir.pages) {
    ctx.pages.set(page.$id, page);
  }

  // Validate schema version
  if (ir.$schema !== "tentoroforge/ir/1.0") {
    errors.push({
      path: "$schema",
      code: "INVALID_SCHEMA",
      message: `Unknown schema: ${ir.$schema}. Expected "tentoroforge/ir/1.0"`,
      severity: "error",
    });
  }

  // Validate app
  if (!ir.app?.name) {
    errors.push({
      path: "app.name",
      code: "MISSING_REQUIRED",
      message: "App name is required",
      severity: "error",
    });
  }

  // Validate data sources
  for (const [name, ds] of Object.entries(ir.dataSources ?? {})) {
    validateDataSource(ds, `dataSources.${name}`, ctx);
  }

  // Validate pages
  for (let i = 0; i < ir.pages.length; i++) {
    validatePage(ir.pages[i], `pages[${i}]`, ctx);
  }

  // Validate fragments
  for (const [name, frag] of Object.entries(ir.fragments ?? {})) {
    validateNode(frag.root, `fragments.${name}.root`, ctx);
  }

  // Check for duplicate page IDs
  const pageIds = new Set<string>();
  for (const page of ir.pages) {
    if (pageIds.has(page.$id)) {
      errors.push({
        path: `pages`,
        code: "DUPLICATE_PAGE_ID",
        message: `Duplicate page ID: "${page.$id}"`,
        severity: "error",
      });
    }
    pageIds.add(page.$id);
  }

  // Check for duplicate routes
  const routes = new Set<string>();
  for (const page of ir.pages) {
    if (routes.has(page.route)) {
      errors.push({
        path: `pages`,
        code: "DUPLICATE_ROUTE",
        message: `Duplicate route: "${page.route}"`,
        severity: "error",
      });
    }
    routes.add(page.route);
  }

  return errors;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface ValidationContext {
  errors: ValidationError[];
  dataSources: Set<string>;
  fragments: Set<string>;
  pages: Map<string, PageIR>;
  currentPageState: Set<string>;
  currentPageModals: Set<string>;
}

// ---------------------------------------------------------------------------
// Data source validation
// ---------------------------------------------------------------------------

function validateDataSource(ds: DataSourceDef, path: string, ctx: ValidationContext): void {
  if (!ds.type) {
    ctx.errors.push({
      path: `${path}.type`,
      code: "MISSING_REQUIRED",
      message: "Data source type is required",
      severity: "error",
    });
  }
  if (!ds.method) {
    ctx.errors.push({
      path: `${path}.method`,
      code: "MISSING_REQUIRED",
      message: "Data source method is required",
      severity: "error",
    });
  }
  if (!ds.path) {
    ctx.errors.push({
      path: `${path}.path`,
      code: "MISSING_REQUIRED",
      message: "Data source path is required",
      severity: "error",
    });
  }
  const validMethods = ["GET", "POST", "PUT", "PATCH", "DELETE"];
  if (ds.method && !validMethods.includes(ds.method)) {
    ctx.errors.push({
      path: `${path}.method`,
      code: "INVALID_VALUE",
      message: `Invalid method: "${ds.method}". Must be one of: ${validMethods.join(", ")}`,
      severity: "error",
    });
  }

  // Validate onSuccess/onError invalidation targets
  if (ds.onSuccess?.invalidate) {
    for (const target of ds.onSuccess.invalidate) {
      if (!ctx.dataSources.has(target)) {
        ctx.errors.push({
          path: `${path}.onSuccess.invalidate`,
          code: "UNKNOWN_DATA_SOURCE",
          message: `Invalidation target "${target}" is not a declared data source`,
          severity: "warning",
        });
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Page validation
// ---------------------------------------------------------------------------

function validatePage(page: PageIR, path: string, ctx: ValidationContext): void {
  if (!page.$id) {
    ctx.errors.push({
      path: `${path}.$id`,
      code: "MISSING_REQUIRED",
      message: "Page $id is required",
      severity: "error",
    });
  }
  if (!page.route) {
    ctx.errors.push({
      path: `${path}.route`,
      code: "MISSING_REQUIRED",
      message: "Page route is required",
      severity: "error",
    });
  }
  if (!page.root) {
    ctx.errors.push({
      path: `${path}.root`,
      code: "MISSING_REQUIRED",
      message: "Page root node is required",
      severity: "error",
    });
    return;
  }

  // Set up page-scoped context
  ctx.currentPageState = new Set(Object.keys(page.state ?? {}));
  ctx.currentPageModals = new Set(Object.keys(page.modals ?? {}));

  // Validate root node
  validateNode(page.root, `${path}.root`, ctx);

  // Validate modals
  for (const [name, modal] of Object.entries(page.modals ?? {})) {
    if (!modal.title) {
      ctx.errors.push({
        path: `${path}.modals.${name}.title`,
        code: "MISSING_REQUIRED",
        message: "Modal title is required",
        severity: "error",
      });
    }
    if (modal.body) {
      validateNode(modal.body, `${path}.modals.${name}.body`, ctx);
    }
    if (modal.footer) {
      validateNode(modal.footer, `${path}.modals.${name}.footer`, ctx);
    }
  }
}

// ---------------------------------------------------------------------------
// Node validation (recursive)
// ---------------------------------------------------------------------------

function validateNode(node: IRNode, path: string, ctx: ValidationContext): void {
  if (!node || typeof node !== "object") {
    ctx.errors.push({
      path,
      code: "INVALID_NODE",
      message: "Node must be an object",
      severity: "error",
    });
    return;
  }

  const nodeType = (node as { node: string }).node;

  // Check node type exists
  if (!nodeType) {
    ctx.errors.push({
      path,
      code: "MISSING_NODE_TYPE",
      message: "Node is missing the 'node' property",
      severity: "error",
    });
    return;
  }

  // FragmentRef is special
  if (nodeType === "FragmentRef") {
    const ref = (node as { $ref?: string }).$ref;
    if (!ref) {
      ctx.errors.push({
        path: `${path}.$ref`,
        code: "MISSING_REQUIRED",
        message: "FragmentRef requires a $ref property",
        severity: "error",
      });
    } else {
      const fragName = ref.replace("#/fragments/", "");
      if (!ctx.fragments.has(fragName)) {
        ctx.errors.push({
          path: `${path}.$ref`,
          code: "UNKNOWN_FRAGMENT",
          message: `Fragment "${fragName}" is not defined`,
          severity: "error",
        });
      }
    }
    return;
  }

  if (!isValidNodeType(nodeType)) {
    ctx.errors.push({
      path: `${path}.node`,
      code: "UNKNOWN_NODE_TYPE",
      message: `Unknown node type: "${nodeType}"`,
      severity: "error",
    });
    return;
  }

  // Check required props — inputs with missing bind are warnings (auto-fixable)
  const INPUT_NODES = new Set(["TextInput", "TextArea", "Select", "Checkbox", "Toggle", "RadioGroup", "DatePicker", "FilePicker", "Slider", "ColorPicker", "RichTextEditor"]);
  const requiredProps = getRequiredProps(nodeType);
  for (const prop of requiredProps) {
    const value = (node as Record<string, unknown>)[prop.name];
    if (value === undefined || value === null || value === "") {
      // Missing bind/options on inputs → warning (can be auto-fixed)
      const isAutoFixable = INPUT_NODES.has(nodeType) && (prop.name === "bind" || prop.name === "options");
      ctx.errors.push({
        path: `${path}.${prop.name}`,
        code: "MISSING_REQUIRED",
        message: `Required prop "${prop.name}" is missing on ${nodeType}`,
        severity: isAutoFixable ? "warning" : "error",
      });
    }
  }

  // Validate bindings
  validateBindings(node, path, ctx);

  // Validate actions
  validateActions(node, path, ctx);

  // Recursively validate children
  const record = node as Record<string, unknown>;

  if (Array.isArray(record.children)) {
    for (let i = 0; i < record.children.length; i++) {
      validateNode(record.children[i] as IRNode, `${path}.children[${i}]`, ctx);
    }
  }

  // Named slots
  if (record.header && typeof record.header === "object" && "node" in (record.header as object)) {
    validateNode(record.header as IRNode, `${path}.header`, ctx);
  }
  if (record.footer && typeof record.footer === "object" && "node" in (record.footer as object)) {
    validateNode(record.footer as IRNode, `${path}.footer`, ctx);
  }
  if (record.media && typeof record.media === "object" && "node" in (record.media as object)) {
    validateNode(record.media as IRNode, `${path}.media`, ctx);
  }
  if (record.emptyState && typeof record.emptyState === "object" && "node" in (record.emptyState as object)) {
    validateNode(record.emptyState as IRNode, `${path}.emptyState`, ctx);
  }
  if (record.template && typeof record.template === "object" && "node" in (record.template as object)) {
    validateNode(record.template as IRNode, `${path}.template`, ctx);
  }
  if (record.loading && typeof record.loading === "object" && "node" in (record.loading as object)) {
    validateNode(record.loading as IRNode, `${path}.loading`, ctx);
  }
  if (record.error && typeof record.error === "object" && "node" in (record.error as object)) {
    validateNode(record.error as IRNode, `${path}.error`, ctx);
  }
  if (record.then && typeof record.then === "object" && "node" in (record.then as object)) {
    validateNode(record.then as IRNode, `${path}.then`, ctx);
  }
  if (record.else && typeof record.else === "object" && "node" in (record.else as object)) {
    validateNode(record.else as IRNode, `${path}.else`, ctx);
  }

  // Slot cases
  if (record.cases && typeof record.cases === "object") {
    for (const [key, caseNode] of Object.entries(record.cases as Record<string, unknown>)) {
      if (caseNode && typeof caseNode === "object" && "node" in (caseNode as object)) {
        validateNode(caseNode as IRNode, `${path}.cases.${key}`, ctx);
      }
    }
  }

  // Tabs
  if (Array.isArray(record.tabs)) {
    for (let i = 0; i < record.tabs.length; i++) {
      const tab = record.tabs[i] as Record<string, unknown>;
      if (tab.content && typeof tab.content === "object" && "node" in (tab.content as object)) {
        validateNode(tab.content as IRNode, `${path}.tabs[${i}].content`, ctx);
      }
    }
  }

  // Accordion items
  if (Array.isArray(record.items) && nodeType === "Accordion") {
    for (let i = 0; i < record.items.length; i++) {
      const item = record.items[i] as Record<string, unknown>;
      if (item.content && typeof item.content === "object" && "node" in (item.content as object)) {
        validateNode(item.content as IRNode, `${path}.items[${i}].content`, ctx);
      }
    }
  }

  // DataTable column renders
  if (Array.isArray(record.columns)) {
    for (let i = 0; i < record.columns.length; i++) {
      const col = record.columns[i] as Record<string, unknown>;
      if (col.render && typeof col.render === "object" && "node" in (col.render as object)) {
        validateNode(col.render as IRNode, `${path}.columns[${i}].render`, ctx);
      }
    }
  }

  // Form actions
  if (Array.isArray(record.actions) && nodeType === "Form") {
    for (let i = 0; i < record.actions.length; i++) {
      const actionNode = record.actions[i] as unknown;
      if (actionNode && typeof actionNode === "object" && "node" in (actionNode as object)) {
        validateNode(actionNode as IRNode, `${path}.actions[${i}]`, ctx);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Binding validation
// ---------------------------------------------------------------------------

function validateBindings(node: IRNode, path: string, ctx: ValidationContext): void {
  const record = node as Record<string, unknown>;
  const nodeType = record.node as string;
  const spec = getNodeSpec(nodeType);
  if (!spec) return;

  for (const propSpec of spec.props) {
    if (propSpec.type !== "binding") continue;
    const value = record[propSpec.name];
    if (typeof value !== "string" || !value) continue;

    // Validate state: bindings
    if (value.startsWith("state:")) {
      const statePath = value.slice(6).split(".")[0];
      if (ctx.currentPageState.size > 0 && !ctx.currentPageState.has(statePath)) {
        ctx.errors.push({
          path: `${path}.${propSpec.name}`,
          code: "UNKNOWN_STATE",
          message: `State "${statePath}" is not declared in the page state`,
          severity: "warning",
        });
      }
    }

    // Validate source: bindings
    if (value.startsWith("source:")) {
      const sourceName = value.slice(7).split(".")[0];
      if (!ctx.dataSources.has(sourceName)) {
        ctx.errors.push({
          path: `${path}.${propSpec.name}`,
          code: "UNKNOWN_DATA_SOURCE",
          message: `Data source "${sourceName}" is not declared`,
          severity: "warning",
        });
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Action validation
// ---------------------------------------------------------------------------

function validateActions(node: IRNode, path: string, ctx: ValidationContext): void {
  const record = node as Record<string, unknown>;

  // Check known action props
  const actionProps = ["action", "onRowClick", "onRemove", "onSubmit"];
  for (const propName of actionProps) {
    const action = record[propName];
    if (action && typeof action === "object" && "type" in (action as object)) {
      validateAction(action as ActionDef, `${path}.${propName}`, ctx);
    }
  }

  // Row actions / bulk actions (arrays)
  for (const arrayProp of ["rowActions", "bulkActions"]) {
    if (Array.isArray(record[arrayProp])) {
      for (let i = 0; i < (record[arrayProp] as unknown[]).length; i++) {
        const action = (record[arrayProp] as unknown[])[i];
        if (action && typeof action === "object" && "type" in (action as object)) {
          validateAction(action as ActionDef, `${path}.${arrayProp}[${i}]`, ctx);
        }
      }
    }
  }
}

function validateAction(action: ActionDef, path: string, ctx: ValidationContext): void {
  const validTypes = [
    "navigate", "mutate", "setState", "openModal",
    "closeModal", "toast", "invalidate", "sequence", "custom",
  ];

  if (!validTypes.includes(action.type)) {
    ctx.errors.push({
      path: `${path}.type`,
      code: "INVALID_ACTION_TYPE",
      message: `Unknown action type: "${action.type}"`,
      severity: "error",
    });
    return;
  }

  switch (action.type) {
    case "mutate":
      if (!ctx.dataSources.has(action.source)) {
        ctx.errors.push({
          path: `${path}.source`,
          code: "UNKNOWN_DATA_SOURCE",
          message: `Mutation source "${action.source}" is not a declared data source`,
          severity: "warning",
        });
      }
      break;

    case "openModal":
      if (ctx.currentPageModals.size > 0 && !ctx.currentPageModals.has(action.modal)) {
        ctx.errors.push({
          path: `${path}.modal`,
          code: "UNKNOWN_MODAL",
          message: `Modal "${action.modal}" is not declared on the current page`,
          severity: "warning",
        });
      }
      break;

    case "invalidate":
      for (const source of action.sources) {
        if (!ctx.dataSources.has(source)) {
          ctx.errors.push({
            path: `${path}.sources`,
            code: "UNKNOWN_DATA_SOURCE",
            message: `Invalidation target "${source}" is not a declared data source`,
            severity: "warning",
          });
        }
      }
      break;

    case "sequence":
      for (let i = 0; i < action.steps.length; i++) {
        validateAction(action.steps[i], `${path}.steps[${i}]`, ctx);
      }
      break;

    case "setState":
      if (action.path) {
        const statePath = action.path.split(".")[0];
        if (ctx.currentPageState.size > 0 && !ctx.currentPageState.has(statePath)) {
          ctx.errors.push({
            path: `${path}.path`,
            code: "UNKNOWN_STATE",
            message: `State "${statePath}" is not declared in the page state`,
            severity: "warning",
          });
        }
      }
      break;
  }
}

// ---------------------------------------------------------------------------
// Convenience: validate a single page
// ---------------------------------------------------------------------------

export function validatePage_standalone(
  page: PageIR,
  dataSources: Record<string, DataSourceDef> = {},
  fragments: Record<string, unknown> = {},
): ValidationError[] {
  const ir: AppIR = {
    $schema: "tentoroforge/ir/1.0",
    app: { name: "validation-check" },
    tokens: {},
    dataSources,
    pages: [page],
    fragments: fragments as AppIR["fragments"],
  };
  return validateIR(ir);
}
