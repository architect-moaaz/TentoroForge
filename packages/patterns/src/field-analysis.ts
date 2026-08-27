/**
 * Field Analysis Heuristics — analyzes entity fields to inform pattern selection.
 *
 * These functions encode the design decisions a human would make when choosing
 * how to display and edit an entity: which fields go in the list, which get
 * badges, which group together in forms, etc.
 */

import type { EntitySpec, FieldSpec, FieldGroup, FieldType } from "./types.js";

// ---------------------------------------------------------------------------
// Field counting
// ---------------------------------------------------------------------------

/** Fields suitable for display in a table/list (excludes richtext, json, etc.) */
export function countDisplayableFields(entity: EntitySpec): number {
  return entity.fields.filter((f) => isDisplayable(f)).length;
}

/** Fields that can be edited in a form */
export function countEditableFields(entity: EntitySpec): number {
  return entity.fields.filter((f) => f.name !== "id" && f.name !== "createdAt" && f.name !== "updatedAt").length;
}

function isDisplayable(field: FieldSpec): boolean {
  const hidden: FieldType[] = ["richtext", "json", "file", "text"];
  return !hidden.includes(field.type) && field.name !== "id";
}

// ---------------------------------------------------------------------------
// Field finders
// ---------------------------------------------------------------------------

/** Find the first field that looks like a title/name (primary text identifier) */
export function findTitleField(entity: EntitySpec): FieldSpec | undefined {
  const titleNames = ["title", "name", "label", "subject", "heading", "displayName", "display_name"];
  for (const name of titleNames) {
    const f = entity.fields.find((f) => f.name.toLowerCase() === name.toLowerCase());
    if (f) return f;
  }
  // Fallback: first required string field
  return entity.fields.find((f) => f.type === "string" && f.required);
}

/** Find a status/stage enum field */
export function findStatusField(entity: EntitySpec): FieldSpec | undefined {
  const statusNames = ["status", "stage", "phase", "step", "state"];
  for (const name of statusNames) {
    const f = entity.fields.find(
      (f) => f.name.toLowerCase().includes(name) && f.type === "enum",
    );
    if (f) return f;
  }
  return undefined;
}

/** Find the primary date field */
export function findDateField(entity: EntitySpec): FieldSpec | undefined {
  const dateNames = ["dueDate", "due_date", "date", "scheduledAt", "eventDate", "startDate", "deadline"];
  for (const name of dateNames) {
    const f = entity.fields.find((f) => f.name.toLowerCase() === name.toLowerCase());
    if (f) return f;
  }
  // Fallback: first date/datetime field that isn't createdAt/updatedAt
  return entity.fields.find(
    (f) => (f.type === "date" || f.type === "datetime") &&
    f.name !== "createdAt" && f.name !== "updatedAt",
  );
}

/** Find an image or avatar field */
export function findImageField(entity: EntitySpec): FieldSpec | undefined {
  return entity.fields.find(
    (f) => f.type === "image" || f.type === "avatar" || f.isIdentityImage,
  );
}

/** Find a richtext or long text field */
export function findRichTextField(entity: EntitySpec): FieldSpec | undefined {
  return entity.fields.find((f) => f.type === "richtext" || f.type === "text");
}

/** Check if entity has an image/avatar field */
export function hasImageField(entity: EntitySpec): boolean {
  return findImageField(entity) !== undefined;
}

/** Check if entity has a richtext field */
export function hasRichTextField(entity: EntitySpec): boolean {
  return findRichTextField(entity) !== undefined;
}

/** Check if entity represents a person (has avatar + name-like fields) */
export function isPersonEntity(entity: EntitySpec): boolean {
  const personNames = ["user", "person", "member", "employee", "contact", "customer", "staff", "agent"];
  const nameMatch = personNames.some((n) => entity.name.toLowerCase().includes(n));
  const hasAvatar = entity.fields.some((f) => f.type === "avatar" || f.name === "avatar" || f.name === "profileImage");
  return nameMatch || hasAvatar;
}

/** Check if entity is temporal (primarily about events/activities) */
export function isTemporalEntity(entity: EntitySpec): boolean {
  const temporalNames = ["log", "event", "activity", "notification", "history", "audit", "changelog"];
  return temporalNames.some((n) => entity.name.toLowerCase().includes(n));
}

// ---------------------------------------------------------------------------
// Field ranking for list preview
// ---------------------------------------------------------------------------

