/** Decision table evaluator — pure function, no DB access. */

import { tokenize, parse, evaluate, matchValue, type Context } from "@/lib/feel-lite";
import type {
  DecisionTableDefinition,
  DecisionTableResult,
  DecisionTableRule,
  HitPolicy,
} from "@/types/decision";

/** Evaluate a decision table against input values. */
export function evaluateDecisionTable(
  table: DecisionTableDefinition,
  inputs: Record<string, unknown>,
): DecisionTableResult {
  const matchedRules: { rule: DecisionTableRule; index: number }[] = [];

  for (let i = 0; i < table.rules.length; i++) {
    const rule = table.rules[i];
    if (ruleMatches(rule, table, inputs)) {
      matchedRules.push({ rule, index: i });
    }
  }

  const matchedRuleIds = matchedRules.map((r) => r.rule.id);
  const outputs = matchedRules.map((r) => extractOutputs(r.rule, table));
  const result = applyHitPolicy(table.hitPolicy, outputs, matchedRules);

  return { hitPolicy: table.hitPolicy, matchedRuleIds, outputs, result };
}

/** Check if a single rule matches the given inputs. */
function ruleMatches(
  rule: DecisionTableRule,
  table: DecisionTableDefinition,
  inputs: Record<string, unknown>,
): boolean {
  for (let i = 0; i < table.inputs.length; i++) {
    const input = table.inputs[i];
    const cellExpr = rule.inputEntries[i] ?? "";
    const inputValue = inputs[input.variableBinding || input.name];

    if (!cellMatches(cellExpr, inputValue, inputs)) {
      return false;
    }
  }
  return true;
}

/** Match a cell expression against a value. */
function cellMatches(
  cellExpr: string,
  value: unknown,
  ctx: Context,
): boolean {
  const trimmed = cellExpr.trim();

  // Empty or wildcard — matches everything
  if (!trimmed || trimmed === "-") return true;

  try {
    const tokens = tokenize(trimmed);
    const ast = parse(tokens);

    // If the expression is a comparison, evaluate it with the input value in context
    if (
      ast.type === "ComparisonExpression" &&
      ast.left.type === "Identifier"
    ) {
      // The cell expression may reference the cell input implicitly
      return Boolean(evaluate(ast, { ...ctx, _cell: value }));
    }

    // For ranges, lists, negation — use matchValue
    if (
      ast.type === "RangeExpression" ||
      ast.type === "ListExpression" ||
      ast.type === "NotExpression" ||
      ast.type === "InExpression" ||
      ast.type === "WildcardExpression"
    ) {
      return matchValue(value, ast, ctx);
    }

    // For comparison operators at top level (e.g. "> 1000", "< 50")
    if (ast.type === "ComparisonExpression") {
      // Substitute the input value for the left side
      const right = evaluate(ast.right, ctx);
      const numValue = Number(value);
      const numRight = Number(right);
      if (!isNaN(numValue) && !isNaN(numRight)) {
        switch (ast.operator) {
          case "=": return numValue === numRight;
          case "!=": return numValue !== numRight;
          case "<": return numValue < numRight;
          case "<=": return numValue <= numRight;
          case ">": return numValue > numRight;
          case ">=": return numValue >= numRight;
        }
      }
      return String(value) === String(right);
    }

    // For unary comparison expressions like "> 1000", "< 50"
    // These get parsed as: UnaryExpression or comparison with implicit left
    if (ast.type === "BinaryExpression" || ast.type === "UnaryExpression") {
      const result = evaluate(ast, ctx);
      // If it evaluates to a number, compare with input value
      if (typeof result === "number" && typeof value === "number") {
        return value === result;
      }
    }

    // Simple value — exact match
    const evaluated = evaluate(ast, ctx);

    // Boolean match
    if (typeof evaluated === "boolean") {
      if (typeof value === "boolean") return value === evaluated;
      return Boolean(value) === evaluated;
    }

    // Null match
    if (evaluated === null) return value === null || value === undefined;

    // Numeric match
    if (typeof evaluated === "number" && !isNaN(Number(value))) {
      return Number(value) === evaluated;
    }

    // String match
    return String(value) === String(evaluated);
  } catch {
    // Fallback: simple string comparison
    return String(value) === trimmed;
  }
}

/** Extract output values from a matched rule. */
function extractOutputs(
  rule: DecisionTableRule,
  table: DecisionTableDefinition,
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (let i = 0; i < table.outputs.length; i++) {
    const output = table.outputs[i];
    const cellExpr = rule.outputEntries[i] ?? "";
    result[output.name] = parseOutputValue(cellExpr, output.type);
  }
  return result;
}

/** Parse an output cell value into the appropriate type. */
function parseOutputValue(expr: string, type: string): unknown {
  const trimmed = expr.trim();
  if (!trimmed) return null;

  try {
    const tokens = tokenize(trimmed);
    const ast = parse(tokens);
    return evaluate(ast, {});
  } catch {
    // Fallback for plain strings
    if (type === "number") {
      const n = Number(trimmed);
      return isNaN(n) ? trimmed : n;
    }
    if (type === "boolean") {
      return trimmed.toLowerCase() === "true";
    }
    return trimmed;
  }
}

/** Apply hit policy to matched outputs. */
function applyHitPolicy(
  policy: HitPolicy,
  outputs: Record<string, unknown>[],
  matchedRules: { rule: DecisionTableRule; index: number }[],
): Record<string, unknown> | Record<string, unknown>[] {
  switch (policy) {
    case "U": // Unique — exactly one match expected
      return outputs[0] ?? {};

    case "F": // First — first match wins
      return outputs[0] ?? {};

    case "A": // Any — all matches must agree
      return outputs[0] ?? {};

    case "P": // Priority — first match by rule order (priority = definition order)
      return outputs[0] ?? {};

    case "C": // Collect — return all matches
      return outputs;

    case "R": // Rule Order — return all in definition order
      return outputs;

    default:
      return outputs[0] ?? {};
  }
}
