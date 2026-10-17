// The app SDK (native) — what a form collects and checks, without React.
//
// THE `kind` VOCABULARY IS THE WEB'S (`WorkflowForm` in the web SDK, client.tsx)
// so a model that writes web forms writes these the same way:
//   text, textarea, email, tel, url, password, date, time, datetime, select,
//   multiselect, tags, number, checkbox, switch, image, file, location
// plus one the phone adds: `money` — a number held in MAJOR units (12.50) that
// the field shows with the app's currency.
//
// A web form leans on the browser to refuse an empty required field, a bad
// email, a date that is not a date. A phone has no such check, so it is here:
// `validateValue` per kind, `collectInput` for a whole form. The workflow still
// has the last word — its rules refuse what a form lets through — but a form
// that sends "2026-13-45" and gets "Something went wrong (422)" back is a worse
// form than one that says "Enter a real date".
//
// PURE — no react-native import.

import { isPoint } from "./geo";

export type FieldKind =
  | "text" | "textarea" | "email" | "tel" | "url" | "password"
  | "date" | "time" | "datetime"
  | "select" | "multiselect" | "tags"
  | "number" | "money"
  | "checkbox" | "switch"
  | "image" | "file" | "location";

export interface Option {
  label: string;
  value: string;
}

/** What validation needs to know about one field. A superset is fine: the
 *  form's own specs (label, help, placeholder, ...) are passed whole. */
export interface FieldRule {
  kind?: FieldKind;
  label?: string;
  options?: Option[];
  min?: number;
  max?: number;
  /** A fixed value (the record the screen is about, the decision a button stands for). */
  value?: unknown;
}

/** A spec with `value` is FIXED: sent as given, never drawn, never asked. */
export function isFixed(spec: FieldRule | undefined): spec is FieldRule & { value: unknown } {
  return !!spec && Object.prototype.hasOwnProperty.call(spec, "value");
}

/** Nothing entered: not set, an empty string, a blank string, an empty list. */
function isEmpty(value: unknown): boolean {
  if (value === undefined || value === null) return true;
  if (typeof value === "string") return value.trim() === "";
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

/** "12.5" -> 12.5, "1,5" -> 1.5 (a decimal comma: one or two digits after it),
 *  "1,234.50" -> 1234.5 (grouping: three), "" -> undefined, "abc" -> null. */
export function numberFromText(text: string): number | undefined | null {
  const t = text.trim();
  if (t === "") return undefined;
  const plain = /^-?\d+,\d{1,2}$/.test(t) ? t.replace(",", ".")
    : /^-?\d{1,3}(,\d{3})+(\.\d+)?$/.test(t) ? t.replace(/,/g, "")
    : t;
  const n = Number(plain);
  return Number.isFinite(n) ? n : null;
}

/** "2026-03-01 14:30" -> "2026-03-01T14:30" (the form's one datetime shape). */
export function normaliseDateTime(text: string): string {
  return text.trim().replace(/^(\d{4}-\d{2}-\d{2})[ T]+(\d{1,2}:\d{2})/, (_m, d: string, t: string) => `${d}T${t.padStart(5, "0")}`);
}

/** What the "Today" / "Now" button puts in a date, time or datetime field, in
 *  the device's own time zone. */
export function nowText(kind: "date" | "time" | "datetime", at: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  const date = `${at.getFullYear()}-${p(at.getMonth() + 1)}-${p(at.getDate())}`;
  const time = `${p(at.getHours())}:${p(at.getMinutes())}`;
  return kind === "date" ? date : kind === "time" ? time : `${date} ${time}`;
}

/** Is `text` a real calendar day in `YYYY-MM-DD`? */
function isIsoDate(text: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const probe = new Date(Date.UTC(y, mo - 1, d));
  return probe.getUTCFullYear() === y && probe.getUTCMonth() === mo - 1 && probe.getUTCDate() === d;
}

function isTime(text: string): boolean {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(text);
}

/** The sentence a field says when its value is wrong, or null when it is fine.
 *  An EMPTY value is `required`'s business only: an optional empty field is fine. */
export function validateValue(rule: FieldRule, value: unknown, required: boolean): string | null {
  const kind: FieldKind = rule.kind ?? "text";
  const label = rule.label ?? "This field";
  if (kind === "checkbox" || kind === "switch") return null; // off is an answer
  if (isEmpty(value)) return required ? `${label} is required.` : null;
  switch (kind) {
    case "number":
    case "money": {
      if (typeof value !== "number" || !Number.isFinite(value)) return `${label} must be a number.`;
      if (rule.min !== undefined && value < rule.min) return `${label} must be at least ${rule.min}.`;
      if (rule.max !== undefined && value > rule.max) return `${label} must be at most ${rule.max}.`;
      return null;
    }
    case "email":
      return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value).trim()) ? null : `${label} must be an email address.`;
    case "url":
      return /^https?:\/\/\S+$/i.test(String(value).trim()) ? null : `${label} must be a web address starting with http.`;
    case "tel":
      return /^\+?[\d\s().-]{5,}$/.test(String(value).trim()) ? null : `${label} must be a phone number.`;
    case "date":
      return isIsoDate(String(value)) ? null : `${label} must be a date, like 2026-03-01.`;
    case "time":
      return isTime(String(value)) ? null : `${label} must be a time, like 14:30.`;
    case "datetime": {
      const [d, t] = normaliseDateTime(String(value)).split("T");
      return d && t && isIsoDate(d) && isTime(t) ? null : `${label} must be a date and time, like 2026-03-01 14:30.`;
    }
    case "select": {
      const offered = rule.options;
      return !offered || offered.some((o) => o.value === value) ? null : `${label}: choose one of the options.`;
    }
    case "multiselect": {
      const offered = rule.options;
      const all = Array.isArray(value) ? (value as unknown[]) : [];
      return !offered || all.every((v) => offered.some((o) => o.value === v)) ? null : `${label}: choose from the options.`;
    }
    case "location":
      return isPoint(value) ? null : `${label} needs a location.`;
    default:
      return null;
  }
}

export interface Collected {
  /** What the workflow is run with: fixed values and every field that has one. */
  input: Record<string, unknown>;
  /** One sentence per field that is wrong, by field name. */
  errors: Record<string, string>;
}

/** A form's values, checked and gathered the way the web gathers them: a fixed
 *  value is sent as given; a field left empty is NOT sent (the workflow's own
 *  default and rules apply); a datetime is normalised. `names` restricts the
 *  CHECK to some fields (the step a stepped form is on); the input is whole. */
export function collectInput(
  specs: Record<string, FieldRule | undefined>,
  values: Record<string, unknown>,
  required: readonly string[] | ReadonlySet<string>,
  names?: readonly string[],
): Collected {
  const need = required instanceof Set ? required : new Set(required as readonly string[]);
  const input: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const [name, spec] of Object.entries(specs)) {
    if (!spec) continue;
    if (isFixed(spec)) { input[name] = spec.value; continue; }
    const raw = values[name];
    if (!names || names.includes(name)) {
      const problem = validateValue(spec, raw, need.has(name));
      if (problem) errors[name] = problem;
    }
    if (raw === undefined || raw === "") continue;
    input[name] = spec.kind === "datetime" && typeof raw === "string" ? normaliseDateTime(raw) : raw;
  }
  return { input, errors };
}
