/**
 * Binding System — resolves IR binding expressions to JavaScript expressions.
 *
 * Binding types:
 *   state:filters.search       → page-local reactive state
 *   source:tasks.items          → data from React Query hook
 *   {{row.title}}               → iterator item field
 *   {{item.name | relativeDate}} → pipe/formatter
 *   static string               → quoted string literal
 */

import { EmitContext } from "./context.js";

// ---------------------------------------------------------------------------
// Pipe/formatter registry
// ---------------------------------------------------------------------------

interface PipeDef {
  importName: string;
  importFrom: string;
  fn: string;
  args?: string;
}

const PIPE_MAP: Record<string, PipeDef> = {
  relativeDate: {
    importName: "formatRelativeDate",
    importFrom: "@/lib/formatters",
    fn: "formatRelativeDate",
  },
  date: {
    importName: "formatDate",
    importFrom: "@/lib/formatters",
    fn: "formatDate",
  },
  currency: {
    importName: "formatCurrency",
    importFrom: "@/lib/formatters",
    fn: "formatCurrency",
  },
  number: {
    importName: "formatNumber",
    importFrom: "@/lib/formatters",
    fn: "formatNumber",
  },
  percent: {
    importName: "formatPercent",
    importFrom: "@/lib/formatters",
    fn: "formatPercent",
  },
  capitalize: {
    importName: "capitalize",
    importFrom: "@/lib/formatters",
    fn: "capitalize",
  },
  uppercase: {
    importName: "toUpperCase",
    importFrom: "@/lib/formatters",
    fn: "toUpperCase",
  },
  lowercase: {
    importName: "toLowerCase",
    importFrom: "@/lib/formatters",
    fn: "toLowerCase",
  },
};

// ---------------------------------------------------------------------------
// Main binding resolver
// ---------------------------------------------------------------------------

/**
 * Resolves a binding expression to a JavaScript expression string.
 * Returns the expression WITHOUT surrounding JSX braces — the caller adds those.
 */
export function emitBinding(
  binding: string | undefined | null,
  ctx: EmitContext,
): string {
  if (!binding) return '""';

  // State reference: state:filters.search
  if (binding.startsWith("state:")) {
    const path = binding.slice(6);
    return path;
  }

  // Data source reference: source:tasks.items
  if (binding.startsWith("source:")) {
    const path = binding.slice(7);
    const [sourceName, ...rest] = path.split(".");
    const varName = `${sourceName}Data`;
    return rest.length ? `${varName}?.${rest.join(".")}` : varName;
  }

  // Template expression: {{row.title}} or {{item.dueDate | relativeDate}}
  if (binding.includes("{{")) {
    const parts = binding.split(/(\{\{.+?\}\})/g);

    if (parts.length === 1) {
      // No template expressions — static string
      return JSON.stringify(binding);
    }

    // If the whole string is a single expression, don't use template literal
    if (parts.length === 1 || (parts.length === 3 && parts[0] === "" && parts[2] === "")) {
      const expr = parts.find((p) => p.startsWith("{{"))!;
      return resolveTemplateExpr(expr.slice(2, -2).trim(), ctx);
    }

    // Multiple parts — use template literal
    const resolved = parts
      .map((part) => {
        if (part.startsWith("{{") && part.endsWith("}}")) {
          const expr = part.slice(2, -2).trim();
          return `\${${resolveTemplateExpr(expr, ctx)}}`;
        }
        return part;
      })
      .join("");

    return `\`${resolved}\``;
  }

  // Static string
  return JSON.stringify(binding);
}

/**
 * Resolves a template expression (the content between {{ }}).
 * Handles pipes: value | formatName
 */
