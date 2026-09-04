// ---------------------------------------------------------------------------
// Compile a visual ConditionExpression tree (from the rules ConditionBuilder)
// into a FEEL-lite string that @/lib/feel-lite `evaluateExpression` can run.
//
// This is the bridge between the editor's structured condition representation
// and the runtime's expression language — the same string is used by the live
// playground here and (later) by the generated app's request-time rules engine.
//
// When a `FieldTypeMap` is supplied (derived from the project's data model),
// values are encoded by the field's type — a string/enum/date field's value is
// always quoted (so "01234" or "gold" don't get mis-parsed as numbers), while
// number/boolean fields stay bare. Without it, values are auto-detected.
// ---------------------------------------------------------------------------

import type {
  ConditionExpression,
  ConditionGroup,
  ConditionNode,
  ConditionOperator,
} from "@/types/rules";
import type { FieldCategory } from "./field-types";

export type FieldTypeMap = Record<string, FieldCategory>;

function isGroup(expr: ConditionExpression): expr is ConditionGroup {
  return "logic" in expr;
}

function quote(v: string): string {
  return `"${v.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

function isNumericLiteral(v: string): boolean {
  return /^-?\d+(\.\d+)?$/.test(v);
}

/** Untyped auto-detect encoding (no data model available). */
function feelValueAuto(raw: string): string {
  const v = (raw ?? "").trim();
  if (v === "") return '""';
  if (v === "true" || v === "false" || v === "null") return v;
  if (isNumericLiteral(v)) return v;
  return quote(v);
}

/** Type-aware encoding using the field's category. */
function feelValueTyped(raw: string, cat: FieldCategory): string {
  const v = (raw ?? "").trim();
  if (v === "null") return "null";
  // Empty value -> empty string for every type. Never inject a bare 0 for number
  // fields (that would silently turn a blank box into "field = 0").
  if (v === "") return '""';
  switch (cat) {
    case "number":
      return isNumericLiteral(v) ? v : quote(v);
    case "boolean":
      return v === "true" || v === "false" ? v : quote(v);
    case "string":
    case "enum":
    case "date":
      return quote(v); // always quote — never coerce "01234"/"gold" to a number
    case "json":
    case "other":
    default:
      return feelValueAuto(v);
  }
}

/**
 * `user.id` is the acting user, not the eight-character string "user.id".
 *
 * Every other value the builder collects is a literal, so the encoders quote
 * it. That made the one comparison an access rule most needs — this row
 * belongs to me — impossible to express: it compiled to
 * `ownerId = "user.id"`, which matches nothing, silently, forever.
 *
 * Emitted bare so it stays an identifier. The FEEL evaluator already resolves
 * dotted names against the context it is given, and both consumers put the
 * acting user there: evaluateRuleSet passes `{...entity, user}`, and the data
 * engine's row-access compiler reads `user.<field>` off the session. Only the
 * `user.` prefix is passed through — a row rule compiles to a predicate over
 * ONE table, so letting `order.total` through here would move a failure the
 * author could see now to a read that returns nothing later.
 */
const USER_REF = /^user\.[A-Za-z_][A-Za-z0-9_]*$/;

function encodeValue(raw: string, cat?: FieldCategory): string {
  const v = (raw ?? "").trim();
  if (USER_REF.test(v)) return v;
  return cat ? feelValueTyped(raw, cat) : feelValueAuto(raw);
}

/** Encode a comma-separated raw value into a FEEL list: a, b, c -> [a, b, c]. */
function feelList(raw: string, cat?: FieldCategory): string {
  const items = (raw ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    .map((s) => encodeValue(s, cat));
  return `[${items.join(", ")}]`;
}

function feelField(field: string): string {
  return (field || "").trim() || "null";
}

function compileNode(node: ConditionNode, types?: FieldTypeMap): string {
  const f = feelField(node.field);
  const cat = types?.[node.field];
  const op: ConditionOperator = node.operator;
  switch (op) {
    case "equals":
      return `${f} = ${encodeValue(node.value, cat)}`;
    case "not_equals":
      return `${f} != ${encodeValue(node.value, cat)}`;
    case "gt":
      return `${f} > ${encodeValue(node.value, cat)}`;
    case "gte":
      return `${f} >= ${encodeValue(node.value, cat)}`;
    case "lt":
      return `${f} < ${encodeValue(node.value, cat)}`;
    case "lte":
      return `${f} <= ${encodeValue(node.value, cat)}`;
    case "in":
      return `${f} in ${feelList(node.value, cat)}`;
    case "not_in":
      return `not(${f} in ${feelList(node.value, cat)})`;
    case "is_null":
      return `${f} = null`;
    case "is_not_null":
      return `${f} != null`;
    case "matches_regex":
      return `matches(${f}, ${encodeValue(node.value, cat)})`;
    case "contains":
      return `contains(${f}, ${encodeValue(node.value, cat)})`;
    case "starts_with":
      // Underscore form: parses as a normal function call in BOTH the frontend
      // and backend FEEL parsers. The space form ("starts with(...)") only
      // parses on the frontend and silently fails on the backend runtime.
      return `starts_with(${f}, ${encodeValue(node.value, cat)})`;
    case "ends_with":
      return `ends_with(${f}, ${encodeValue(node.value, cat)})`;
    default:
      return "true";
  }
}

function compileGroup(group: ConditionGroup, types?: FieldTypeMap): string {
  const parts = group.conditions
    .map((c) => (isGroup(c) ? compileGroup(c, types) : compileNode(c, types)))
    .filter((s) => s && s.length > 0);

  if (parts.length === 0) return "true";

  if (group.logic === "NOT") {
    const inner = parts.length === 1 ? parts[0] : parts.join(" and ");
    return `not(${inner})`;
  }

  const joiner = group.logic === "OR" ? " or " : " and ";
  if (parts.length === 1) return parts[0];
  return `(${parts.join(joiner)})`;
}

/**
 * Compile a condition tree to a FEEL-lite expression string.
 * Returns "true" for an empty/absent condition (rule always fires).
 * Pass `types` (field -> category) to encode values by their data-model type.
 */
export function conditionToFeel(
  expr: ConditionExpression | null | undefined,
  types?: FieldTypeMap,
): string {
  if (!expr) return "true";
  return isGroup(expr) ? compileGroup(expr, types) : compileNode(expr, types);
}
