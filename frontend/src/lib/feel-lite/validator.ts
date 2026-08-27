/** FEEL-lite static analysis — type checking, unknown variables, syntax errors. */

import { tokenize } from "./tokenizer";
import { parse, ParseError } from "./parser";
import type { ASTNode } from "./ast";

export interface VariableSchema {
  name: string;
  type: "string" | "number" | "boolean" | "date" | "any";
  label?: string;
}

export interface ValidationIssue {
  severity: "error" | "warning" | "info";
  message: string;
  start?: number;
  end?: number;
}

export interface ValidationResult {
  valid: boolean;
  issues: ValidationIssue[];
  variables: string[];
  functions: string[];
}

const KNOWN_FUNCTIONS = new Set([
  "sum", "count", "min", "max", "avg",
  "abs", "floor", "ceiling", "round",
  "contains", "starts with", "ends with", "starts_with", "ends_with", "matches",
  "string", "number", "date", "now", "duration",
]);

export function validateExpression(
  expr: string,
  availableVariables?: VariableSchema[],
): ValidationResult {
  const issues: ValidationIssue[] = [];
  const referencedVars = new Set<string>();
  const referencedFuncs = new Set<string>();

  if (!expr || !expr.trim()) {
    return { valid: true, issues: [], variables: [], functions: [] };
  }

  // Step 1: Tokenize
  let tokens;
  try {
    tokens = tokenize(expr);
  } catch (e) {
    issues.push({
      severity: "error",
      message: `Tokenization error: ${e instanceof Error ? e.message : String(e)}`,
    });
    return { valid: false, issues, variables: [], functions: [] };
  }

  // Step 2: Parse
  let ast: ASTNode;
  try {
    ast = parse(tokens);
  } catch (e) {
    if (e instanceof ParseError) {
      issues.push({
        severity: "error",
        message: e.message,
        start: e.position,
      });
    } else {
      issues.push({
        severity: "error",
        message: `Parse error: ${e instanceof Error ? e.message : String(e)}`,
      });
    }
    return { valid: false, issues, variables: [], functions: [] };
  }

  // Step 3: Walk AST for analysis
  const varSchemaMap = new Map<string, VariableSchema>();
  if (availableVariables) {
    for (const v of availableVariables) {
      varSchemaMap.set(v.name, v);
    }
  }

  function walk(node: ASTNode): void {
    switch (node.type) {
      case "Identifier":
        referencedVars.add(node.name);
        if (availableVariables && !resolveVariable(node.name, varSchemaMap)) {
          issues.push({
            severity: "warning",
            message: `Unknown variable: "${node.name}"`,
          });
        }
        break;

      case "MemberExpression":
        walk(node.object);
        break;

      case "FunctionCall":
        referencedFuncs.add(node.name);
        if (!KNOWN_FUNCTIONS.has(node.name)) {
          issues.push({
            severity: "warning",
            message: `Unknown function: "${node.name}"`,
          });
        }
        for (const arg of node.args) walk(arg);
        break;

      case "BinaryExpression":
        walk(node.left);
        walk(node.right);
        break;

      case "ComparisonExpression":
        walk(node.left);
        walk(node.right);
        break;

      case "LogicalExpression":
        walk(node.left);
        walk(node.right);
        break;

      case "UnaryExpression":
        walk(node.operand);
        break;

      case "NotExpression":
        walk(node.operand);
        break;

      case "IfExpression":
        walk(node.condition);
        walk(node.thenBranch);
        walk(node.elseBranch);
        break;

      case "InExpression":
        walk(node.value);
        walk(node.list);
        break;

      case "BetweenExpression":
        walk(node.value);
        walk(node.low);
        walk(node.high);
        break;

      case "RangeExpression":
        walk(node.start);
        walk(node.end);
        break;

      case "ListExpression":
        for (const el of node.elements) walk(el);
        break;

      // Literals and wildcards don't need analysis
      case "NumberLiteral":
      case "StringLiteral":
      case "BooleanLiteral":
      case "NullLiteral":
      case "WildcardExpression":
        break;
    }
  }

  walk(ast);

  return {
    valid: issues.filter((i) => i.severity === "error").length === 0,
    issues,
    variables: [...referencedVars],
    functions: [...referencedFuncs],
  };
}

function resolveVariable(
  name: string,
  schema: Map<string, VariableSchema>,
): boolean {
  // Check exact match
  if (schema.has(name)) return true;

  // Check parent path: "customer.age" → check if "customer" exists
  const dotIdx = name.indexOf(".");
  if (dotIdx !== -1) {
    const root = name.slice(0, dotIdx);
    if (schema.has(root)) return true;
  }

  return false;
}
