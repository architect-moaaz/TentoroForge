"""schema_prompt — builds the LLM prompt for schema generation.

The prompt is composed of:
  - App context (description, entity, page-type)
  - Domain & design rationale (from design-spec.json)
  - Available design tokens (auto-generated from defaultTokens)
  - Available components (the library descriptor)
  - Page archetype + gold-standard example
  - Per-entity context (fields, relations, workflows)

The token-paths list is auto-generated from defaultTokens at prompt-build
time so the prompt and the validator share a single source of truth — no
drift possible.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import FIDELITY_MODE_ENABLED, REFERENCE_GROUNDING_ENABLED
from services.cta_defaults import defaults_for_register
from services.page_type import infer_page_type
from services.reference_bank import load_exemplars, render_exemplars_block
from services.schema_rules import RULES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rules-as-data (Task 20) — each Rule in services.schema_rules carries body +
# example_snippet + applies_when, and _emit_rules_block emits them one after
# another so the LLM sees each binding rule inline with a correct example.
#
# SCHEMA_RULES_DISABLED (comma-separated list of rule names) lets A/B
# experiments switch individual rules off without code changes, e.g.:
#   SCHEMA_RULES_DISABLED=metric-tile-for-stats,hero-on-list
# ---------------------------------------------------------------------------
_RULES_DISABLED = {
    name.strip()
    for name in (os.getenv("SCHEMA_RULES_DISABLED") or "").split(",")
    if name.strip()
}


def _emit_rules_block(entity: dict, page_type: str) -> str:
    """Emit each applicable Rule from services.schema_rules as a markdown
    block of `## Rule: <name>` + body + fenced JSON example.

    The block is intentionally APPENDED alongside (not in place of) the
    existing monolithic rule section in build_schema_prompt — the old text
    stays as a safety net until the proximity-trained structure proves
    itself.
    """
    blocks: list[str] = []
    for rule in RULES:
        if rule.name in _RULES_DISABLED:
            continue
        if not rule.applies_when(entity, page_type):
            continue
        blocks.append(
            f"## Rule: {rule.name}\n\n"
            f"{rule.body}\n\n"
            f"Example:\n```json\n{rule.example_snippet}\n```\n"
        )
    return "\n".join(blocks)

# ---------------------------------------------------------------------------
# Hierarchy guidance — injected into the prompt after component contracts and
# before reference exemplars so the LLM has contracts in mind when it reads
# the guidance, and exemplars can then demonstrate the props in action.
# ---------------------------------------------------------------------------
TOKENS_NEW_GROUPS_GUIDANCE = """
## NEW TOKEN GROUPS (Wave 2)

Beyond color, the design system now has these knobs:

  density: compact | comfortable | spacious
    Drives default gaps + paddings. Use compact for data-dense pages
    (HR / fintech tables), spacious for marketing / content pages.

  elevation: flat | bordered | layered | floating
    flat = no shadow no border (Notion-like)
    bordered = border only (Linear-like)
    layered = shadow-sm + border (default)
    floating = shadow-lg (Stripe-like hero treatment)

  radius.scale: sharp | soft | round
    sharp = 4px (Linear)
    soft = 8px (default — shadcn-like)
    round = 12px (Notion-like)

  typography.display: family for headlines (hero text, page titles)
  typography.bodyText: family for paragraphs and labels
  typography.numeric: family for metric values (often a tabular face)
  typography.scaleMode: tight | balanced | dramatic — H1->H6 size jump

  motionLevel: none | subtle | expressive

Most schemas don't need to set these — they inherit from the project's
register (Wave 3). When you DO set them, set them on the root node so they
cascade.
"""

HIERARCHY_GUIDANCE = """
## INFORMATION HIERARCHY

