/**
 * Control-type-aware hydration for edit-form default values.
 *
 * Root cause this addresses: edit-form default values come from an API record
 * as raw DB shapes (ISO date strings, UUID strings for FKs, jsonb objects for
 * config columns, string booleans from postgres, file-ref shapes for uploads).
 * Each control (Input/Select/DatePicker/Checkbox/FileUpload/KeyValueInput/...)
 * expects a specific value shape; passing the raw record straight into
 * react-hook-form's `defaultValues` leaves several fields blank because the
 * shape doesn't match. That's what produces B-021.6 ("Edit screen has missing
 * pre-filled data"): the DatePicker gets an ISO timestamp instead of
 * `YYYY-MM-DD` and renders empty, the Checkbox gets `"true"` instead of `true`
 * and renders unchecked, the KeyValueInput gets `{k:v}` instead of `[{k,v}]`
 * and renders empty, etc.
 *
 * Fix: a single hydration table keyed by field `kind` that transforms each raw
 * value into the shape its control expects. Pure, deterministic, additive —
 * safe to call on every edit-form render.
 *
 * Behavior:
 *   * `hydrateFieldValue(rawValue, field)` returns the shaped value for the
 *     given control kind. Unknown kinds pass through unchanged.
 *   * `hydrateFormValues(record, fields)` builds a full defaults dict by
 *     walking the field spec list. Missing keys stay missing (react-hook-form
 *     falls back to its normal defaults).
 *   * Both functions are idempotent — running twice is identical.
 */

// Minimal field-spec shape this module cares about — we don't import the
// Form's FieldSpec union so this util stays library-wide and reusable.
export type HydrationFieldSpec = {
  kind?: string;
  name: string;
  fields?: HydrationFieldSpec[]; // nested (for object kind)
  valueType?: "text" | "number" | "boolean"; // keyvalue's value type hint
};

// --------------------------------------------------------------------------
// Per-control hydrators                                                     //
// --------------------------------------------------------------------------

function hydrateDate(v: unknown): string {
  if (v == null) return "";
  const s = String(v);
  // ISO timestamp → date-only. Native <input type="date"> requires YYYY-MM-DD.
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) return s.slice(0, 10);
  // Already YYYY-MM-DD.
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  // Try Date parsing as a last resort.
  const d = new Date(s);
  if (!isNaN(d.getTime())) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  return "";
}

function hydrateDateTime(v: unknown): string {
  if (v == null) return "";
  const s = String(v);
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s)) return s.slice(0, 16);
  const d = new Date(s);
  if (!isNaN(d.getTime())) {
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  return "";
}

function hydrateNumber(v: unknown): number | "" {
  if (v == null || v === "") return "";
  const n = Number(v);
  return Number.isFinite(n) ? n : "";
}

function hydrateBoolean(v: unknown): boolean {
  if (typeof v === "boolean") return v;
  if (typeof v === "number") return v !== 0;
  if (typeof v === "string") {
    const s = v.toLowerCase().trim();
    return s === "true" || s === "1" || s === "yes" || s === "on" || s === "t";
  }
  return Boolean(v);
}

function hydrateSelect(v: unknown): string {
  // Native <select> requires a string value. UUID FKs and enum ids arrive as
  // strings already; numbers coerce cleanly.
  if (v == null) return "";
  if (typeof v === "object") {
    // Some FK responses arrive as { id, ... } — pick .id if present.
    const asRec = v as { id?: unknown; value?: unknown };
    if (asRec.id != null) return String(asRec.id);
    if (asRec.value != null) return String(asRec.value);
    return "";
  }
  return String(v);
}

function hydrateFileUpload(v: unknown): string {
  // FileUpload's hidden input carries the file id (single) or a JSON array
  // (multiple). Accept the storage shapes the server actually returns.
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "object") {
    const asRec = v as { id?: unknown; url?: unknown };
    if (asRec.id != null) return String(asRec.id);
    if (asRec.url != null) return String(asRec.url);
  }
  if (Array.isArray(v)) return JSON.stringify(v);
  return "";
}

function hydrateKeyValue(v: unknown): Array<{ key: string; value: unknown }> {
  // KeyValueInput expects an array of {key, value} rows; jsonb columns arrive
  // as a plain object. Empty / null / non-object → [].
  if (v == null) return [];
  if (Array.isArray(v)) return v as Array<{ key: string; value: unknown }>;
  if (typeof v === "string") {
    try {
      const parsed = JSON.parse(v);
      return hydrateKeyValue(parsed);
    } catch {
      return [];
    }
  }
  if (typeof v === "object") {
    return Object.entries(v as Record<string, unknown>).map(([key, value]) => ({ key, value }));
  }
  return [];
}

function hydrateObject(v: unknown, fields: HydrationFieldSpec[] | undefined): Record<string, unknown> {
  // Nested typed object — recurse into each sub-field so the same hydration
  // rules apply at every depth.
  const src = (v != null && typeof v === "object" && !Array.isArray(v)) ? (v as Record<string, unknown>) : {};
  if (!fields || !fields.length) return src;
  const out: Record<string, unknown> = {};
  for (const sub of fields) {
    if (!sub || !sub.name) continue;
    out[sub.name] = hydrateFieldValue(src[sub.name], sub);
  }
  return out;
}

// --------------------------------------------------------------------------
// Public API                                                                //
// --------------------------------------------------------------------------

export function hydrateFieldValue(rawValue: unknown, field: HydrationFieldSpec): unknown {
  const kind = (field.kind || "").toLowerCase();
  switch (kind) {
    case "date":
      return hydrateDate(rawValue);
    case "datetime":
    case "datetime-local":
      return hydrateDateTime(rawValue);
    case "number":
      return hydrateNumber(rawValue);
    case "checkbox":
    case "switch":
    case "boolean":
      return hydrateBoolean(rawValue);
    case "select":
    case "radio":
      return hydrateSelect(rawValue);
    case "file":
    case "fileupload":
    case "upload":
      return hydrateFileUpload(rawValue);
    case "keyvalue":
      return hydrateKeyValue(rawValue);
    case "object":
      return hydrateObject(rawValue, field.fields);
    case "textarea":
    case "text":
    case "email":
    case "":
    default:
      // Strings, unknown kinds — coerce null/undefined to empty string so the
      // control renders empty instead of blank-and-uncontrolled.
      if (rawValue == null) return "";
      return typeof rawValue === "object" ? JSON.stringify(rawValue) : rawValue;
  }
}

/**
 * Build a react-hook-form `defaultValues` dict from a raw record and the
 * form's field specs. Idempotent, side-effect-free.
 */
export function hydrateFormValues(
  record: Record<string, unknown> | null | undefined,
  fields: HydrationFieldSpec[] | undefined,
): Record<string, unknown> {
  if (!record || !fields) return record ?? {};
  const out: Record<string, unknown> = { ...record };
  for (const f of fields) {
    if (!f || !f.name) continue;
    out[f.name] = hydrateFieldValue(record[f.name], f);
  }
  return out;
}
