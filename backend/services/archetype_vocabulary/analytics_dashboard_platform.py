"""Analytics-dashboard-platform vocabulary — Metabase / Amplitude /
Looker / Mixpanel / Tableau-like pure BI (not embedded analytics).

Shape mirrors the other archetype vocabs. Values are the conventions
every real BI product commits to that a generator would otherwise
re-invent.

Design decisions worth naming:

  - **Dashboards use card-grid.** A dashboard directory is browse-by-
    identity (title + thumbnail + owner) — card-grid is right; table
    would waste the visual metaphor a BI tool trades on.

  - **Saved queries use card-list.** A "your queries" view is one
    row per query with the name + description + last-run — card-list
    with a light inline action beats table density here.

  - **Reports + datasets + users stay a table.** Bulk admin work
    (schedule, permission, deprecate) — comparison across columns.

  - **Query runs / report runs use ledger-list.** Append-only history
    stream — timestamp + duration + status per row.

  - **Datasources use card-grid.** Connection tiles the reader picks
    from ("Postgres — analytics-prod", "S3 — events-2024").

  - **Empty-state copy is matter-of-fact utility** — BI tools carry
    professional-neutral tone; warmth reads as tone-deaf when the
    reader is grinding through a metric.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


ANALYTICS_DASHBOARD_PLATFORM = ArchetypeVocabulary(
    id="analytics-dashboard-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Analyst — authors dashboards + queries + reports on datasets.
        "analyst":       ["dashboards", "queries", "reports", "datasets"],
        "data_analyst":  ["dashboards", "queries", "reports", "datasets"],

        # Viewer / business user — reads dashboards; no authoring.
        "viewer":         ["dashboards", "favorites", "shared-with-me"],
        "business_user":  ["dashboards", "favorites", "shared-with-me"],

        # Admin — the whole platform.
        "admin":     ["dashboard", "users", "datasources", "permissions", "collections"],
        "bi_admin":  ["dashboard", "users", "datasources", "permissions", "collections"],

        # Data engineer — pipeline surface (sources + models + jobs).
        "data_engineer":  ["datasets", "datasources", "models", "jobs"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Dashboards splits — the standard BI "your stuff" pattern.
        "dashboards":       ["mine", "shared-with-me", "recently-viewed"],

        # Saved queries splits.
        "queries":          ["mine", "shared", "scheduled"],
        "saved_queries":    ["mine", "shared", "scheduled"],

        # Reports lifecycle.
        "reports":          ["scheduled", "past-runs", "failed"],

        # Datasets curation lifecycle.
        "datasets":         ["curated", "raw", "deprecated"],

        # Datasources connection state.
        "datasources":      ["connected", "disconnected", "failed"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Dashboards — the browsing catalog.
        "dashboards":       ComponentPreference(shape="card-grid",
                                                 primary_field="title"),

        # Saved queries — "your queries" list.
        "queries":          ComponentPreference(shape="card-list",
                                                 primary_field="name"),
        "saved_queries":    ComponentPreference(shape="card-list",
                                                 primary_field="name"),

        # Reports — admin ops table.
        "reports":          ComponentPreference(shape="table",
                                                 primary_field="name"),

        # Datasets / tables — admin ops table.
        "datasets":         ComponentPreference(shape="table",
                                                 primary_field="name"),
        "tables":           ComponentPreference(shape="table",
                                                 primary_field="name"),

        # Datasources / connections — tile grid.
        "datasources":      ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
        "connections":      ComponentPreference(shape="card-grid",
                                                 primary_field="name"),

        # Collections / folders — content organiser tiles.
        "collections":      ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
        "folders":          ComponentPreference(shape="card-grid",
                                                 primary_field="name"),

        # Query / report runs — append-only history ledger.
        "query_runs":       ComponentPreference(shape="ledger-list",
                                                 primary_field="queryName"),
        "report_runs":      ComponentPreference(shape="ledger-list",
                                                 primary_field="queryName"),

        # Users — admin bulk-ops table.
        "users":            ComponentPreference(shape="table",
                                                 primary_field="email",
                                                 context="admin"),
    },

    # ── Empty states — matter-of-fact utility ──────────────────────
    signature_states={
        # Screen headliners.
        "empty_dashboards":     "No dashboards yet. Create one to start "
                                 "visualizing your data.",
        "empty_queries":        "No saved queries yet. Save one to reuse "
                                 "or share.",
        "empty_saved_queries":  "No saved queries yet. Save one to reuse "
                                 "or share.",
        "empty_datasources":    "No data sources connected. Connect one "
                                 "to start exploring.",
        "empty_datasets":       "No datasets yet. Curate one from a data "
                                 "source to get started.",
        "empty_reports":        "No reports scheduled. Schedule one to "
                                 "deliver a query on cadence.",
        "empty_favorites":      "No favorites yet. Star a dashboard to "
                                 "pin it here.",
        "empty_collections":    "No collections yet.",
        "empty_permissions":    "No custom permissions set.",
        "empty_models":         "No models defined yet.",
        "empty_jobs":           "No jobs configured.",
        "empty_users":          "No users provisioned yet.",
        "empty_dashboard":      "No activity yet. Metrics will populate "
                                 "here once queries run.",

        # Per-section splits.
        "empty_mine":               "You haven't created any yet.",
        "empty_shared_with_me":     "Nothing has been shared with you yet.",
        "empty_recently_viewed":    "No recent activity.",
        "empty_shared":             "Nothing shared yet.",
        "empty_scheduled":          "Nothing scheduled to run.",
        "empty_past_runs":          "No past runs recorded.",
        "empty_failed":             "No failed runs — clean state.",
        "empty_curated":            "No curated datasets yet.",
        "empty_raw":                "No raw datasets registered.",
        "empty_deprecated":         "Nothing deprecated.",
        "empty_connected":          "No connected sources yet.",
        "empty_disconnected":       "No disconnected sources.",

        # Filtered-out state.
        "no_results":       "No matches for the current filter. Try "
                             "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Dashboards / queries splits — ownership + share visibility;
        # runtime enforces upstream (ownership isn't a status column).
        "mine":                 {},
        "shared-with-me":       {},
        "recently-viewed":      {},
        "shared":               {},
        "scheduled":            {"status": ["scheduled", "active"]},
        "past-runs":            {},

        # Reports lifecycle.
        "failed":               {"status": ["failed", "error"]},

        # Datasets curation.
        "curated":              {"status": ["curated", "certified"]},
        "raw":                  {"status": ["raw", "uncurated"]},
        "deprecated":           {"status": ["deprecated", "archived"]},

        # Datasource state.
        "connected":            {"status": ["connected", "active", "healthy"]},
        "disconnected":         {"status": ["disconnected", "inactive"]},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        # Publish / lifecycle state.
        "draft":            {"variant": "neutral", "label": "Draft"},
        "published":        {"variant": "success", "label": "Published"},
        "scheduled":        {"variant": "accent",  "label": "Scheduled"},
        "failed":           {"variant": "danger",  "label": "Failed"},
        "error":            {"variant": "danger",  "label": "Error"},

        # Connection state.
        "connected":        {"variant": "success", "label": "Connected"},
        "disconnected":     {"variant": "warning", "label": "Disconnected"},
        "inactive":         {"variant": "warning", "label": "Inactive"},
        "healthy":          {"variant": "success", "label": "Healthy"},

        # Dataset curation.
        "deprecated":       {"variant": "neutral", "label": "Deprecated"},
        "curated":          {"variant": "accent",  "label": "Curated"},
        "certified":        {"variant": "accent",  "label": "Certified"},

        # Runs.
        "running":          {"variant": "warning", "label": "Running"},
        "succeeded":        {"variant": "success", "label": "Succeeded"},
    },

    # The person who owns a BI platform doesn't open it to look at
    # charts — they open it to find out which delivery broke overnight.
    # A silently failed scheduled report and a dropped connection are
    # how a BI tool loses trust, so both lead. Query runtime is here
    # because slow is the failure mode analysts complain about instead
    # of reporting.
    dashboard_recipe={
        "kpis": [
            {"label": "Failed runs",        "entity": "report_runs",
             "op": "count", "filter": {"status": ["failed", "error"]}},
            {"label": "Sources offline",    "entity": "datasources",
             "op": "count", "filter": {"status": ["disconnected", "inactive"]}},
            {"label": "Scheduled reports",  "entity": "reports",
             "op": "count", "filter": {"status": ["scheduled"]}},
            {"label": "Deprecated datasets", "entity": "datasets",
             "op": "count", "filter": {"status": ["deprecated"]}},
            {"label": "Avg query time",     "entity": "query_runs",
             "op": "avg", "field": "durationMs"},
            {"label": "Published dashboards", "entity": "dashboards",
             "op": "count", "filter": {"status": ["published"]}},
        ],
        "sections": [
            # Failed deliveries first: every one of these is a person
            # who expected a number in their inbox and didn't get it.
            {"title": "Failed report runs", "entity": "report_runs",
             "shape": "ledger-list", "filter": {"status": ["failed", "error"]},
             "limit": 8},

            # A dead connection makes every dashboard downstream of it
            # quietly wrong, which is worse than visibly broken.
            {"title": "Data sources needing attention", "entity": "datasources",
             "shape": "card-grid",
             "filter": {"status": ["disconnected", "inactive"]}, "limit": 6},

            # The one genuinely browse-shaped strip on the page — every
            # BI product opens on a wall of dashboard tiles.
            {"title": "Dashboards", "entity": "dashboards",
             "shape": "card-grid", "limit": 8},
        ],
    },

    # Reading order per screen. BI rows answer "whose is it, where does
    # the data come from, did it run" — ownership and lineage are the
    # columns people actually scan, not row counts.
    page_recipes={
        "dashboards": {
            "list_columns": ["title", "owner", "collection", "status",
                             "chartCount", "lastViewedAt"],
            "filter_chips": ["status", "collection"],
            "detail_sections": [
                {"label": "Dashboard", "fields": ["title", "description",
                                                  "collection"]},
                {"label": "Ownership", "fields": ["owner", "status",
                                                  "createdAt", "updatedAt"]},
                {"label": "Usage",     "fields": ["viewCount", "lastViewedAt",
                                                  "chartCount"]},
            ],
        },
        "queries": {
            "list_columns": ["name", "datasource", "owner", "lastRunStatus",
                             "lastRunAt"],
            "filter_chips": ["datasource", "owner"],
            "detail_sections": [
                {"label": "Query",  "fields": ["name", "description", "sql"]},
                {"label": "Source", "fields": ["datasource", "dataset", "owner"]},
                {"label": "Runs",   "fields": ["lastRunAt", "lastRunStatus",
                                               "avgDurationMs"]},
            ],
        },
        "reports": {
            # Schedule + recipients sit next to the name because a
            # report's identity IS "what goes to whom, how often".
            "list_columns": ["name", "schedule", "recipients", "status",
                             "format", "lastRunAt"],
            "filter_chips": ["status", "schedule"],
            "detail_sections": [
                {"label": "Report",   "fields": ["name", "description", "query"]},
                {"label": "Delivery", "fields": ["schedule", "recipients",
                                                 "format", "status"]},
                {"label": "History",  "fields": ["lastRunAt", "lastRunStatus",
                                                 "nextRunAt"]},
            ],
        },
        "datasets": {
            "list_columns": ["name", "datasource", "status", "owner",
                             "rowCount", "updatedAt"],
            "filter_chips": ["status", "datasource"],
            "detail_sections": [
                {"label": "Dataset",  "fields": ["name", "description",
                                                 "datasource"]},
                {"label": "Curation", "fields": ["status", "owner", "certifiedBy"]},
                {"label": "Volume",   "fields": ["rowCount", "columnCount",
                                                 "updatedAt"]},
            ],
        },
        "datasources": {
            "list_columns": ["name", "type", "status", "host", "lastSyncedAt"],
            "filter_chips": ["status", "type"],
            "detail_sections": [
                {"label": "Connection", "fields": ["name", "type", "host",
                                                   "database"]},
                {"label": "Health",     "fields": ["status", "lastSyncedAt",
                                                   "lastError"]},
                {"label": "Access",     "fields": ["owner", "permissions",
                                                   "datasetCount"]},
            ],
        },
        "query_runs": {
            "list_columns": ["queryName", "status", "runBy", "durationMs",
                             "rowCount", "startedAt"],
            "filter_chips": ["status", "runBy"],
            "detail_sections": [
                {"label": "Run",    "fields": ["queryName", "status", "runBy"]},
                {"label": "Result", "fields": ["rowCount", "durationMs",
                                               "resultSize"]},
                {"label": "Timing", "fields": ["startedAt", "finishedAt"]},
            ],
        },
        "collections": {
            "list_columns": ["name", "owner", "itemCount", "visibility",
                             "updatedAt"],
            "filter_chips": ["visibility", "owner"],
            "detail_sections": [
                {"label": "Collection", "fields": ["name", "description",
                                                   "parentCollection"]},
                {"label": "Contents",   "fields": ["itemCount", "dashboardCount",
                                                   "queryCount"]},
                {"label": "Access",     "fields": ["owner", "visibility",
                                                   "updatedAt"]},
            ],
        },
        "users": {
            "list_columns": ["email", "name", "role", "status", "lastActiveAt"],
            "filter_chips": ["role", "status"],
            "detail_sections": [
                {"label": "Account",  "fields": ["name", "email", "role"]},
                {"label": "Access",   "fields": ["status", "groups", "permissions"]},
                {"label": "Activity", "fields": ["lastActiveAt", "dashboardCount",
                                                 "createdAt"]},
            ],
        },
    },
)
