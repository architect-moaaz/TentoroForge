// ---------------------------------------------------------------------------
// Field type intelligence for the Business Rules editor.
//
// Maps Drizzle column types (from the project's data model) to a small set of
// categories, then derives the *valid operators* and the right *value control*
// per category. This is what makes condition authoring type-accurate: a number
// field offers >, >=, between; a string field offers contains/starts_with; an
// enum field offers a value dropdown; a boolean offers true/false.
// ---------------------------------------------------------------------------

import type { ConditionOperator } from "@/types/rules";

export type FieldCategory =
  | "number"
  | "string"
  | "boolean"
  | "date"
  | "enum"
  | "json"
  | "other";

const NUMBER_TYPES = new Set([
  "serial", "integer", "int", "int4", "int8", "bigint", "smallint",
  "real", "doubleprecision", "double", "numeric", "decimal", "float", "number",
]);
const STRING_TYPES = new Set([
  "text", "varchar", "char", "uuid", "string", "inet", "cidr", "macaddr",
  "citext", "name",
]);
const BOOLEAN_TYPES = new Set(["boolean", "bool"]);
const DATE_TYPES = new Set([
  "timestamp", "timestamptz", "date", "time", "datetime", "interval",
]);
const JSON_TYPES = new Set(["json", "jsonb"]);

/**
 * Classify a Drizzle/SQL column type into a category. Pass `isEnum` when the
 * type names a known enum in the data model.
 */
export function fieldCategory(type: string | undefined, isEnum = false): FieldCategory {
  if (isEnum) return "enum";
  const t = (type ?? "").toLowerCase().replace(/\(.*\)$/, "").trim();
  if (NUMBER_TYPES.has(t)) return "number";
  if (STRING_TYPES.has(t)) return "string";
  if (BOOLEAN_TYPES.has(t)) return "boolean";
  if (DATE_TYPES.has(t)) return "date";
  if (JSON_TYPES.has(t)) return "json";
  return "other";
}

const ORDERED: ConditionOperator[] = [
  "equals", "not_equals", "gt", "gte", "lt", "lte",
  "in", "not_in", "contains", "starts_with", "ends_with",
  "matches_regex", "is_null", "is_not_null",
];

const OPERATORS_BY_CATEGORY: Record<FieldCategory, ConditionOperator[]> = {
  number: ["equals", "not_equals", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "is_not_null"],
  date: ["equals", "not_equals", "gt", "gte", "lt", "lte", "is_null", "is_not_null"],
  string: ["equals", "not_equals", "contains", "starts_with", "ends_with", "in", "not_in", "matches_regex", "is_null", "is_not_null"],
  boolean: ["equals", "not_equals", "is_null", "is_not_null"],
  enum: ["equals", "not_equals", "in", "not_in", "is_null", "is_not_null"],
  json: ["is_null", "is_not_null"],
  other: ORDERED, // unknown type -> don't restrict
};

export function operatorsForCategory(cat: FieldCategory): ConditionOperator[] {
  return OPERATORS_BY_CATEGORY[cat] ?? ORDERED;
}

/** What kind of value control to render for a (category, operator) pair. */
export type ValueControl = "none" | "list" | "enum" | "boolean" | "number" | "date" | "text";

const UNARY = new Set<ConditionOperator>(["is_null", "is_not_null"]);
const LIST_OPS = new Set<ConditionOperator>(["in", "not_in"]);

export function valueControl(cat: FieldCategory, op: ConditionOperator): ValueControl {
  if (UNARY.has(op)) return "none";
  if (LIST_OPS.has(op)) return "list"; // comma-separated; enum values still typed as text in a list
  switch (cat) {
    case "enum": return "enum";
    case "boolean": return "boolean";
    case "number": return "number";
    case "date": return "date";
    default: return "text";
  }
}

/** Per-field metadata the condition editor uses for type-aware authoring. */
export interface FieldMeta {
  name: string;
  type: string;
  category: FieldCategory;
  enumValues?: string[];
  label?: string;
}

/**
 * Build a field-name -> FieldMeta map for a model's columns.
 * `enumValuesForType` resolves a column type that names an enum to its values.
 */
export function buildFieldMeta(
  columns: Array<{ name: string; type: string }>,
  enumValuesForType?: (type: string | undefined) => string[] | null,
): Record<string, FieldMeta> {
  const out: Record<string, FieldMeta> = {};
  for (const c of columns) {
    const enumValues = enumValuesForType?.(c.type) ?? undefined;
    out[c.name] = {
      name: c.name,
      type: c.type,
      category: fieldCategory(c.type, !!enumValues),
      enumValues: enumValues ?? undefined,
    };
  }
  return out;
}
