/** FEEL-lite expression engine — barrel export. */

export { tokenize, TokenType, type Token } from "./tokenizer";
export { parse, ParseError } from "./parser";
export type {
  ASTNode,
  NumberLiteral,
  StringLiteral,
  BooleanLiteral,
  NullLiteral,
  Identifier,
  UnaryExpression,
  BinaryExpression,
  ComparisonExpression,
  LogicalExpression,
  RangeExpression,
  ListExpression,
  InExpression,
  NotExpression,
  IfExpression,
  FunctionCall,
  MemberExpression,
  WildcardExpression,
  BetweenExpression,
} from "./ast";
export { evaluate, matchValue, type Context } from "./evaluator";
export {
  validateExpression,
  type VariableSchema,
  type ValidationIssue,
  type ValidationResult,
} from "./validator";

// ── Convenience functions ──────────────────────────────

import { tokenize } from "./tokenizer";
import { parse } from "./parser";
import { evaluate, type Context } from "./evaluator";
import { validateExpression, type VariableSchema } from "./validator";

/** Parse and evaluate a FEEL-lite expression against a context. */
export function evaluateExpression(expr: string, ctx: Context = {}): unknown {
  if (!expr || !expr.trim()) return null;
  const tokens = tokenize(expr);
  const ast = parse(tokens);
  return evaluate(ast, ctx);
}

/** Validate a FEEL-lite expression with optional variable schema. */
export function validate(expr: string, variables?: VariableSchema[]) {
  return validateExpression(expr, variables);
}
