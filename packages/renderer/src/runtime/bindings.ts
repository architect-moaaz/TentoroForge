import type { DataBinding } from "@tentoroforge/schema";
import { evaluateExpression } from "./expressions";

export type RenderContext = {
  data: Record<string, unknown>;
  user?: Record<string, unknown>;
  scope?: Record<string, unknown>; // for Repeat-bound child scopes
};

/**
 * Walk a dotted path with optional array-index segments against a root value.
 * Supports paths like "items[0].name" or "address.city".
 */
function walkPath(root: unknown, path: string): unknown {
  // Tokenize path into segments: "items[0].name" → ["items", "0", "name"]
  const segments: string[] = [];
  for (const segment of path.split(".")) {
    const bracketMatch = segment.match(/^([^\[]+)\[(\d+)\](.*)$/);
    if (bracketMatch) {
      if (bracketMatch[1]) segments.push(bracketMatch[1]);
      segments.push(bracketMatch[2]);
      if (bracketMatch[3]) {
        // handle trailing segments like [0].foo → foo already split above
        segments.push(...bracketMatch[3].replace(/^\./, "").split(".").filter(Boolean));
      }
    } else {
      // Handle inline bracket at start e.g. "[0]"
      const pureIndex = segment.match(/^\[(\d+)\]$/);
      if (pureIndex) {
        segments.push(pureIndex[1]);
      } else {
        segments.push(segment);
      }
    }
  }

  let current: unknown = root;
  for (const seg of segments) {
    if (current == null) return undefined;
    if (Array.isArray(current)) {
      const idx = parseInt(seg, 10);
      if (isNaN(idx)) return undefined;
      current = current[idx];
    } else if (typeof current === "object") {
      current = (current as Record<string, unknown>)[seg];
    } else {
      return undefined;
    }
  }
  return current;
}

export function resolveBinding(b: DataBinding, ctx: RenderContext): unknown {
  const root = (ctx.data as Record<string, unknown>)[b.source];
  if (root === undefined) return undefined;
  // Use manual path walker to support dotted paths + array indices like "items[0].name"
  return walkPath(root, b.path);
}

// A plain property/index path: identifier + `.prop` / `[idx]` segments only.
// FEEL-lite throws on array subscripts like `arr[0]`, but walkPath resolves
// them — so route bracket-index paths through walkPath. Everything else
// (operators, calls, pure-dotted paths) stays on FEEL-lite (unchanged).
const PLAIN_INDEX_PATH = /^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|\[\d+\])*$/;

export function evalExpression(expr: string, ctx: Record<string, unknown>): unknown {
  try {
    if (expr.includes("[") && PLAIN_INDEX_PATH.test(expr)) {
      return walkPath(ctx, expr);
    }
    return evaluateExpression(expr, ctx);
  } catch (err) {
    // Per spec: visibleIf failures are treated as false; binding failures as undefined.
    console.warn("[renderer] expression error:", expr, err);
    return false;
  }
}