/**
 * Select the best 3-4 fields for a compact list/card preview.
 * Priority: title > status > date > relation > other short fields
 */
export function rankFieldsForListPreview(entity: EntitySpec): FieldSpec[] {
  const titleField = findTitleField(entity);
  const statusField = findStatusField(entity);
  const dateField = findDateField(entity);

  const ranked: FieldSpec[] = [];

  // Always include title
  if (titleField) ranked.push(titleField);

  // Status is high-value for browse views
  if (statusField) ranked.push(statusField);

  // Date gives temporal context
  if (dateField) ranked.push(dateField);

  // Fill remaining slots with short displayable fields
  const used = new Set(ranked.map((f) => f.name));
  const remaining = entity.fields
    .filter((f) => !used.has(f.name) && isDisplayable(f) && isShortField(f))
    .slice(0, 4 - ranked.length);

  ranked.push(...remaining);

  return ranked.slice(0, 4);
}

/**
 * Select fields for a full table view.
 * Returns all displayable fields, ordered by importance.
 */
export function rankFieldsForTable(entity: EntitySpec): FieldSpec[] {
  const titleField = findTitleField(entity);
  const statusField = findStatusField(entity);
  const dateField = findDateField(entity);

  const priority: FieldSpec[] = [];
  const rest: FieldSpec[] = [];

  for (const field of entity.fields) {
    if (!isDisplayable(field)) continue;
    if (field === titleField || field === statusField || field === dateField) {
      priority.push(field);
    } else {
      rest.push(field);
    }
  }

  return [...priority, ...rest];
}

function isShortField(field: FieldSpec): boolean {
  const shortTypes: FieldType[] = ["string", "number", "boolean", "date", "datetime", "email", "enum", "relation"];
  return shortTypes.includes(field.type);
}

// ---------------------------------------------------------------------------
// Field grouping for sectioned forms
// ---------------------------------------------------------------------------

/**
 * Group fields into logical sections for form layout.
 * Uses prefix matching and semantic affinity.
 */
export function groupFieldsByAffinity(entity: EntitySpec): FieldGroup[] {
  const editable = entity.fields.filter(
    (f) => f.name !== "id" && f.name !== "createdAt" && f.name !== "updatedAt",
  );

  // Try prefix-based grouping first
  const prefixGroups = groupByPrefix(editable);
  if (prefixGroups.length >= 2) return prefixGroups;

  // Try semantic grouping
  const semanticGroups = groupBySemantic(editable);
  if (semanticGroups.length >= 2) return semanticGroups;

  // Fallback: sequential chunks of 4-5 fields
  return chunkFields(editable, 5);
}

function groupByPrefix(fields: FieldSpec[]): FieldGroup[] {
  const groups = new Map<string, FieldSpec[]>();

  for (const field of fields) {
    // Look for prefixes: address_street → "address", billing_name → "billing"
    const parts = field.name.split(/[_.]|(?=[A-Z])/);
    if (parts.length >= 2) {
      const prefix = parts[0].toLowerCase();
      if (!groups.has(prefix)) groups.set(prefix, []);
      groups.get(prefix)!.push(field);
    }
  }

  // Only keep groups with 2+ fields
  const result: FieldGroup[] = [];
  const grouped = new Set<string>();

  for (const [prefix, groupFields] of groups) {
    if (groupFields.length >= 2) {
      result.push({
        title: capitalize(prefix),
        fields: groupFields,
      });
      for (const f of groupFields) grouped.add(f.name);
    }
  }

  // Add ungrouped fields as "General"
  const ungrouped = fields.filter((f) => !grouped.has(f.name));
  if (ungrouped.length > 0) {
    result.unshift({ title: "General", fields: ungrouped });
  }

  return result;
}

