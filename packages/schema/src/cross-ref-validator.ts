import type { Page } from "./page";

export type ValidationContext = {
  entities: Set<string>;
  workflows: Set<string>;
  libraryNames: Set<string>;
  tokens: Set<string>;
};

export type CrossRefError = {
  path: (string | number)[];
  message: string;
};

const RESERVED_TYPES = new Set([
  "Stack", "Row", "Grid", "Container", "Spacer",
  "Box", "Text", "Image",
  "Repeat", "Conditional", "DataBoundary",
  "Slot",
]);

const TOKEN_STYLE_KEYS = new Set([
  "color", "background", "padding", "paddingX", "paddingY",
  "margin", "marginX", "marginY", "fontSize", "fontWeight",
  "lineHeight", "letterSpacing", "borderRadius", "borderColor",
  "borderWidth", "shadow", "width", "height", "gap",
]);

export function validateCrossRefs(page: Page, ctx: ValidationContext): CrossRefError[] {
  const errors: CrossRefError[] = [];

  // 1. Data source entities
  for (const [i, ds] of (page.dataSources ?? []).entries()) {
    if (!ctx.entities.has((ds as any).entity)) {
      errors.push({
        path: ["dataSources", i, "entity"],
        message: `unknown entity '${(ds as any).entity}' (data sources)`,
      });
    }
  }

  // 2-4. Walk all nodes
  function walk(node: any, path: (string | number)[]): void {
    // Library component check
    if (node.type && !RESERVED_TYPES.has(node.type) && !ctx.libraryNames.has(node.type)) {
      errors.push({
        path: [...path, "type"],
        message: `unknown library component '${node.type}'`,
      });
    }

    // Workflow ref check on event handlers
    for (const [eventName, handler] of Object.entries(node.on ?? {})) {
      if ((handler as any)?.workflow) {
        const w = (handler as any).workflow;
        if (!ctx.workflows.has(w)) {
          errors.push({
            path: [...path, "on", eventName, "workflow"],
            message: `unknown workflow '${w}' (event handler)`,
          });
        }
      }
    }

    // Token reference check on style
    for (const [key, value] of Object.entries(node.style ?? {})) {
      if (TOKEN_STYLE_KEYS.has(key) && typeof value === "string" && !ctx.tokens.has(value)) {
        errors.push({
          path: [...path, "style", key],
          message: `unknown token '${value}' (style.${key})`,
        });
      }
    }

    for (const [i, child] of (node.children ?? []).entries()) {
      walk(child, [...path, "children", i]);
    }
    if (node.else) {
      for (const [i, child] of node.else.entries()) {
        walk(child, [...path, "else", i]);
      }
    }
  }

  walk((page as any).root, ["root"]);
  return errors;
}
