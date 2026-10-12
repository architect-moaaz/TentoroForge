// The template's default, so the runtime's own tests resolve
// `./sensitive-columns`. An app gets its own, written by the Blueprint
// projection (project_sensitive_columns). This file is not copied into apps.
export type MaskKind = "last4" | "email" | "phone" | "full";
export interface SensitiveColumnSpec { mask: MaskKind; readers: string[] }
export const SENSITIVE_COLUMNS: Record<string, Record<string, SensitiveColumnSpec>> = {};
export function sensitiveColumnsFor(entity: string): Record<string, SensitiveColumnSpec> {
  return SENSITIVE_COLUMNS[entity] ?? SENSITIVE_COLUMNS[String(entity).toLowerCase()] ?? {};
}
