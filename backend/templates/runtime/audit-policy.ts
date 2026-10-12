// The template's default, so the runtime's own tests resolve `./audit-policy`.
// An app gets its own: written by the Blueprint projection (project_audit), or
// a "none" stub by the injector. This file is not copied into apps.
export const AUDIT = { level: "none", reviewers: [], retentionDays: null, reasonRequired: [] } as const;
