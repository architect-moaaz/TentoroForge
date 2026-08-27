import type { SmartFieldConfig } from "./ai-features";

export interface ColumnModel {
  name: string;
  type: string;
  primaryKey?: boolean;
  nullable?: boolean;
  unique?: boolean;
  default?: string;
  references?: {
    table: string;
    column: string;
  };
  smart?: SmartFieldConfig;
}

export interface RelationModel {
  type: "one-to-one" | "one-to-many" | "many-to-many";
  target: string;
  foreignKey: string;
}

export interface IndexModel {
  name?: string;
  columns: string[];
  unique?: boolean;
}

export interface EnumModel {
  name: string;
  values: string[];
}

export interface TableModel {
  name: string;
  columns: ColumnModel[];
  relations?: RelationModel[];
  indexes?: IndexModel[];
}

export interface DatabaseModel {
  tables: TableModel[];
  enums?: EnumModel[];
}

export interface ApiRoute {
  method: string;
  path: string;
  description: string;
}

export interface PageModel {
  path: string;
  component: string;
  description: string;
}

export interface ComponentModel {
  name: string;
  file: string;
  description: string;
}

export interface AppModelRules {
  validation?: number;
  access?: number;
  business?: number;
  computed?: number;
  state_machine?: number;
  trigger?: number;
}

export interface AppModel {
  name: string;
  description: string;
  database: DatabaseModel;
  api: {
    routes: ApiRoute[];
  };
  pages: PageModel[];
  components: ComponentModel[];
  rules?: AppModelRules;
}

/**
 * Drizzle column types for the type picker in field editors.
 */
export const DRIZZLE_COLUMN_TYPES = [
  "serial",
  "integer",
  "bigint",
  "smallint",
  "boolean",
  "text",
  "varchar",
  "char",
  "uuid",
  "timestamp",
  "date",
  "time",
  "json",
  "jsonb",
  "real",
  "doublePrecision",
  "numeric",
  "decimal",
  "bytea",
  "interval",
  "point",
  "line",
  "inet",
  "cidr",
  "macaddr",
  "tsvector",
  "tsquery",
] as const;

export type DrizzleColumnType = (typeof DRIZZLE_COLUMN_TYPES)[number];

/**
 * Actions that the instruction builder can convert to natural language.
 */
export type DataEditorAction =
  | { type: "add_model"; name: string; fields: { name: string; type: string; primaryKey?: boolean; nullable?: boolean; unique?: boolean }[] }
  | { type: "delete_model"; name: string }
  | { type: "add_field"; table: string; field: { name: string; type: string; nullable?: boolean; unique?: boolean; default?: string; references?: { table: string; column: string }; smart?: SmartFieldConfig } }
  | { type: "edit_field"; table: string; oldName: string; field: { name: string; type: string; nullable?: boolean; unique?: boolean; default?: string; smart?: SmartFieldConfig } }
  | { type: "delete_field"; table: string; fieldName: string }
  | { type: "add_relation"; source: string; target: string; relationType: "one-to-one" | "one-to-many" | "many-to-many"; foreignKey?: string }
  | { type: "delete_relation"; source: string; target: string; foreignKey: string }
  | { type: "add_enum"; name: string; values: string[] }
  | { type: "edit_enum"; name: string; values: string[] }
  | { type: "add_index"; table: string; columns: string[]; unique?: boolean };
