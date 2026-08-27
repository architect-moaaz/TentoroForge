/** FEEL-lite AST evaluator — walks the AST and evaluates against a context. */

import type { ASTNode } from "./ast";

export type Context = Record<string, unknown>;

/** Built-in functions available in FEEL-lite expressions. */
const BUILT_IN_FUNCTIONS: Record<string, (...args: unknown[]) => unknown> = {
  sum: (...args: unknown[]) => {
    const nums = flattenNumbers(args);
    return nums.reduce((a, b) => a + b, 0);
  },
  count: (...args: unknown[]) => {
    const list = args.length === 1 && Array.isArray(args[0]) ? args[0] : args;
    return list.length;
  },
  min: (...args: unknown[]) => {
    const nums = flattenNumbers(args);
    return nums.length > 0 ? Math.min(...nums) : null;
  },
  max: (...args: unknown[]) => {
    const nums = flattenNumbers(args);
    return nums.length > 0 ? Math.max(...nums) : null;
  },
  avg: (...args: unknown[]) => {
    const nums = flattenNumbers(args);
    return nums.length > 0 ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
  },
  abs: (x: unknown) => Math.abs(toNumber(x)),
  floor: (x: unknown) => Math.floor(toNumber(x)),
  ceiling: (x: unknown) => Math.ceil(toNumber(x)),
  round: (x: unknown, scale?: unknown) => {
    const n = toNumber(x);
    const s = scale !== undefined ? toNumber(scale) : 0;
    const factor = Math.pow(10, s);
    return Math.round(n * factor) / factor;
  },
  contains: (str: unknown, sub: unknown) => String(str).includes(String(sub)),
  "starts with": (str: unknown, prefix: unknown) =>
    String(str).startsWith(String(prefix)),
  // Underscore aliases — the canonical form emitted by the business-rules
  // condition compiler (parses identically on the backend runtime too).
  starts_with: (str: unknown, prefix: unknown) =>
    String(str).startsWith(String(prefix)),
  "ends with": (str: unknown, suffix: unknown) =>
    String(str).endsWith(String(suffix)),
  ends_with: (str: unknown, suffix: unknown) =>
    String(str).endsWith(String(suffix)),
  matches: (str: unknown, pattern: unknown) => {
    try {
      return new RegExp(String(pattern)).test(String(str));
    } catch {
      return false;
    }
  },
  string: (x: unknown) => String(x ?? ""),
  number: (x: unknown) => {
    const n = Number(x);
    return isNaN(n) ? null : n;
  },
  date: (x: unknown) => {
    const d = new Date(String(x));
    return isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10);
  },
  now: () => new Date().toISOString(),
  duration: (x: unknown) => {
    // Parse ISO 8601 duration string to seconds
    const str = String(x);
    const m = str.match(
      /^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/i,
    );
    if (!m) return null;
    const days = parseInt(m[1] || "0");
    const hours = parseInt(m[2] || "0");
    const minutes = parseInt(m[3] || "0");
    const seconds = parseInt(m[4] || "0");
    return (days * 86400 + hours * 3600 + minutes * 60 + seconds) * 1000;
  },
};

function flattenNumbers(args: unknown[]): number[] {
  const result: number[] = [];
  for (const arg of args) {
    if (Array.isArray(arg)) {
      result.push(...flattenNumbers(arg));
    } else {
      const n = Number(arg);
      if (!isNaN(n)) result.push(n);
    }
  }
  return result;
}

function toNumber(x: unknown): number {
  const n = Number(x);
  return isNaN(n) ? 0 : n;
}

function resolveIdentifier(name: string, ctx: Context): unknown {
  // Handle dotted names: "customer.age"
  const parts = name.split(".");
  let current: unknown = ctx;
  for (const part of parts) {
    // An ABSENT field is null, not undefined — matching the Python engine
    // (ctx.get(name) -> None). Without this, `field = null` reads false in the
    // browser playground but true in the shipped app (they must agree).
    if (current == null || typeof current !== "object") return null;
    current = (current as Record<string, unknown>)[part];
  }
  return current === undefined ? null : current;
}

// Equality mirroring the Python engine's `_fuzzy_equal` (backend/runtime/
// feel_lite/evaluator.py) so the browser playground and the server evaluate a
// condition identically. Pinned by the cross-engine conformance suite
// (frontend/src/__tests__/feel-conformance.test.ts).
function fuzzyEqual(a: unknown, b: unknown): boolean {
  if (a === null && b === null) return true;
  if (a === null || b === null) return false;
  // Numeric coercion when BOTH sides parse as numbers (Python: float(a)==float(b)).
  // Guard empty string / whitespace, which Number() turns into 0 but float() rejects.
  const emptyish = (v: unknown) =>
    typeof v === "string" && v.trim() === "";
  if (!emptyish(a) && !emptyish(b)) {
    const na = Number(a);
    const nb = Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na === nb;
  }
  // Case-insensitive string comparison (Python: str(a).lower()==str(b).lower()).
  return String(a).toLowerCase() === String(b).toLowerCase();
}

