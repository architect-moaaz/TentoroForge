/**
 * Runtime binding evaluation.
 *
 * Resolves IR binding expressions to actual values at runtime.
 * This is the runtime equivalent of packages/compiler/src/bindings.ts
 * which emits JavaScript source code strings.
 */

import type { RendererContext } from "./types";

const PIPE_MAP: Record<string, (v: unknown) => unknown> = {
  capitalize: (v) => {
    const s = String(v ?? "");
    return s.charAt(0).toUpperCase() + s.slice(1);
  },
  uppercase: (v) => String(v ?? "").toUpperCase(),
  lowercase: (v) => String(v ?? "").toLowerCase(),
  number: (v) =>
    typeof v === "number" ? v.toLocaleString() : String(v ?? ""),
  currency: (v) =>
    typeof v === "number"
      ? v.toLocaleString("en-US", { style: "currency", currency: "USD" })
      : String(v ?? ""),
  percent: (v) =>
    typeof v === "number" ? `${(v * 100).toFixed(1)}%` : String(v ?? ""),
  compact: (v) => {
    if (typeof v !== "number") return String(v ?? "");
    return Intl.NumberFormat("en", { notation: "compact" }).format(v);
  },
  relativeDate: (v) => {
    if (!v) return "";
    const d = new Date(String(v));
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins} min ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  },
  date: (v) => {
    if (!v) return "";
    return new Date(String(v)).toLocaleDateString();
  },
};

/**
 * Resolve a binding expression to its runtime value.
 *
 * Handles:
 * - "state:path.to.value" → ctx.state[path][to][value]
 * - "source:dataSourceName" → ctx.dataSources[name].data
 * - "source:dataSourceName.field" → ctx.dataSources[name].data[field]
 * - "{{variable}}" or "{{variable | pipe}}" → template expression
 * - Static strings → returned as-is
 */
export function resolveBinding(
  binding: unknown,
  ctx: RendererContext,
): unknown {
  if (binding == null) return undefined;
  if (typeof binding === "number" || typeof binding === "boolean")
    return binding;
  if (typeof binding !== "string") return binding;

  const s = binding.trim();
  if (!s) return undefined;

  // state:path.to.value
  if (s.startsWith("state:")) {
    return getByPath(ctx.state, s.slice(6));
  }

  // source:name or source:name.field
  if (s.startsWith("source:")) {
    const rest = s.slice(7);
    const dot = rest.indexOf(".");
    if (dot === -1) {
      return ctx.dataSources[rest]?.data;
    }
    const sourceName = rest.slice(0, dot);
    const field = rest.slice(dot + 1);
    const data = ctx.dataSources[sourceName]?.data;
    return getByPath(data, field);
  }

  // {{expression}} or {{expression | pipe}}
  if (s.includes("{{")) {
    return resolveTemplate(s, ctx);
  }

  // Static string
  return s;
}

/**
 * Resolve a template string with {{var}} interpolations.
 */
export function resolveTemplate(
  template: string,
  ctx: RendererContext,
): string {
  return template.replace(/\{\{(.+?)\}\}/g, (_match, expr: string) => {
    const trimmed = expr.trim();
    const parts = trimmed.split("|").map((p) => p.trim());
    const varName = parts[0];
    let value = resolveVariable(varName, ctx);

    // Apply pipes
    for (let i = 1; i < parts.length; i++) {
      const pipe = PIPE_MAP[parts[i]];
      if (pipe) value = pipe(value);
    }

    return value == null ? "" : String(value);
  });
}

/**
 * Resolve a single variable name to its value.
 */
function resolveVariable(name: string, ctx: RendererContext): unknown {
  // Iterator scope (Repeater/DataTable context)
  if (ctx.iteratorScope) {
    const { variable, value } = ctx.iteratorScope;
    if (name === variable) return value;
    if (name.startsWith(`${variable}.`)) {
      return getByPath(value, name.slice(variable.length + 1));
    }
  }

  // State
  if (name.startsWith("state:")) {
    return getByPath(ctx.state, name.slice(6));
  }

  // Source
  if (name.startsWith("source:")) {
    const rest = name.slice(7);
    const dot = rest.indexOf(".");
    if (dot === -1) return ctx.dataSources[rest]?.data;
    return getByPath(
      ctx.dataSources[rest.slice(0, dot)]?.data,
      rest.slice(dot + 1),
    );
  }

  // Try iterator scope first (e.g., "item.name" when iteratorScope.variable = "item")
  if (ctx.iteratorScope) {
    const { variable, value } = ctx.iteratorScope;
    if (name.startsWith(`${variable}.`)) {
      return getByPath(value, name.slice(variable.length + 1));
    }
  }

  // Direct state lookup
  return getByPath(ctx.state, name);
}

/**
 * Evaluate a boolean expression for conditionals (Slot.if, visible).
 */
export function resolveExpression(
  expr: string,
  ctx: RendererContext,
): boolean {
  if (!expr) return true;
  const trimmed = expr.trim();

  // Simple negation
  if (trimmed.startsWith("!")) {
    return !resolveExpression(trimmed.slice(1), ctx);
  }

  // Comparison operators
  const compMatch = trimmed.match(/^(.+?)\s*(===?|!==?|>=?|<=?)\s*(.+)$/);
  if (compMatch) {
    const left = resolveBinding(compMatch[1].trim(), ctx);
    const op = compMatch[2];
    let right: unknown = compMatch[3].trim();

    // Parse right side
    if (right === "true") right = true;
    else if (right === "false") right = false;
    else if (right === "null" || right === "undefined") right = null;
    else if (!isNaN(Number(right))) right = Number(right);
    else if (
      typeof right === "string" &&
      right.startsWith('"') &&
      right.endsWith('"')
    )
      right = right.slice(1, -1);
    else right = resolveBinding(right as string, ctx);

    switch (op) {
      case "==":
      case "===":
        return left === right;
      case "!=":
      case "!==":
        return left !== right;
      case ">":
        return Number(left) > Number(right);
      case ">=":
        return Number(left) >= Number(right);
      case "<":
        return Number(left) < Number(right);
      case "<=":
        return Number(left) <= Number(right);
    }
  }

  // Truthy check
  const val = resolveBinding(trimmed, ctx);
  return !!val;
}

/**
 * Get a nested property by dot-separated path.
 */
function getByPath(obj: unknown, path: string): unknown {
  if (obj == null || !path) return obj;
  const parts = path.split(".");
  let current: unknown = obj;
  for (const part of parts) {
    if (current == null || typeof current !== "object") return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

/**
 * Set a nested property by dot-separated path (immutable — returns new object).
 */
export function setByPath(
  obj: Record<string, unknown>,
  path: string,
  value: unknown,
): Record<string, unknown> {
  const parts = path.split(".");
  if (parts.length === 1) {
    return { ...obj, [parts[0]]: value };
  }
  const [head, ...rest] = parts;
  const child = (obj[head] as Record<string, unknown>) ?? {};
  return { ...obj, [head]: setByPath(child, rest.join("."), value) };
}
