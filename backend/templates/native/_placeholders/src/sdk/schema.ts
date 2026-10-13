// PLACEHOLDER of the generated `src/sdk/schema.ts` — not copied into apps. It
// has the exports (and the shape of each) the projector's real file has, so the
// template typechecks standalone. The real one is `emit_schema` in
// services/blueprint/app_sdk.py: the same file the web app gets.

/** Task — a sample entity. */
export interface Task {
  id: string;
  title: string;
  status: "open" | "done";
  amount: number | null;
  dueDate: string | null;
  place: { lat: number; lng: number } | null;
  photo: string | null;
}

/** Every entity, by the name the SDK's reads take. */
export interface Entities {
  "Task": Task;
}

export type EntityName = keyof Entities & string;

/** The numeric fields of an entity — what `total` and `series` can add up. */
export type NumericField<E extends EntityName> = {
  [K in keyof Entities[E]]-?: NonNullable<Entities[E][K]> extends number ? K : never;
}[keyof Entities[E]] & string;

/** The columns the SDK returns for each entity — exactly the typed ones. */
export const READABLE_FIELDS: Record<string, readonly string[]> = {
  "Task": ["id", "title", "status", "amount", "dueDate", "place", "photo"],
};

/** Columns the driver returns as strings that the SDK hands over as numbers. */
export const NUMERIC_FIELDS: Record<string, readonly string[]> = {
  "Task": ["amount"],
};

/** The entity each login IS; `never` when there is none. */
export type AccountEntity = never;

/** The display label of each entity's records. */
export const LABEL_FIELD: Record<string, string> = {
  "Task": "title",
};