export function evaluate(node: ASTNode, ctx: Context): unknown {
  switch (node.type) {
    case "NumberLiteral":
      return node.value;
    case "StringLiteral":
      return node.value;
    case "BooleanLiteral":
      return node.value;
    case "NullLiteral":
      return null;
    case "WildcardExpression":
      return Symbol.for("FEEL_WILDCARD");

    case "Identifier":
      return resolveIdentifier(node.name, ctx);

    case "MemberExpression": {
      const obj = evaluate(node.object, ctx);
      if (obj == null || typeof obj !== "object") return undefined;
      return (obj as Record<string, unknown>)[node.property];
    }

    case "UnaryExpression": {
      const val = toNumber(evaluate(node.operand, ctx));
      return node.operator === "-" ? -val : val;
    }

    case "BinaryExpression": {
      const left = evaluate(node.left, ctx);
      const right = evaluate(node.right, ctx);
      const l = toNumber(left);
      const r = toNumber(right);

      switch (node.operator) {
        case "+":
          // String concatenation if either is a string and non-numeric
          if (typeof left === "string" || typeof right === "string") {
            return String(left ?? "") + String(right ?? "");
          }
          return l + r;
        case "-":
          return l - r;
        case "*":
          return l * r;
        case "/":
          return r === 0 ? null : l / r;
        case "%":
          return r === 0 ? null : l % r;
        case "^":
          return Math.pow(l, r);
      }
      break;
    }

    case "ComparisonExpression": {
      const left = evaluate(node.left, ctx);
      const right = evaluate(node.right, ctx);

      // Equality/inequality use fuzzy-equal (numeric coercion + case-insensitive
      // + null handling), matching the Python engine exactly.
      if (node.operator === "=") return fuzzyEqual(left, right);
      if (node.operator === "!=") return !fuzzyEqual(left, right);

      // Ordering (<, <=, >, >=): a null operand yields false (no coercion).
      if (left === null || right === null) {
        return false;
      }

      // Numeric comparison (= / != already handled above via fuzzyEqual).
      if (typeof left === "number" && typeof right === "number") {
        switch (node.operator) {
          case "<": return left < right;
          case "<=": return left <= right;
          case ">": return left > right;
          case ">=": return left >= right;
        }
      }

      // String comparison
      const ls = String(left);
      const rs = String(right);
      switch (node.operator) {
        case "<": return ls < rs;
        case "<=": return ls <= rs;
        case ">": return ls > rs;
        case ">=": return ls >= rs;
      }
      break;
    }

    case "LogicalExpression": {
      const left = evaluate(node.left, ctx);
      if (node.operator === "or") {
        return Boolean(left) || Boolean(evaluate(node.right, ctx));
      }
      return Boolean(left) && Boolean(evaluate(node.right, ctx));
    }

    case "NotExpression":
      return !Boolean(evaluate(node.operand, ctx));

    case "IfExpression": {
      const cond = evaluate(node.condition, ctx);
      return Boolean(cond)
        ? evaluate(node.thenBranch, ctx)
        : evaluate(node.elseBranch, ctx);
    }

    case "InExpression": {
      const value = evaluate(node.value, ctx);
      return matchValue(value, node.list, ctx);
    }

    case "BetweenExpression": {
      const val = toNumber(evaluate(node.value, ctx));
      const low = toNumber(evaluate(node.low, ctx));
      const high = toNumber(evaluate(node.high, ctx));
      return val >= low && val <= high;
    }

    case "RangeExpression": {
      // When evaluated standalone (not in InExpression), return a range descriptor
      return {
        __range: true,
        startInclusive: node.startInclusive,
        endInclusive: node.endInclusive,
        start: evaluate(node.start, ctx),
        end: evaluate(node.end, ctx),
      };
    }

    case "ListExpression":
      return node.elements.map((el) => evaluate(el, ctx));

    case "FunctionCall": {
      const fn = BUILT_IN_FUNCTIONS[node.name];
      if (!fn) {
        throw new Error(`Unknown function: ${node.name}`);
      }
      const args = node.args.map((a) => evaluate(a, ctx));
      return fn(...args);
    }
  }

  return null;
}

/** Check if a value matches a FEEL-lite pattern (range, list, or single value). */
export function matchValue(
  value: unknown,
  pattern: ASTNode,
  ctx: Context,
): boolean {
  if (pattern.type === "WildcardExpression") {
    return true;
  }

  if (pattern.type === "RangeExpression") {
    const v = toNumber(value);
    const start = toNumber(evaluate(pattern.start, ctx));
    const end = toNumber(evaluate(pattern.end, ctx));
    const startOk = pattern.startInclusive ? v >= start : v > start;
    const endOk = pattern.endInclusive ? v <= end : v < end;
    return startOk && endOk;
  }

  if (pattern.type === "ListExpression") {
    return pattern.elements.some((el) => {
      if (el.type === "RangeExpression") {
        return matchValue(value, el, ctx);
      }
      const elVal = evaluate(el, ctx);
      return value === elVal || String(value) === String(elVal);
    });
  }

  if (pattern.type === "NotExpression") {
    return !matchValue(value, pattern.operand, ctx);
  }

  // Single value comparison
  const patternVal = evaluate(pattern, ctx);
  return value === patternVal || String(value) === String(patternVal);
}

/** Evaluate a FEEL-lite expression string against a context. */
export function evaluateExpression(
  expr: string,
  ctx: Context,
): unknown {
  if (!expr || !expr.trim()) return null;

  // Import lazily to avoid circular dependency
  const { tokenize } = require("./tokenizer");
  const { parse } = require("./parser");

  const tokens = tokenize(expr);
  const ast = parse(tokens);
  return evaluate(ast, ctx);
}
