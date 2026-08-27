import type { WorkflowDefinition } from "@/types/workflow";

export interface FieldSpec {
  name: string;
  type: "string" | "number" | "boolean" | "object" | "array" | "date";
  required: boolean;
  defaultValue: unknown;
  description: string | undefined;
}

export function extractTriggerFields(def: WorkflowDefinition): FieldSpec[] {
  const vars = def.processVariables ?? [];
  return vars.map((v) => ({
    name: v.name,
    type: v.type,
    required: !!v.required,
    defaultValue: v.defaultValue,
    description: v.description,
  }));
}

function coerce(type: FieldSpec["type"], raw: unknown): unknown {
  if (type === "number") {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw; // keep bad input as-is rather than emit NaN
  }
  if (type === "boolean") return raw === true || raw === "true";
  if (type === "object" || type === "array") {
    if (typeof raw !== "string") return raw;
    try {
      return JSON.parse(raw);
    } catch {
      return raw; // leave malformed JSON for the UI to surface
    }
  }
  // "string" | "date" → passthrough (no client-side date coercion needed)
  return raw;
}

/** Build the `variables` payload: coerce by type, drop empty optionals, apply defaults. */
export function coerceTriggerValues(
  fields: FieldSpec[],
  raw: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = raw[f.name];
    const isEmpty = v === undefined || v === null || v === "";
    if (isEmpty) {
      if (f.defaultValue !== undefined) out[f.name] = f.defaultValue;
      continue;
    }
    out[f.name] = coerce(f.type, v);
  }
  return out;
}