function groupBySemantic(fields: FieldSpec[]): FieldGroup[] {
  const categories: Record<string, { match: (f: FieldSpec) => boolean; title: string }> = {
    identity: {
      title: "Profile",
      match: (f) => ["name", "email", "phone", "avatar", "bio", "title", "displayName"].some(
        (n) => f.name.toLowerCase().includes(n),
      ),
    },
    location: {
      title: "Address",
      match: (f) => ["street", "city", "state", "zip", "country", "address", "location", "lat", "lng"].some(
        (n) => f.name.toLowerCase().includes(n),
      ),
    },
    security: {
      title: "Security",
      match: (f) => ["password", "twoFactor", "two_factor", "mfa", "session", "token"].some(
        (n) => f.name.toLowerCase().includes(n),
      ),
    },
    preferences: {
      title: "Preferences",
      match: (f) => ["notify", "email_", "theme", "language", "timezone", "locale", "preference", "setting"].some(
        (n) => f.name.toLowerCase().includes(n),
      ) || f.type === "boolean",
    },
  };

  const groups: FieldGroup[] = [];
  const assigned = new Set<string>();

  for (const [, cat] of Object.entries(categories)) {
    const matches = fields.filter((f) => !assigned.has(f.name) && cat.match(f));
    if (matches.length >= 2) {
      groups.push({ title: cat.title, fields: matches });
      for (const f of matches) assigned.add(f.name);
    }
  }

  // Remaining → "Details"
  const remaining = fields.filter((f) => !assigned.has(f.name));
  if (remaining.length > 0) {
    groups.unshift({ title: "Details", fields: remaining });
  }

  return groups;
}

function chunkFields(fields: FieldSpec[], size: number): FieldGroup[] {
  const groups: FieldGroup[] = [];
  for (let i = 0; i < fields.length; i += size) {
    const chunk = fields.slice(i, i + size);
    groups.push({
      title: i === 0 ? "General" : `Section ${Math.floor(i / size) + 1}`,
      fields: chunk,
    });
  }
  return groups;
}

// ---------------------------------------------------------------------------
// Input type inference
// ---------------------------------------------------------------------------

/** Infer the best IR input node type for a field */
export function inferInputType(field: FieldSpec): string {
  switch (field.type) {
    case "string":
      if (field.name.toLowerCase().includes("email")) return "TextInput";
      if (field.name.toLowerCase().includes("url")) return "TextInput";
      if (field.name.toLowerCase().includes("phone") || field.name.toLowerCase().includes("tel")) return "TextInput";
      if (field.name.toLowerCase().includes("password")) return "TextInput";
      if (field.maxLength && field.maxLength > 200) return "TextArea";
      return "TextInput";
    case "text":
      return "TextArea";
    case "richtext":
      return "RichTextEditor";
    case "number":
      return "TextInput";
    case "boolean":
      return "Toggle";
    case "date":
    case "datetime":
      return "DatePicker";
    case "email":
      return "TextInput";
    case "url":
      return "TextInput";
    case "tel":
      return "TextInput";
    case "enum":
      if (field.values && field.values.length <= 4) return "RadioGroup";
      return "Select";
    case "image":
    case "avatar":
    case "file":
      return "FilePicker";
    case "relation":
      return "Select";
    case "string[]":
      return "TextInput"; // simplified
    default:
      return "TextInput";
  }
}

/** Infer the DataTable column render shorthand for a field */
export function inferColumnRender(field: FieldSpec): string | undefined {
  if (field.type === "enum") return "badge";
  if (field.type === "date" || field.type === "datetime") return "date:relative";
  if (field.type === "boolean") return "boolean";
  return undefined;
}

/** Infer the TextInput type prop for a field */
export function inferTextInputType(field: FieldSpec): string {
  if (field.type === "email" || field.name.toLowerCase().includes("email")) return "email";
  if (field.type === "url" || field.name.toLowerCase().includes("url")) return "url";
  if (field.type === "tel" || field.name.toLowerCase().includes("phone")) return "tel";
  if (field.type === "number") return "number";
  if (field.name.toLowerCase().includes("password")) return "password";
  return "text";
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Pluralize a simple English word */
export function pluralize(word: string): string {
  if (word.endsWith("s")) return word;
  if (word.endsWith("y") && !["ay", "ey", "oy", "uy"].some((s) => word.endsWith(s))) {
    return word.slice(0, -1) + "ies";
  }
  if (word.endsWith("ch") || word.endsWith("sh") || word.endsWith("x") || word.endsWith("z")) {
    return word + "es";
  }
  return word + "s";
}

/** Convert to URL-friendly slug */
export function slugify(word: string): string {
  return word
    .replace(/([A-Z])/g, "-$1")
    .toLowerCase()
    .replace(/^-/, "")
    .replace(/[^a-z0-9-]/g, "-")
    .replace(/-+/g, "-");
}

/** Capitalize each word for labels */
export function toLabel(fieldName: string): string {
  return fieldName
    .replace(/([A-Z])/g, " $1")
    .replace(/[_-]/g, " ")
    .trim()
    .split(" ")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