Some library components accept hierarchy props. Use them to express which
piece of the page is the headline vs. supporting content.

  MetricTile.importance: "primary" | "secondary" | "tertiary"
    - Exactly ONE MetricTile per page should be `importance: primary` —
      the headline metric (the one that answers the user's main question).
    - Other MetricTiles default to `importance: secondary` (or omit the prop).
    - Use `tertiary` for sidebar / tertiary stats (small, label-first).

  Hero.role: "headline" | "banner" | "inline"
    - Detail pages and dashboards: `role: headline` (full-bleed page header)
    - Marketing-style pages or sub-sections: `role: banner` (default)
    - List pages or short pages: `role: inline` (one-liner)

  Section.role: "headline" | "content" | "aside" | "footer"
    - Top of the page: `role: headline`
    - Body: omit (default)
    - Right rail / sidebar: `role: aside`
    - Bottom: `role: footer`

  Card.density: "tight" | "regular" | "loose"
    - Data-dense (lists of cards, sidebar): `density: tight`
    - Default cards: omit
    - Hero cards / featured content: `density: loose`

  Heading.weight: "light" | "regular" | "bold" | "display"
    - Page title / hero headline: `weight: display`
    - Default: omit
    - De-emphasised: `weight: light`

ANTI-PATTERN — four equal-weight MetricTiles in a row. Always pick one as
`importance: primary` and the others as `secondary`/`tertiary`.
"""

DASHBOARD_METRICS_GUIDANCE = """
## DASHBOARD METRICS

DASHBOARD METRICS — when a page shows KPI MetricTiles, declare ONE aggregate
dataSource and bind each tile to a named metric:

  "dataSources": [
    { "name": "dashboardStats", "entity": "Appointment", "op": "aggregate",
      "metrics": {
        "todayCount":     { "fn": "count", "window": "today", "dateField": "date" },
        "monthlyRevenue": { "fn": "sum", "field": "total", "entity": "Invoice", "window": "month", "dateField": "issuedAt" },
        "pendingCount":   { "fn": "count", "entity": "Invoice", "filter": { "status": "pending" } },
        "paidRate":       { "kind": "ratio", "entity": "Invoice", "percent": true,
                            "numerator": { "fn": "count", "filter": { "status": "paid" } },
                            "denominator": { "fn": "count" } },
        "revenueChange":  { "kind": "delta", "fn": "sum", "field": "total", "entity": "Invoice",
                            "window": "month", "dateField": "issuedAt", "percent": true }
      } }
  ]
  // tiles bind to the metric KEYS:
  { "type": "MetricTile", "props": { "value": "{{dashboardStats.todayCount}}" } }

Rules:
- Every MetricTile value MUST reference a metric KEY that exists in `metrics`.
- `fn`: count | sum | avg | min | max. `field` is REQUIRED for everything but count
  and MUST be a real numeric column on the metric's entity.
- `entity` per-metric is optional (defaults to the source entity) — use it to count a
  related table (e.g. Invoice) from one dashboardStats source.
- `window` (today|week|month) + `dateField` add a time filter. `filter` adds equality
  filters. Omit what you don't need.
- RATIO metric — a percentage/rate (e.g. paid rate, cache hit rate). Use
  `{ "kind": "ratio", "numerator": {…}, "denominator": {…}, "percent": true }`.
  numerator/denominator are ordinary count/sum metrics; `percent:true` → 0-100.
- PERIOD-DELTA metric — change vs the previous period (e.g. "↑ 12% vs last month").
  Use `{ "kind": "delta", "fn": "sum", "field": "total", "window": "month",
  "percent": true }`. `percent:true` → % change; omit it for the absolute delta.
  `window` is REQUIRED for a delta. Bind the tile's `trend`/`delta` prop to it.
"""

CHART_SERIES_GUIDANCE = """
## CHART DATA

CHART DATA — a Chart's `data` MUST be bound to a real op:"series" dataSource, NEVER
a hardcoded array of made-up rows. A series source runs a GROUP BY and resolves to
an array of `{ label, value }` rows. So EVERY chart binds the same way:
`data: "{{sourceName}}"`, `xKey: "label"`, `series: [{ "name": "<legend>", "dataKey": "value" }]`.

  "dataSources": [
    // time series — group a date column into buckets (day|week|month):
    { "name": "signupsByWeek", "entity": "User", "op": "series",
      "groupBy": "createdAt", "bucket": "week", "agg": { "fn": "count" } },
    // category breakdown — group by a category column, biggest first:
    { "name": "ordersByStatus", "entity": "Order", "op": "series",
      "groupBy": "status", "agg": { "fn": "count" }, "sort": "value" }
  ]
  { "type": "Chart", "props": {
      "chartType": "line", "data": "{{signupsByWeek}}",
      "xKey": "label", "series": [{ "name": "Signups", "dataKey": "value" }] } }

Rules:
- `groupBy` MUST be a real column on the entity. Add `bucket` (day|week|month) ONLY when
  groupBy is a date/timestamp column (time chart); omit it for category charts.
- `agg`: { "fn": "count" } counts rows; sum/avg/min/max REQUIRE a real numeric `field`.
- `sort`: "value" ranks biggest→smallest (categories); omit for time charts (they stay
  chronological). `limit` caps the number of bars/points.
- The resolved rows always use keys `label` (x-axis) and `value` (y-axis) — so `xKey` is
  ALWAYS "label" and every series `dataKey` is ALWAYS "value".
"""

# Path from this file to the repo root (backend/services/ → repo root = ../../)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIBRARY_DEFAULT_TOKENS = _REPO_ROOT / "packages" / "library" / "src" / "theme" / "default-tokens.ts"
_SCHEMA_EXAMPLES_DIR = Path(__file__).parent / "schema_examples"

# Path to the canonical registry JSON built by `npm run build` in
# packages/registry.  Absent on a fresh clone (before npm install) — see
# _FALLBACK_COMPONENTS below.
_REGISTRY_JSON = (
    _REPO_ROOT / "packages" / "registry" / "dist" / "starter.json"
)

# Fallback when registry hasn't been built yet — covers core composable
# primitives + a representative mix of layout/input/display components
# so a fresh-clone run still generates plausible output.
_FALLBACK_COMPONENTS = [
    "Stack", "Row", "Grid", "Container", "Box", "Text", "Image",
    "Hero", "Section", "Card", "MetricTile", "FeatureCard",
    "Heading", "Badge", "Divider", "Avatar",
    "Form", "Input", "Textarea", "Select", "Checkbox", "Button", "Link",
    "Table", "Alert", "EmptyState", "Tabs",
]


@lru_cache(maxsize=1)
def _registered_components() -> list[str]:
    """Component names the LLM is told it can use. Sourced from the
    registry JSON when present (canonical) — falls back to a curated list
    when the dist file is absent (fresh clone before npm install). Always
    includes a few bare primitives (Box, Text, Image) that the registry
    doesn't list but the renderer accepts."""
    names: list[str] = []
    # Prefer the AUTHORITATIVE contracts (extracted from the renderer's own zod
    # propsSchemas) so the allowlist matches what validateProps actually accepts —
    # the legacy starter.json is hand-maintained and drifts (e.g. it lists the
    # non-existent `TableSortable`). Fall back to starter.json, then the curated list.
    try:
        from services.context_assembler import _component_contracts
        names = sorted(_component_contracts().keys())
    except Exception:
        names = []
    if not names:
        try:
            data = json.loads(_REGISTRY_JSON.read_text(encoding="utf-8"))
            names = sorted(data.keys())
        except (OSError, json.JSONDecodeError):
            names = list(_FALLBACK_COMPONENTS)
    # Augment with the bare primitives + layout nodes the renderer treats as
    # built-ins (they're not registered library components, so the contracts file
    # omits them, but they ARE valid node types — shells and pages use them).
    for primitive in ("Box", "Text", "Image", "Container", "Row", "Stack", "Grid", "Spacer"):
        if primitive not in names:
            names.append(primitive)
    return sorted(set(names))

TIER2_COMPONENTS_GUIDANCE = """
## TIER 2 COMPONENTS (data-heavy enterprise patterns)

  Sparkline { data: number[], width?, height?, color?, showDots? }
    Inline mini-chart. Use INSIDE DataGrid cells, MetricTile trends, or
    dashboard rows where the shape of a trend matters more than exact values.
    NOT a standalone visualisation — wrap in another component.

  Chart { chartType: "line"|"bar"|"area", data: object[], xKey: string,
          series: { name, dataKey, color? }[], height?, showGrid?, showLegend? }
    Full chart with axes/grid/tooltip/legend. Use for dashboard pages and
    reporting pages. Pick line for time-series, bar for comparisons,
    area for cumulative metrics.

  DataGrid { columns: ColumnDef[], rows: object[], rowKey: string,
             virtualise?, selectable?, expandable?, rowActions? }
    For data-heavy pages with > 20 rows. Use INSTEAD OF Table for list pages
    when columns need sorting/freezing/bulk-select. Each column can specify
    sortable, frozen, align, and a custom render component (e.g. render a
    StatusPill for the status column).

  Timeline { entries: TimelineEntry[], orientation?: "vertical"|"horizontal" }
    For audit logs, approval history, activity feeds tied to a single entity.
    Each entry has timestamp + actor + status + title + optional detail.

  ResourceTimeline { resources, items, itemResourceField, startField, endField,
                     titleField, statusField, resourceGroupField, days, itemHref }
    THE scheduler / Gantt grid: resources as ROWS (rooms, staff, vehicles,
    rentals, providers), days as COLUMNS, and items drawn as horizontal BARS
    spanning their date range, coloured by status. USE THIS (not a Table or the
    vertical Timeline, not Calendar) whenever the domain schedules bookable
    resources over time — hotel reservations by room, clinic appointments by
    provider, rentals by unit, shifts by employee. `resources` + `items` are
    bindings; group rows with resourceGroupField (e.g. room type).
    Example: a hotel "reservations"/"calendar"/"timeline" page →
      ResourceTimeline { resources: "{{rooms}}", items: "{{reservations}}",
        itemResourceField: "roomId", startField: "checkInDate",
        endField: "checkOutDate", titleField: "guestName", statusField: "status",
        resourceGroupField: "roomType", itemHref: "/reservations/{id}" }

ANTI-PATTERNS to avoid:
  - A reservation/booking/scheduling page rendered as a plain Table or vertical
    Timeline: use ResourceTimeline (rooms×days grid with booking bars)
  - Using Table for > 50 rows: use DataGrid (gets virtualisation for free)
  - Using a chart on every page: only dashboard/console/report archetypes
  - Sparkline standalone: always nest inside MetricTile.trend / DataGrid cell
  - Timeline as the primary content of a list page: use DataGrid + Timeline
    in an InspectorPanel for the selected row's history
"""

TIER2_BATCH2_GUIDANCE = """
## TIER 2 COMPONENTS BATCH 2 (enterprise patterns)

  ApprovalStepper { steps: { id, label, status, actor?, timestamp? }[],
                    orientation?: "horizontal"|"vertical" }
    For multi-stage approval flows. Each step's status is one of:
    pending|current|approved|rejected|skipped. Use horizontal for top-of-page
    progress indicators; vertical for sidebar/detail-panel approval history.

  PersonCard { name, role?, department?, avatarUrl?, avatarInitials?,
               email?, status?, manager?, layout?: "compact"|"expanded" }
    Avatar + name + role + manager + status combined. Use compact in lists +
    inline. Use expanded as a sidebar widget for "you are managed by X".
    Status enum: active|away|on-leave|offline.

  FilterBar { chips, savedViews?, showSearch? }
    URL-persisted filter management. Each chip is {key, label, options[]}.
    State writes to URL search params via useUrlState. Use ABOVE DataGrid
    for filterable lists. The savedViews dropdown applies a preset of
    multiple filter values at once.

  CommandPalette { items, placeholder?, triggerKey? }
    Cmd-K modal with fuzzy search. Each item has id + label + group? +
    shortcut? + action (navigate or workflow). Use as a top-level page
    affordance for power users — typically mounted once per app shell, not
    per page. Lists pages + actions + recent records.

  ActivityFeed { entries, title?, showFilter?, maxHeight? }
    Project-wide audit-trail sidebar. Different from Timeline (which is
    per-entity history). Each entry is {actor, action, target, timestamp,
    category?, detail?}. Categories: create|update|approve|reject|comment|
    system. Use as a right-rail widget on dashboards / console pages.

ANTI-PATTERNS:
  - Using Timeline for project-wide activity: prefer ActivityFeed
  - Using ApprovalStepper as the only content of a page: combine with
    DataGrid or KeyValueList showing the request being approved
  - Using FilterBar without DataGrid: filters with no list to filter is dead UI
  - Using PersonCard.expanded inline in a row: layout="compact" is for rows
"""

TIER2_BATCH3_GUIDANCE = """
## TIER 2 COMPONENTS BATCH 3 (filter ergonomics + first-render UX)

  EmptyStateRich { icon?, illustration?, heading, body?, primaryCta?,
                   sampleDataLink? }
    Replaces basic EmptyState for first-render contexts. Heading + body copy
    + primary CTA + optional "try with sample data" link. Wrap every
    DataGrid / Table / list-page-content in a `rows.length === 0 ?
    <EmptyStateRich/> : <DataGrid/>` guard.

  DateRangePicker { name, label?, startDate?, endDate?, presets?,
                    minDate?, maxDate? }
    Calendar popover with preset list (today / yesterday / last-7-days /
    last-30-days / quarter-to-date / year-to-date / custom). URL-persisted
    via {name}_start + {name}_end keys. Use on report / analytics / audit
    pages where time-range filtering is the primary axis. Combine with
    FilterBar for status/department filters.

  MultiSelect { name, label?, placeholder?, options[], selected?,
                showSearch?, maxSelectionLabel? }
    Checkbox-list dropdown for multi-value filters. Auto-shows search when
    options > 8. Same prop shape as Select; use INSTEAD OF Select when
    multiple values can be selected (e.g. "show employees in [Eng, Design,
    Sales]"). URL state is comma-separated CSV.

ANTI-PATTERNS:
  - Plain "No data" text under a DataGrid → use EmptyStateRich
  - Two separate <Input type="date"> for date filtering → use DateRangePicker
  - Three separate Select chips for the same filter axis → use MultiSelect
  - DateRangePicker WITHOUT a list/chart it filters → noise, no purpose
"""

PROGRESSIVE_DISCLOSURE_RULES = """
## Container choice (binding)

- Form with > 7 user-editable fields: wrap in Accordion (collapsed panels per
  logical group) or Tabs (one tab per group). Pick Accordion when groups have
  a sequence; Tabs when they don't.
- Detail page with > 5 sections of content: split with Tabs (or
  TabPanelWithDeepLink for URL-aware tabs).
- "View row → see detail" interaction: prefer InspectorPanel over a separate
  detail page.
- Related field cluster (3-6 fields that belong together semantically): wrap
  in Card.
- NEVER lay out > 10 form fields in a flat Stack — readers cannot scan that density.

## Reference patterns

See exemplar schemas under backend/fixtures/exemplars/:
  - wide-form-accordion.json     — 9 fields wrapped in Accordion
  - wide-form-tabs.json          — same fields wrapped in Tabs
  - detail-tabs.json             — detail page with 6 sections in Tabs
  - related-fields-card.json     — 4 related fields wrapped in Card
  - narrow-form-flat.json        — 4 fields in a flat Stack (OK at this size)
"""

# Exemplar JSON files live under backend/fixtures/exemplars/ — load lazily so
# we don't pay the IO cost on every import. _EXEMPLARS_DIR resolves to
# `<repo>/backend/fixtures/exemplars`.
_EXEMPLARS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "exemplars"


def _load_exemplar(name: str) -> str:
    """Read an exemplar JSON file's text contents, or return "" if missing."""
    p = _EXEMPLARS_DIR / f"{name}.json"
    try:
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except OSError:
        return ""


def _exemplar_for(page_type: str, route: str = "") -> str:
    """Pick the matching exemplar for a given page_type / route.

    Auth-shaped routes (/login, /signin, /signup, /register) take precedence
    over page_type and get the auth-split-illustration exemplar so the LLM
    learns the canonical 2-column form + illustration layout.

    Otherwise: form pages get the wide-form-accordion exemplar (the most
    common progressive-disclosure pattern). Detail pages get detail-tabs.
    Dashboard pages get dashboard-kpi-grid. Other page types get no
    exemplar — the rule block alone is sufficient.
    """
    if route and any(route.startswith(p) for p in ("/login", "/signin", "/signup", "/register")):
        return _load_exemplar("auth-split-illustration")
    return {
        "form":      _load_exemplar("wide-form-accordion"),
        "detail":    _load_exemplar("detail-tabs"),
        "dashboard": _load_exemplar("dashboard-kpi-grid"),
    }.get(page_type, "")


COLOR_RULES = """
## Color Rules — varied palette, semantic tokens

The project's tailwind theme exposes the FULL semantic palette below. USE
THEM ACTIVELY — pages that only paint with `primary` + `muted` + `foreground`
read as monochrome and feel like "black + brand color" — exactly the dull
look we're avoiding.

Use this palette of semantic tokens (NEVER raw Tailwind shades like
`bg-purple-500` unless the design spec lists that exact hex):

  Brand & action
    bg-primary / text-primary-foreground     — CTAs, active nav, focused
    bg-primary/10 / bg-primary/15            — tinted callouts, hero overlays
    bg-secondary / text-secondary-foreground — alt actions, segmented controls
    bg-accent / text-accent-foreground       — highlights, links, active row

  Status colours
    bg-success / text-success-foreground     — positive metrics (revenue up),
                                              completed states, "approved"
    bg-success/10 text-success                — green tinted chips/badges
    bg-warning / text-warning-foreground     — pending, attention, "review"
    bg-warning/10 text-warning                — amber chips, banner backgrounds
    bg-info / text-info-foreground            — informational, "tip" banners
    bg-info/10 text-info                      — blue tinted notices
    bg-destructive / text-destructive-foreground — errors, "delete"
    bg-destructive/10 text-destructive       — error chips, red badges

  Surface & text
    bg-background                              — page background
    bg-card / text-card-foreground             — Card surfaces
    bg-muted / text-muted-foreground           — labels, hints, captions,
                                                 secondary tab bg
    text-foreground                            — body text
    border-border                              — dividers, card borders

## Color usage patterns (REQUIRED — varies the palette across the page)

  Dashboard / overview pages MUST use at least THREE of:
    bg-primary (CTA), bg-success/10 (positive metric chip),
    bg-warning/10 (attention chip), bg-info/10 (tip block),
    bg-accent (highlighted row), bg-primary/10 (hero callout)

  Metric tiles — pick a colour per metric semantic:
    revenue / growth     → text-success on white card, success arrow icon
    pending / awaiting   → text-warning, warning arrow
    errors / failed      → text-destructive
    visits / impressions → text-info OR text-primary

  Badges — Badge.variant controls the colour. Use the variants:
    "success" for approved / live / active
    "warning" for pending / review / draft
    "danger"  for rejected / error / failed
    "primary" for brand-coloured statuses (default chip)
    "neutral" only as last resort — most chips have semantic meaning

  Status icons must match: CheckCircle in text-success,
    AlertTriangle in text-warning, XCircle in text-destructive,
    Info in text-info. Same family in tinted backgrounds.

  Hero — when backgroundImage is set, also add `bg-primary/90` overlay
    OR a brand gradient on the inner Card so the brand colour is felt.

## What NOT to do

- Painting every metric tile with `text-foreground` and `bg-card` only
  → it reads as "white on white with one button" — the dull look.
- Single-color pages where the only colour is `bg-primary` on the CTA button
  → users perceive the app as a B&W wireframe with a tinted button.
- Using `bg-muted` for everything that isn't `bg-primary` — `muted` is for
  supporting UI, not the default surface. Cards are `bg-card`, sections
  alternate `bg-background` / `bg-muted/30`.

## Hard prohibitions (still apply)

NEVER emit raw Tailwind palette classes unless the EXACT shade is in the
design spec tokens:
  bg-purple-*, bg-blue-*, bg-pink-*, bg-yellow-*, bg-cyan-*, bg-indigo-*
  text-amber-*, text-rose-*, text-teal-*, text-sky-*
  bg-orange-*, bg-lime-*, bg-violet-*, bg-fuchsia-*
  Any explicit hex not listed in the design tokens

These break theme switching and look pasted-in. The semantic tokens above
cover every legitimate use case.
"""

RESPONSIVE_RULES = """
## Responsive Rules — STRICT

All pages must render correctly on screens 375px wide and up.

For Grid nodes: ALWAYS use the `columns` prop with a number — the renderer
compiles it to responsive breakpoint classes automatically:
  - columns: 1  →  grid-cols-1
  - columns: 2  →  grid-cols-1 md:grid-cols-2
  - columns: 3  →  grid-cols-1 sm:grid-cols-2 lg:grid-cols-3
  - columns: 4  →  grid-cols-1 sm:grid-cols-2 lg:grid-cols-4
Do NOT emit hardcoded `className: "grid-cols-3"` strings — they will not
collapse on mobile. Use `props.columns: 3` (a number) instead.

For Row nodes containing 3+ children: emit `wrap: true` so children flow
onto multiple lines on narrow viewports, OR use a Grid instead.

For Container with explicit width: NEVER use w-[400px] or similar fixed px
widths. Use Tailwind responsive classes like `w-full md:w-2/3 lg:w-1/2`
or omit width entirely and let flex/grid handle sizing.

For Buttons that might wrap: use `whitespace-nowrap` in className so labels
don't break mid-word.

For Heading.level=1 (page titles): never set explicit text-[Npx] — let
the level prop and theme tokens decide the size.

For data tables (DataGrid): on mobile they should scroll horizontally —
the renderer already wraps them in overflow-x-auto. Don't fight that
by giving DataGrid a fixed width.
"""

RICH_VISUALS = """
## Visual richness — REQUIRED (no monogram-only layouts)

The library is built for image-rich, modern web apps. Plain "Card → Heading
→ Text" stacks render as bland boilerplate that looks AI-generated. Every
page MUST satisfy these rules — a post-pass enricher will retrofit any
omissions, but you should set them upstream so the prompt review is clean:

  Avatar — MUST always set props.photoUrl to a real Unsplash portrait URL.
    NEVER emit an Avatar that relies on initials-only rendering — the
    fallback is the "monogram" look that signals an unfinished app. When
    you need a placeholder face, use one of:
      https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=200&q=80
      https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=200&q=80
      https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=200&q=80
      https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=200&q=80
    WRONG: {{ "type": "Avatar", "props": {{ "name": "Sarah Johnson", "size": "md" }} }}
    RIGHT: {{ "type": "Avatar", "props": {{ "name": "Sarah Johnson", "size": "md",
              "photoUrl": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=200&q=80" }} }}

  Hero — landing / dashboard / marketing / auth-shaped pages MUST set
    props.backgroundImage = {{ "url": "<full https://images.unsplash.com/...>", "overlay": 0.4 }}.
    Pick a domain-appropriate photo (healthcare → hospital corridor,
    finance → trading screens, education → classroom). Skip backgroundImage
    ONLY for inline / table-row heroes where a background would distract.

  FeatureCard — props.icon is REQUIRED. Choose a Lucide name that matches
    the feature semantics (e.g. title "Real-time analytics" → "trending-up";
    title "Bank-grade security" → "shield"; title "24/7 support" → "message-circle").

  EmptyStateRich — props.illustration is REQUIRED on every empty state.
    You have access to the `list_illustrations` MCP tool — call it once
    per page that needs one, then set illustration to the chosen slug.

  Card stacks — if a page has 3+ Card nodes and zero Image / Avatar /
    Hero / FeatureCard / Icon descendants, the page reads as "monogram"
    and the user will reject the output. Insert at least ONE imagery node
    per ~3 cards (a hero photo, a category illustration, an avatar
    cluster, etc).

Why this matters: the runtime renders Avatar's blank-photoUrl state as
two initials in a coloured circle. Three of those side-by-side IS the
"monogram-like" anti-pattern users complain about. Heroes without
backgrounds + FeatureCards without icons compound the problem.
"""

TIER2_LAYOUT_GUIDANCE = """
## TIER 2 LAYOUT PRIMITIVES (Wave 4)

  AppShell { sidebar?, topbar?, actions?, rightRail?, children }
    Canonical app-chrome composition. Use as the ROOT node of every page in
    enterprise apps. Sidebar = global nav. Topbar = breadcrumb/title.
    Actions = page-level CTAs. RightRail = context sidebar (e.g. ActivityFeed).

  InspectorPanel { paramKey?, title?, width?, children }
    Slide-out detail panel from the right edge. Hidden until URL has the
    paramKey set. Use for "click row in DataGrid → see full record without
    page change". Composes with DataGrid via ?{paramKey}={rowId} URL state.
    width: narrow (320) | default (480) | wide (640).

  TabPanelWithDeepLink { paramKey?, tabs[], defaultTab?, children }
    URL-aware tabs. children must be ONE node per tab, IN ORDER (matched to
    tabs[] array index). Use for detail pages with multiple sections
    (Overview / History / Settings). Active tab survives refresh + browser
    back-button.

ANTI-PATTERNS:
  - Wrapping every page in AppShell when only a Hero/main-content layout is
    needed (Section is fine for content-only pages)
  - InspectorPanel without a triggering UI (DataGrid row-click, button, or
    link must set the URL param via &{paramKey}={value})
  - Using Tabs+TabPanel for tabs on detail pages: prefer TabPanelWithDeepLink
    so users can refresh / share the URL
"""


def render_token_paths(tokens: dict, prefix: str = "tokens") -> str:
    """Walk a tokens dict, emit one line per LEAF path.

    A leaf is a value that's not a dict. Branches (intermediate dicts) are
    NOT emitted — they're not valid token refs.

    Wave 2: top-level scalar fields (density, elevation, motionLevel) and
    scalar sub-fields inside dicts (radius.scale, typography.scaleMode) are
    now emitted as leaves — the walker recurses into dicts at every depth
    and emits any non-dict value as a leaf.

    Returns a newline-separated string suitable for inclusion in the
    LLM prompt.
    """
    lines: list[str] = []

    def _walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                child_path = f"{path}.{k}"
                _walk(v, child_path)
        elif obj is not None:
            # Leaf: any non-dict, non-None value (str, int, float, bool, list)
            lines.append(path)

    _walk(tokens, prefix)
    return "\n".join(sorted(lines))


def load_default_tokens() -> dict:
    """Read defaultTokens from the library's TypeScript source.

    We extract the literal object via a Node subprocess — TS is the source
    of truth, not a JSON mirror. Falls back to a hardcoded subset if the
    subprocess fails (e.g., in test environments without Node).
    """
    try:
        # Run a tiny tsx/node script that imports defaultTokens and prints JSON
        result = subprocess.run(
            [
                "node", "--input-type=module", "-e",
                f'import("file://{_LIBRARY_DEFAULT_TOKENS.resolve()}".replace(/\\.ts$/, ".js")).then(m => process.stdout.write(JSON.stringify(m.defaultTokens)))',
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
    except Exception as e:
        logger.warning("schema_prompt: load_default_tokens subprocess failed: %s", e)

    # Fallback: hardcoded canonical subset matching defaultTokens shape.
    # This must be kept in sync with packages/library/src/theme/default-tokens.ts.
    return _FALLBACK_DEFAULT_TOKENS


_FALLBACK_DEFAULT_TOKENS = {
    "color": {
        "primary":   {"50": "#eff6ff", "100": "#dbeafe", "200": "#bfdbfe", "300": "#93c5fd",
                      "400": "#60a5fa", "500": "#3b82f6", "600": "#2563eb", "700": "#1d4ed8",
                      "800": "#1e40af", "900": "#1e3a8a", "950": "#172554"},
        "secondary": {"50": "#f5f3ff", "100": "#ede9fe", "200": "#ddd6fe", "300": "#c4b5fd",
                      "400": "#a78bfa", "500": "#8b5cf6", "600": "#7c3aed", "700": "#6d28d9",
                      "800": "#5b21b6", "900": "#4c1d95", "950": "#2e1065"},
        "accent":    {"50": "#fdf4ff", "100": "#fae8ff", "200": "#f5d0fe", "300": "#f0abfc",
                      "400": "#e879f9", "500": "#d946ef", "600": "#c026d3", "700": "#a21caf",
                      "800": "#86198f", "900": "#701a75", "950": "#4a044e"},
        "surface":   {"0": "#ffffff", "1": "#fafafa", "2": "#f4f4f5"},
        "border":    {"default": "#e4e4e7"},
        "muted":     {"default": "#a1a1aa"},
        "text":      {"primary": "#18181b", "secondary": "#52525b", "tertiary": "#a1a1aa"},
        "sidebar":   {"bg": "#0f172a", "text": "#cbd5e1", "active": "#1e293b"},
        "success":   {"50": "#f0fdf4", "500": "#22c55e", "700": "#15803d"},
        "warning":   {"50": "#fffbeb", "500": "#f59e0b", "700": "#b45309"},
        "error":     {"50": "#fef2f2", "500": "#ef4444", "700": "#b91c1c"},
        "info":      {"50": "#eff6ff", "500": "#3b82f6", "700": "#1d4ed8"},
    },
    "spacing": {
        "0": "0", "1": "0.25rem", "2": "0.5rem", "3": "0.75rem", "4": "1rem",
        "6": "1.5rem", "8": "2rem", "12": "3rem", "16": "4rem", "24": "6rem",
        "32": "8rem", "48": "12rem", "64": "16rem",
        "semantic": {"page": "2rem", "card": "1.25rem", "section": "4rem", "element": "1rem", "input": "0.75rem"},
    },
    # Wave 2: radius.scale is a scalar leaf alongside the existing named radii.
    "radius": {
        "sm": "0.25rem", "md": "0.5rem", "lg": "0.75rem", "xl": "1rem", "full": "9999px",
        "scale": "soft",
    },
    "shadow": {"sm": "0 1px 2px", "md": "0 4px 6px", "lg": "0 10px 15px", "xl": "0 20px 25px"},
    "typography": {
        "font":   {"body": "Inter, system-ui, sans-serif", "heading": "Inter, system-ui, sans-serif"},
        "weight": {"body": "400", "heading": "600"},
        "scale":  {"h1": "2rem", "h2": "1.5rem", "h3": "1.25rem", "body": "0.875rem", "caption": "0.75rem"},
        "lineHeight":    {"tight": "1.25", "normal": "1.5"},
        "letterSpacing": {"heading": "-0.02em", "body": "0"},
        # Wave 2: new typography sub-groups — defaults match today's appearance.
        "display":   {"family": "Inter, system-ui, sans-serif", "weight": 700},
        "bodyText":  {"family": "Inter, system-ui, sans-serif", "weight": 400, "lineHeight": 1.5},
        "numeric":   {"family": "Inter, system-ui, sans-serif", "weight": 500, "tabular": False},
        "scaleMode": "balanced",
    },
    "motion": {
        "duration": {"fast": "150ms", "normal": "300ms"},
        "easing":   {"standard": "cubic-bezier(0.4, 0, 0.2, 1)"},
    },
    # Wave 2: new top-level scalar groups — defaults match today's appearance.
    "density":     "comfortable",
    "elevation":   "layered",
    "motionLevel": "subtle",
}


def load_enterprise_pattern(archetype_or_role: str) -> dict | None:
    """Load an enterprise pattern by best-match keyword.

    Walks the keyword_map and returns the first matching pattern's JSON.
    Returns None if no match or file missing.
    """
    PATTERNS_DIR = Path(__file__).parent / "schema_examples" / "enterprise"
    if not PATTERNS_DIR.exists():
        return None

    keyword_map = {
        "master-detail":        ["list", "detail", "browse", "manage"],
        "multi-step-wizard":    ["wizard", "onboarding", "create", "multi-step"],
        "approval-flow":        ["approval", "review", "request"],
        "reporting-dashboard":  ["report", "analytics", "dashboard", "kpi"],
        "settings-grouped":     ["settings", "profile", "preferences"],
        "audit-log":            ["audit", "history", "activity", "log"],
    }

    role = (archetype_or_role or "").lower()
    for pattern_name, keywords in keyword_map.items():
        if any(kw in role for kw in keywords):
            path = PATTERNS_DIR / f"{pattern_name}.json"
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
    return None


def load_gold_example(page_type: str, archetype: str | None) -> dict | None:
    """Load the gold-standard example for the given (page_type, archetype).

    Falls back to the first available example for the page_type if the
    specified archetype isn't found. Returns None if the page_type itself
    doesn't have any examples.
    """
    page_dir = _SCHEMA_EXAMPLES_DIR / page_type
    if not page_dir.exists() or not page_dir.is_dir():
        return None

    # Try requested archetype first
    if archetype:
        archetype_path = page_dir / f"{archetype}.json"
        if archetype_path.exists():
            try:
                return json.loads(archetype_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("schema_prompt: failed to parse %s: %s", archetype_path, e)

    # Fallback: first example in the directory
    candidates = sorted(page_dir.glob("*.json"))
    if not candidates:
        return None

    if archetype:
        logger.warning(
            "schema_prompt: archetype '%s' not found for page_type '%s'; falling back to %s",
            archetype, page_type, candidates[0].stem,
        )
    try:
        return json.loads(candidates[0].read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("schema_prompt: failed to parse fallback %s: %s", candidates[0], e)
        return None


_DNA_LAYOUT_KEYS = ("dashboard", "list", "detail", "auth", "chrome", "form")


def _merge_dna_composition(spec: dict, output_dir: str | Path) -> dict:
    """Backfill composition/voice from design-dna.json when the spec lacks it.

    design-spec.json can lose the Layout-DNA keys (an agent refine pass, a
    template seed, or an older spec rewriting `layout` down to
    {navigation, density}) — and every downstream builder then silently
    falls back to the historical stat-grid/table shapes. design-dna.json is
    written unconditionally at generation start, so it is the durable source.
    """
    try:
        dna_path = Path(output_dir) / "src" / "contracts" / "design-dna.json"
        if not dna_path.exists():
            return spec
        layout = spec.get("layout")
        if not isinstance(layout, dict):
            layout = {}
        missing = [k for k in _DNA_LAYOUT_KEYS if not layout.get(k)]
        needs_voice = not isinstance(spec.get("voice"), dict) or not spec.get("voice")
        if not missing and not needs_voice:
            return spec
        dna = json.loads(dna_path.read_text(encoding="utf-8"))
        dna_layout = dna.get("layout") or {}
        for k in missing:
            if dna_layout.get(k):
                layout[k] = dna_layout[k]
        if dna.get("shell", {}).get("chrome") and not layout.get("chrome"):
            layout["chrome"] = dna["shell"]["chrome"]
        spec["layout"] = layout
        if needs_voice and isinstance(dna.get("voice"), dict):
            spec["voice"] = dict(dna["voice"])
        if not spec.get("archetype") and dna.get("archetype"):
            spec["archetype"] = dna["archetype"]
    except Exception as e:  # noqa: BLE001 — backfill must never break page gen
        logger.warning("schema_prompt: design-dna composition backfill failed: %s", e)
    return spec


def _load_design_spec(output_dir: str | Path | None) -> dict:
    """Load src/contracts/design-spec.json from the output directory if present.

    Always passes through _merge_dna_composition so the Layout-DNA keys
    survive whatever rewrote the spec.
    """
    if not output_dir:
        return {}
    spec_path = Path(output_dir) / "src" / "contracts" / "design-spec.json"
    if not spec_path.exists():
        return _merge_dna_composition({}, output_dir)
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("schema_prompt: failed to read design-spec.json: %s", e)
        return _merge_dna_composition({}, output_dir)
    return _merge_dna_composition(spec, output_dir)


def _format_library_descriptor() -> str:
    """Return the available components as a readable descriptor."""
    lines = ["Available components:"]
    for c in _registered_components():
        lines.append(f"  - {c}")
    return "\n".join(lines)


def format_design_brief_for_schema(spec: dict) -> str:
    """Return a markdown design-context block for the schema (token-mode) prompt.

    Carries the same fidelity CONTENT as the Tailwind-path brief but frames
    everything as REFERENCE / INTENT for token-model composition decisions:

    - Concrete brand palette hex values labeled as reference (semantic tokens
      resolve to these; do NOT inline hex).
    - Component style intent (button/card radius, density).
    - Navigation style and typography for composition decisions.
    - Entity view patterns if present.

    NEVER emits globals.css or Tailwind bg-[#hex] class instructions — those
    are Tailwind-path only and would contradict the token-only color rules.

    Args:
        spec: design-spec dict (may be empty or partially populated; never raises).

    Returns:
        A markdown string, or empty string if spec is empty.
    """
    if not spec:
        return ""

    lines: list[str] = ["## Brand design context (reference for composition decisions)"]
    lines.append(
        "The design tokens below resolve to the brand colors listed here. "
        "Compose using the semantic token paths — do NOT inline these hex values directly."
    )
    lines.append("")

    # --- Colour palette ---
    palette = spec.get("colorPalette") or {}
    if palette:
        lines.append("### Brand palette (hex reference only — use token paths in schema)")
        for role, hex_val in palette.items():
            if isinstance(hex_val, str):
                lines.append(f"  - {role}: {hex_val}")
        lines.append("")

    # --- Typography ---
    typography = spec.get("typography") or {}
    if typography:
        lines.append("### Typography")
        if typography.get("fontFamily"):
            lines.append(f"  - Font family: {typography['fontFamily']}")
        if typography.get("headingWeight"):
            lines.append(f"  - Heading weight: {typography['headingWeight']}")
        lines.append("")

    # --- Layout / navigation ---
    layout = spec.get("layout") or {}
    nav_style = layout.get("navigation") if isinstance(layout, dict) else None
    density = layout.get("density") if isinstance(layout, dict) else None
    if nav_style or density:
        lines.append("### Layout intent")
        if nav_style:
            lines.append(f"  - Navigation: {nav_style}")
        if density:
            lines.append(f"  - Density: {density}")
        lines.append("")

    # --- Composition DNA (THIS app's chosen page shapes) ---
    # Without these, LLM-authored pages converge on the statistical-average
    # layout (KPI tiles + a table) and every app looks like every other app.
    _COMP_DIRECTIVES = {
        "dashboard": {
            "stat-strip": "a thin full-width KPI band first, then ONE wide primary block",
            "stat-grid": "a 3-4 column KPI tile grid, then supporting blocks in a 2-col grid",
            "hero-led": "open with a greeting/summary hero band; KPIs support below it",
            "feed-led": "the activity feed/table IS the page lead; KPIs demoted below it",
            "split-focus": "60/40 split — primary work surface beside a slim KPI rail",
            "board-first": "cards/board blocks lead in a wide grid; compact metrics underneath",
        },
        "list": {
            "table": "dense Table with rowHref",
            "card-grid": "a 3-col Grid of Cards (Repeat over the list), NOT a table",
            "board": "a Kanban grouped by the status column, NOT a table",
            "timeline": "a date-anchored feed of Cards (Repeat), NOT a table",
        },
        "detail": {
            "split-detail": "2:1 Split — primary fields left, record-info meta card right",
            "profile-detail": "identity band (Avatar + name + status Badge) above the facts",
            "timeline-detail": "3 key facts as a summary strip, then the full record card",
            "tabbed-hero": "title hero band (record name + Badge), then the record card",
        },
    }
    if isinstance(layout, dict):
        comp_lines = []
        for key in ("dashboard", "list", "detail", "form", "chrome"):
            val = layout.get(key)
            if not val:
                continue
            directive = _COMP_DIRECTIVES.get(key, {}).get(str(val), "")
            comp_lines.append(f"  - {key}: {val}" + (f" — {directive}" if directive else ""))
        if comp_lines:
            lines.append("### Composition DNA (follow these page shapes — they ARE this app's identity)")
            lines.extend(comp_lines)
            lines.append("")

    # --- Entity view patterns ---
    entity_patterns = spec.get("entityPatterns")
    if entity_patterns:
        lines.append("### Entity view patterns")
        if isinstance(entity_patterns, dict):
            for entity, pattern in entity_patterns.items():
                lines.append(f"  - {entity}: {pattern}")
        lines.append("")

    return "\n".join(lines)


def build_schema_prompt(
    plan: dict,
    library_descriptor: dict | None = None,
    tokens: dict | None = None,
    page_brief: dict | None = None,
    domain: str | None = None,
    design_spec: dict | None = None,
) -> str:
    """Assemble the full LLM prompt for schema generation.

    Args:
        plan: dict with keys:
              - description (str)
              - entity (dict with name, fields)
              - page_type (str: "list", "detail", "form", "landing")
              - archetype (optional str)
              - _output_dir (optional path) — for loading design-spec.json
              - workflows (optional list)
        library_descriptor: ignored for now (we hardcode the registered-components list)
        tokens: optional dict to use instead of loading defaultTokens
        design_spec: optional dict to use instead of loading design-spec.json from
                     _output_dir — primarily for testing and programmatic callers

    Returns:
        A formatted prompt string ready for the LLM.
    """
    # Task 36: FIDELITY_MODE_ENABLED is imported at module level — when false,
    # skip design-spec injection and gold-example loading so the prompt reverts
    # to structural-only guidance.

    description = plan.get("description", "")
    entity = plan.get("entity", {})
    entity_name = entity.get("name", "Unknown") if isinstance(entity, dict) else "Unknown"
    page_type = plan.get("page_type", "list")
    archetype = plan.get("archetype")
    output_dir = plan.get("_output_dir")

    # 1. Load design spec (rationale, layout hints, etc.)
    # If the caller passed a design_spec dict directly, use it; otherwise
    # load from _output_dir (or empty dict when fidelity mode is off).
    # Task 36: skipped when fidelity mode is off; treat as empty spec.
    if design_spec is None:
        if FIDELITY_MODE_ENABLED:
            design_spec = _load_design_spec(output_dir)
        else:
            design_spec = {}
    rationale = design_spec.get("designRationale", "")

    # 2. Auto-generate token paths from defaultTokens (single source of truth).
    # Token paths are always rendered — they are the token contract and are
    # independent of fidelity mode.
    if tokens is None:
        tokens = load_default_tokens()
    token_paths_str = render_token_paths(tokens)

    # 3. Library descriptor
    library_str = _format_library_descriptor()

    # 4. Gold-standard example
    # Task 36: skipped when fidelity mode is off.
    if FIDELITY_MODE_ENABLED:
        example = load_gold_example(page_type, archetype)
    else:
        example = None

    example_block = ""
    if FIDELITY_MODE_ENABLED and example:
        example_block = (
            "\n## Gold-standard example for this archetype\n"
            "Follow the level of richness shown here. Use real token refs. "
            "Use StyleSlot (background, padding, radius, shadow, motion) liberally.\n\n"
            f"```json\n{json.dumps(example, indent=2)}\n```\n"
        )

    # 5. Compose the prompt
    rationale_block = ""
    if rationale:
        rationale_block = f"\n## Domain & design rationale\n{rationale}\n"

    # SP1.5-F3: inject a token-framed domain design brief so the schema LLM
    # knows the concrete brand palette and style intent. Gated by
    # FIDELITY_MODE_ENABLED (same gate as rationale above).
    design_brief_block = ""
    if FIDELITY_MODE_ENABLED and design_spec:
        _brief = format_design_brief_for_schema(design_spec)
        if _brief:
            design_brief_block = f"\n{_brief}\n"

    archetype_note = f' (archetype: "{archetype}")' if archetype else ""

    prompt = f"""You generate JSON schemas for the Tentoroforge platform's
schema-driven runtime. Your output is a single JSON object validated by
the Page schema (schemaVersion: "2"). Output ONLY the JSON — no prose,
no markdown fences, no explanations.

## App context
{description}

## Page archetype
This is a {page_type} page{archetype_note} for entity "{entity_name}".
{rationale_block}{design_brief_block}
## Available design tokens (use these — never inline hex/px/rem)
{token_paths_str}

{COLOR_RULES}
## {library_str}

## Component prop contracts (use EXACT prop names — do not invent v1-style names)

Use these exact prop names. Common mistakes to avoid: do NOT use `content`,
`children`, `href`, `text`, `defaultValue`, `minLength`, `maxLength` — those
are v1 names that the v2 contracts reject.

  Button       {{ label?, variant: "primary"|"secondary"|"ghost"|"danger", size: "sm"|"md"|"lg", icon?: string, iconPosition?: "left"|"right", "aria-label"?: string, navigate?: string, workflow?: string, args?: object, disabled?: bool }}
               // label is optional when icon is set; use a lowercase kebab-case Lucide name for icon (e.g. "plus", "filter", "chevron-right", "more-horizontal")
               // icon-only buttons MUST set aria-label
               // CORRECT: {{ "type": "Button", "props": {{ "label": "Add task", "icon": "plus" }} }}
               // CORRECT: {{ "type": "Button", "props": {{ "label": "Filter", "icon": "filter", "iconPosition": "right" }} }}
               // CORRECT: {{ "type": "Button", "props": {{ "icon": "more-horizontal", "aria-label": "More" }} }}
  Link         {{ label, navigate: string, workflow?: string, args?: object }}      // no `variant`, no `href`
  IconButton   {{ icon, "aria-label", variant?, size?, navigate?, workflow? }}

  Hero         {{ eyebrow?, headline, subhead?, layout: "centered"|"split"|"stacked", ctas: [{{label, action: {{type:"navigate", to}} | {{type:"workflow", name}}, variant?}}], media? }}
  Section      {{ variant: "plain"|"feature"|"cta"|"stats"|"split", title?, subtitle?, anchor? }}
  FeatureCard  {{ title, description, icon?, cta?: {{label, href}}, layout: "icon-top"|"icon-left" }}
  MetricTile   {{ label: string, value: number|string, format: "number"|"currency"|"percent"|"duration", delta?: {{direction: "up"|"down"|"flat", value: number}}, icon?: string, trend?: number[], importance?: "primary"|"secondary"|"tertiary" }}
               // CORRECT: {{ "label": "Total Users", "value": 1284, "format": "number" }}
               // CORRECT: {{ "label": "Revenue", "value": 482910, "format": "currency", "delta": {{ "direction": "up", "value": 0.12 }} }}
               // CORRECT: {{ "label": "Pending", "value": "{{{{stats.pendingCount}}}}", "format": "number", "importance": "primary" }}
               // WRONG: format "text" or "string" — use "number"|"currency"|"percent"|"duration" ONLY
               // WRONG: delta as a scalar (e.g. 0.5) — must be {{ direction, value }} object
               // WRONG: omit `format` entirely — it is REQUIRED

  Badge        {{ content, variant: "neutral"|"primary"|"success"|"danger"|"warning" }}    // not `text`, not `label`
  Avatar       {{ name, src?, size: "sm"|"md"|"lg", status?: "online"|"offline"|"away"|"busy" }}
  Skeleton     {{ variant: "rect"|"circle"|"text", lines? }}
  KeyValueList {{ items: [{{label, value, copyable?: bool}}] }}

  Input        {{ name, label, type: "text"|"email"|"password"|"number"|"url"|"tel", placeholder?, validators?: {{required?, min?, max?, pattern?, message?}} }}
  Textarea     {{ name, label, rows?, placeholder?, validators? }}
  Select       {{ name, label, options: [{{value, label}}], validators? }}
  Checkbox     {{ name, label, validators? }}
  DatePicker   {{ name, label, min?, max?, validators? }}    // ISO 8601 (YYYY-MM-DD)

  Form         {{ workflow?, fields?[], defaultValues?, submitLabel?, style?, children? }}
               // Two modes — pick ONE per page:
               //
               // DECLARATIVE (preferred for standard CRUD forms):
               //   Pass `workflow` + `fields` array as props; omit children.
               //   Each field object is typed — `kind` drives rendering. Form
               //   auto-renders inputs, validation messages, and a submit button.
               //   Use this for all forms with known fields and no custom layout.
               //
               //   fields[i] = {{ kind: "text"|"email"|"number"|"textarea"|"select"|
               //                          "checkbox"|"date",
               //                   name: string,          // form field name
               //                   label: string,         // visible label
               //                   required?: boolean,
               //                   placeholder?: string,  // text/email/number only
               //                   rows?: number,          // textarea only
               //                   options?: [{{value, label}}]  // select only
               //                }}
               //
               //   CORRECT declarative example:
               //     {{ "type": "Form", "props": {{
               //         "workflow": "createNote",
               //         "submitLabel": "Save note",
               //         "fields": [
               //           {{ "kind": "text",     "name": "title", "label": "Title", "required": true }},
               //           {{ "kind": "textarea", "name": "body",  "label": "Body",  "rows": 6 }}
               //         ]
               //     }} }}
               //
               // CONTAINER (only when custom layout is required):
               //   Leave props empty (or just style); place Input / Textarea /
               //   Select / Button nodes as children. Form provides the <form>
               //   wrapper + optional workflow dispatch but does NOT auto-render
               //   fields. Use ONLY for multi-column grids, grouped sections
               //   under Accordion, or conditional fields. Standard CRUD forms
               //   MUST use declarative mode.
               //
               //   WRONG for a basic CRUD form (do not emit this pattern):
               //     {{ "type": "Form", "props": {{}}, "children": [
               //       {{ "type": "Stack", "children": [
               //         {{ "type": "Input", "props": {{ "name": "title", "label": "Title" }} }}
               //       ]}}
               //     ] }}

  Tabs         {{ tabs: [{{id, label, icon?}}], value: string }}    // children[i] is the panel for tabs[i]; do NOT use `defaultValue`
  Accordion    {{ mode: "single"|"multi", defaultOpen?: string[] }}    // children must be AccordionPanel; mode is `multi` not `multiple`
  AccordionPanel {{ value, label }}

  Table        {{ columns: [{{key, label, width?}}], rows|data, caption? }}    // bind the row array via `rows` (or `data`), e.g. "rows": "{{{{properties}}}}"; column-level `type`/`sortable` are NOT in the schema

  Split        {{ ratio: "1:1"|"2:1"|"1:2"|"3:1"|"1:3", breakpoint?: "sm"|"md"|"lg" }}    // exactly 2 children
  Sidebar      {{ width: "240px"|"60"|... }}    // exactly 2 children: [aside, main]
  Cluster      {{ gap?: tokenRef, justify?: "start"|"center"|"end"|"between", align?: "start"|"center"|"end"|"stretch" }}

  Stack        {{ direction: "vertical"|"horizontal", gap?, align?, justify?, wrap? }}
  Row          {{ gap?, align?, justify?, wrap? }}
  Grid         {{ columns: number, gap? }}
  Container    {{ maxWidth: "sm"|"md"|"lg"|"xl"|"2xl"|"full" }}

For data binding, use `dataSources` at the page level + `bind` on individual
nodes. A Table's row array is bound via its `rows` (or `data`) prop, e.g.
`"rows": "{{{{properties}}}}"`. Do not use `source`, `defaultSort`, `pagination`,
or `emptyState` — those are not real Table props.

## Layout patterns to follow

- Pages should be visually rich: at least one Hero or Section per page.
- Detail / dashboard pages: Hero (with eyebrow + headline + 1-2 CTAs) →
  Grid of MetricTiles (3-4 cols at lg, 2 at sm, 1 mobile) → Card-wrapped
  sections (KeyValueList, Table, Tabs, etc).
- Form pages: Hero (lighter) → Card → Form (Input/Select/Textarea/Checkbox/
  DatePicker grouped with Section dividers).
- List pages: Hero (light) → MetricTile row of summary stats → Table or
  Grid of FeatureCards.
- Use Grid for responsive multi-column layouts (it auto-collapses on mobile).
- Use Split with breakpoint:"md" for two-pane detail layouts.
- Wrap pages in Container (maxWidth:"xl") so margins look right on mobile
  AND desktop, with Stack gap:"tokens.spacing.semantic.section" between
  major blocks for breathing room.

## Data binding — DO NOT hardcode entity-specific values

The schema runtime resolves Mustache-style `{{{{path}}}}` placeholders against
the page's `dataSources` at render time. ALWAYS use bindings — NEVER inline
fake names, dates, descriptions, or other entity-specific data.

Wrong (hardcoded values that will appear identically for every record):
  {{ "type": "Heading", "props": {{ "content": "Sarah Johnson - Marketing" }} }}
  {{ "type": "Text",    "props": {{ "content": "Family vacation to Europe" }} }}
  {{ "type": "Badge",   "props": {{ "content": "Approved" }} }}

Right (resolved per-record from dataSources at render time):
  {{ "type": "Heading", "props": {{ "content": "{{{{employee.name}}}} - {{{{employee.department}}}}" }} }}
  {{ "type": "Text",    "props": {{ "content": "{{{{leaveRequest.reason}}}}" }} }}
  {{ "type": "Badge",   "props": {{ "content": "{{{{leaveRequest.status}}}}" }} }}

Also declare the data source at the top of the schema:
  "dataSources": [
    {{ "name": "leaveRequest", "entity": "LeaveRequest", "op": "get" }},
    {{ "name": "employee",     "entity": "Employee",     "op": "get",
       "filter": {{ "id": "leaveRequest.employeeId" }} }}
  ]

Repeating record collections (recent items, table rows, card grids) use
`Repeat` with `bind` pointing at the dataSource name; each iteration scopes
`item` to the current row, so children reference `{{{{item.field}}}}`:
  {{ "type": "Repeat", "bind": "recentRequests", "children": [
    {{ "type": "Card", "children": [
      {{ "type": "Heading", "props": {{ "content": "{{{{item.employee.name}}}}" }} }},
      {{ "type": "Badge",   "props": {{ "content": "{{{{item.status}}}}" }} }}
    ]}}
  ]}}

In short: every concrete name, date, number, or status that varies per
record must come from `{{{{...}}}}`. The only literal text in the schema should
be UI labels (button text, section titles like "Recent Requests", form
field labels) — never the data those labels describe.
{example_block}
## Your task
Emit a Page schema for entity "{entity_name}" / page-type "{page_type}".
Emit ONLY the JSON object — no fences, no commentary."""

    # ── Context engine (first slice): inject HARD CONTRACTS up front — the
    # authoritative component allowlist + exact prop names (from the library's zod
    # schemas) and the entity's REAL columns. This turns the registry from a post-hoc
    # validator into an up-front constraint, so the model can't emit unknown
    # components/props (which validateProps would strip) or invent/rename field names.
    try:
        from services.context_assembler import component_catalog_block, entity_columns_block
        _contract = component_catalog_block()
        if _contract:
            prompt += "\n\n" + _contract
        if isinstance(entity, dict) and entity.get("name"):
            _cols = entity_columns_block(entity["name"], {"entities": {entity["name"]: entity}})
            if _cols:
                prompt += "\n\n" + _cols
    except Exception:
        pass  # never block prompt assembly on the context assembler

    # Hierarchy semantics — injected after component contracts (already in the
    # f-string above) and before Phase 15 reference exemplars so the LLM sees
    # the guidance before the few-shot examples demonstrate it.
    prompt += "\n\n" + HIERARCHY_GUIDANCE

    # Dashboard aggregate-metrics guidance — teaches the agent to emit a
    # `metrics` map on op:"aggregate" dataSources so MetricTile bindings
    # like {{dashboardStats.todayCount}} resolve to real numbers.
    prompt += "\n\n" + DASHBOARD_METRICS_GUIDANCE

    # Chart data: bind Chart.data to an op:"series" (GROUP BY) dataSource instead
    # of hardcoding mock rows, so charts render real aggregated data.
    prompt += "\n\n" + CHART_SERIES_GUIDANCE

    # Wave 2 token groups guidance — surfaces density, elevation, radius.scale,
    # typography sub-groups, and motionLevel to the LLM right after hierarchy.
    prompt += "\n\n" + TOKENS_NEW_GROUPS_GUIDANCE

    # Tier 2 component contracts — Chart, Sparkline, DataGrid, Timeline
    prompt += "\n\n" + TIER2_COMPONENTS_GUIDANCE

    # Tier 2 batch 2 — ApprovalStepper, PersonCard, FilterBar, CommandPalette, ActivityFeed
    prompt += "\n\n" + TIER2_BATCH2_GUIDANCE

    # Tier 2 batch 3 — EmptyStateRich, DateRangePicker, MultiSelect
    prompt += "\n\n" + TIER2_BATCH3_GUIDANCE

    # Tier 2 Wave 4 — AppShell, InspectorPanel, TabPanelWithDeepLink
    prompt += "\n\n" + TIER2_LAYOUT_GUIDANCE

    # Responsive rules — Grid columns compile to breakpoint classes;
    # Row wrapping; no fixed-px widths; no explicit heading text sizes.
    prompt += "\n\n" + RESPONSIVE_RULES

    # Visual richness — REQUIRED rules that prevent the "monogram-only" /
    # "Card + Heading + Text" boilerplate look. Forces real photo URLs on
    # Avatar, backgroundImage on Hero, icon on FeatureCard, illustration
    # on EmptyStateRich. A post-pass enricher retrofits any omissions, but
    # this directive gets the LLM to set them upstream.
    prompt += "\n\n" + RICH_VISUALS

    # Phase 15 reference grounding — domain-aware few-shot exemplars
    if REFERENCE_GROUNDING_ENABLED and page_brief is not None and domain:
        # page_brief is a dict with 'route' and optionally 'role';
        # wrap it in a tiny shim that infer_page_type accepts
        class _Shim:
            def __init__(self, d: dict) -> None:
                self.route = d.get("route", "")
                self.role = d.get("role")
        _inferred_page_type = infer_page_type(_Shim(page_brief))

        # Read register from design-spec so exemplar lookup uses the right tier.
        # Falls back to "default" if design-spec has no register field yet.
        _register = design_spec.get("register", "default")

        exemplars = load_exemplars(domain, _inferred_page_type, register=_register, limit=2)
        if not exemplars:
            exemplars = load_exemplars("general", _inferred_page_type, register=_register, limit=2)
        block = render_exemplars_block(exemplars)
        if block:
            prompt += "\n\n" + block

    # Enterprise pattern gold example — injected after reference exemplars so the
    # archetype-specific template is the last thing the LLM sees before its task.
    enterprise_pattern = load_enterprise_pattern(
        page_brief.get("role", "") if page_brief else ""
    )
    if enterprise_pattern:
        prompt += "\n\n## ENTERPRISE PATTERN (gold example for this archetype)\n\n"
        prompt += "```json\n"
        prompt += json.dumps(enterprise_pattern, indent=2)
        prompt += "\n```\n"
        prompt += "Adapt this structure to the specific entities + brief above.\n"

    # Progressive disclosure (binding) — injected before the CTA block so that
    # CTA stays last for recency. The rule block teaches the LLM the container-
    # choice taxonomy; the inlined exemplar (for form/detail page types) shows
    # what a correct partitioned schema looks like.
    # Auth-shaped routes (/login etc.) route to the auth-split-illustration
    # exemplar regardless of page_type — _exemplar_for handles the precedence.
    route = (page_brief or {}).get("route", "") or (plan.get("page") or {}).get("route", "")
    exemplar = _exemplar_for(page_type, route=route)
    if exemplar:
        prompt += (
            "\n" + PROGRESSIVE_DISCLOSURE_RULES
            + f"\n### Exemplar ({page_type}):\n```json\n{exemplar}\n```\n"
        )
    else:
        prompt += "\n" + PROGRESSIVE_DISCLOSURE_RULES + "\n"

    # Rules-as-data (Task 20) — emits each Rule from services.schema_rules
    # inline with its example_snippet. Sits BETWEEN progressive disclosure
    # (above) and CTA hierarchy (below) so CTA stays last for recency.
    # The existing monolithic rules text earlier in the prompt is NOT
    # removed — this is additive while the proximity structure is proven.
    rules_block = _emit_rules_block(entity if isinstance(entity, dict) else {}, page_type)
    if rules_block:
        prompt += "\n" + rules_block + "\n"

    # CTA hierarchy (binding) — injected last so it appears after all structural
    # guidance and few-shot examples, making it the freshest instruction the LLM
    # sees.  Variant names + counts come from design_spec.cta_hierarchy so
    # register switches propagate without prompt rewrites.
    cta = design_spec.get("cta_hierarchy") or defaults_for_register(
        design_spec.get("register", "default")
    )
    primary_variant = cta["primary"]["variant"]
    secondary_variant = cta["secondary"]["variant"]
    tertiary_variant = cta["tertiary"]["variant"]
    secondary_max = cta["secondary"]["max_per_page"]

    cta_block = f"""
## CTA hierarchy (binding)

- Every page MUST have exactly 1 Button with variant="{primary_variant}". This is
  the primary CTA; place it where visual weight expects it (hero, top-right of
  the page, or form submit area).
- Use variant="{secondary_variant}" for follow-up actions. Cap: {secondary_max} per page.
- Use variant="{tertiary_variant}" for tertiary / inline actions (no limit).
- Form pages: the form's submit button counts as the primary CTA.

Examples:
  PAGE HEADER:
    {{ "type": "Button", "props": {{ "label": "New Task", "variant": "{primary_variant}", "icon": "plus" }} }}
  ROW ACTION (in a Repeat over rows):
    {{ "type": "Button", "props": {{ "label": "View", "variant": "{tertiary_variant}", "navigate": "/tasks/{{{{item.id}}}}" }} }}
"""
    prompt += "\n" + cta_block

    # Page-type template (last block before token-budget check — recency
    # bias means the LLM treats this as the strongest instruction).
    # Archetype wins over the legacy page_type when present; falls through
    # to generic when both are missing or "generic".
    _arch = (page_brief or {}).get("archetype") or (plan.get("page") or {}).get("archetype")
    _page_type = (page_brief or {}).get("page_type") or plan.get("page_type") or "generic"
    _template_key = _arch or _page_type
    if _template_key and _template_key != "generic":
        from services.page_type_templates import template_for
        prompt += "\n\n" + template_for(_template_key)

    # Token-budget warning (Task 20) — proximity training expands the prompt;
    # log once when we cross the 25k-token budget so we know to trim rule
    # examples or disable rules via SCHEMA_RULES_DISABLED.
    APPROX_CHARS_PER_TOKEN = 4
    TOKEN_BUDGET = 25_000
    if len(prompt) > TOKEN_BUDGET * APPROX_CHARS_PER_TOKEN:
        logger.warning(
            "[schema_prompt] prompt is %d approx tokens (budget %d). "
            "Consider trimming rule examples or disabling rules via "
            "SCHEMA_RULES_DISABLED.",
            len(prompt) // APPROX_CHARS_PER_TOKEN,
            TOKEN_BUDGET,
        )

    return prompt
