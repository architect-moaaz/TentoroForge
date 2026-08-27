// Re-exports the existing FEEL-lite evaluator from the runtime template so the
// renderer and the workflow engine share one expression language.
import { evaluateExpression as _evaluateExpression } from "@tentoroforge/feel-lite";

export function evaluateExpression(expr: string, ctx: Record<string, unknown>): unknown {
  // Normalize JavaScript-style == to FEEL-style = for comparison expressions
  // Use negative lookbehind to avoid replacing the second = in !=
  const normalized = expr.replace(/(?<!!)==/g, "=");
  return _evaluateExpression(normalized as string, ctx as Record<string, unknown>);
}
