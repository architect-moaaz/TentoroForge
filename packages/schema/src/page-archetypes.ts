/**
 * Page archetype taxonomy.
 *
 * Beyond the v1 list/detail/form/dashboard/settings, this expands to
 * patterns that real enterprise + SaaS apps use:
 *
 *   workspace     list + inspector pane + filter bar (Linear / Notion-tier)
 *   console       KPI grid + chart + activity feed (Stripe / Workday-tier)
 *   inspector     master/detail/sub-detail nesting (any register)
 *   wizard        multi-step form with progress indicator (Workday onboarding)
 *   audit-log     timeline + filters + drill-in (compliance / HR review)
 *   report        filter bar + chart + table + export (BI / analytics)
 */
export const PAGE_ARCHETYPES = [
  // Originals (v1)
  "list", "detail", "form", "dashboard", "settings", "generic",
  // New (Wave 5)
  "workspace", "console", "inspector", "wizard", "audit-log", "report",
] as const;

export type PageArchetype = typeof PAGE_ARCHETYPES[number];

export const ARCHETYPE_DESCRIPTIONS: Record<PageArchetype, string> = {
  list:        "index/list page for browsing many records, with sorting + filters",
  detail:      "record-detail page showing one item's full information",
  form:        "create/edit form with proper validation feedback",
  dashboard:   "overview with KPI tiles, recent activity, status",
  settings:    "settings/profile page with grouped configuration controls",
  generic:     "uncategorised — falls back to default treatment",
  workspace:   "list + inspector pane + filter bar (Linear-style)",
  console:     "KPI grid + chart + activity feed (operations dashboard)",
  inspector:   "master/detail/sub-detail nested view",
  wizard:      "multi-step form with progress + save-draft + back nav",
  "audit-log": "timeline + filters + drill-in for compliance / history review",
  report:      "filter bar + chart + table + export for BI / analytics",
};