function resolveTemplateExpr(expr: string, ctx: EmitContext): string {
  // Handle pipes: {{value | relativeDate}}
  if (expr.includes("|")) {
    const [valuePart, ...pipeParts] = expr.split("|").map((s) => s.trim());
    let result = resolveVariable(valuePart, ctx);

    for (const pipeName of pipeParts) {
      // Handle pipe with args: currency:USD
      const [name, ...pipeArgs] = pipeName.split(":");
      const pipe = PIPE_MAP[name.trim()];
      if (pipe) {
        ctx.ensureImport(pipe.importFrom, pipe.importName);
        const args = pipeArgs.length
          ? `, ${pipeArgs.map((a) => JSON.stringify(a.trim())).join(", ")}`
          : pipe.args
            ? `, ${pipe.args}`
            : "";
        result = `${pipe.fn}(${result}${args})`;
      }
    }

    return result;
  }

  return resolveVariable(expr, ctx);
}

/**
 * Resolves a variable name to its JavaScript equivalent based on context.
 */
function resolveVariable(name: string, ctx: EmitContext): string {
  // Built-in helpers
  if (name === "today") return "new Date()";

  // Inside DataTable column: row.field → row.original.field
  if (name.startsWith("row.") && ctx.iteratorVar === "row.original") {
    return `row.original.${name.slice(4)}`;
  }

  // Inside Repeater: item.field stays as-is
  if (name.startsWith("item.") && ctx.iteratorVar === "item") {
    return name;
  }

  // State reference shorthand in expressions: state:something
  if (name.startsWith("state:")) {
    return name.slice(6);
  }

  // Source reference shorthand
  if (name.startsWith("source:")) {
    const path = name.slice(7);
    const [sourceName, ...rest] = path.split(".");
    const varName = `${sourceName}Data`;
    return rest.length ? `${varName}?.${rest.join(".")}` : varName;
  }

  return name;
}

// ---------------------------------------------------------------------------
// State binding — returns getter and setter
// ---------------------------------------------------------------------------

export interface StateBind {
  getter: string;
  setter: string;
  stateKey: string;
}

/**
 * Resolves a state binding to getter/setter pair.
 * "state:filters.search" → { getter: "filters.search", setter: "setFilters", stateKey: "filters" }
 */
export function emitStateBinding(binding: string, _ctx: EmitContext): StateBind {
  const path = binding.startsWith("state:") ? binding.slice(6) : binding;
  const parts = path.split(".");
  const stateKey = parts[0];
  const setter = `set${stateKey.charAt(0).toUpperCase()}${stateKey.slice(1)}`;

  if (parts.length === 1) {
    return { getter: stateKey, setter, stateKey };
  }

  // Nested: filters.search → getter is "filters.search", setter updates the object
  return { getter: path, setter, stateKey };
}

// ---------------------------------------------------------------------------
// Expression resolver (for if/switch conditions)
// ---------------------------------------------------------------------------

/**
 * Resolves a condition expression used in Slot if/switch.
 * Handles simple comparisons and binding references.
 */
export function emitExpression(expr: string, ctx: EmitContext): string {
  // Replace binding references in the expression
  let result = expr;

  // Replace state: references
  result = result.replace(/state:(\w+(?:\.\w+)*)/g, (_match, path) => path);

  // Replace source: references
  result = result.replace(/source:(\w+)(?:\.(\w+(?:\.\w+)*))?/g, (_match, name, rest) => {
    const varName = `${name}Data`;
    return rest ? `${varName}?.${rest}` : varName;
  });

  // Replace {{var}} templates
  result = result.replace(/\{\{(.+?)\}\}/g, (_match, inner) => {
    return resolveVariable(inner.trim(), ctx);
  });

  return result;
}

// ---------------------------------------------------------------------------
// JSX content helper
// ---------------------------------------------------------------------------

/**
 * Wraps a binding value for use as JSX text content.
 * Static strings → literal text (no braces)
 * Dynamic → {expression}
 */
export function emitJSXContent(binding: string, ctx: EmitContext): string {
  const resolved = emitBinding(binding, ctx);

  // If it's a quoted string literal, strip quotes for JSX text
  if (resolved.startsWith('"') && resolved.endsWith('"')) {
    return resolved.slice(1, -1);
  }

  // Dynamic expression
  return `{${resolved}}`;
}
