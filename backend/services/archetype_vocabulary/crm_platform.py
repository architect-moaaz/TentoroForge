"""CRM-platform vocabulary — sales pipelines, contacts, deals, activities.

Shape mirrors booking_platform / banking_platform. Reads as "what does
every CRM (Salesforce/HubSpot/Pipedrive/Close) do that a code generator
would otherwise re-invent every time?"

Design decisions worth naming:

  - **Deals use kanban.** A deal pipeline is the CRM signature move —
    every real CRM promotes deals to a column-per-stage board. Kanban
    is in KNOWN_SHAPES so the composer branches on it directly.

  - **Contacts + Companies use card-grid.** People/company directories
    are "browse by identity" tasks (avatar + name + primary meta),
    not comparison across rows.

  - **Activities use ledger-list.** Activities are an append-only
    history — a call log, an email log, a meeting log. Ledger-list
    matches: right-aligned timestamp, category chip, dense row.

  - **Tasks stay a table.** Bulk operational work (assign, due-date,
    complete) is comparison + edit work, not a browse-a-directory
    task. Table is right.

  - **Empty-state copy is matter-of-fact utility** — CRM is a work
    tool; warmth reads as tone-deaf when the user is chasing a quota.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


CRM_PLATFORM = ArchetypeVocabulary(
    id="crm-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Individual sales rep — daily work is deals + contacts + follow-ups.
        "salesperson":       ["deals", "contacts", "activities", "tasks"],
        "sales_rep":         ["deals", "contacts", "activities", "tasks"],
        "ae":                ["deals", "contacts", "activities", "tasks"],
        "account_executive": ["deals", "contacts", "activities", "tasks"],
        "account_manager":   ["deals", "contacts", "activities", "tasks"],

        # Sales manager — team view + reporting + configuration of products.
        "sales_manager": ["dashboard", "pipeline", "team", "reports", "products"],
        "manager":       ["dashboard", "pipeline", "team", "reports", "products"],

        # Admin — user provisioning + pipeline configuration + product catalog.
        "admin":         ["dashboard", "users", "products", "pipelines", "settings"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Deals split by pipeline outcome — the universal CRM triple.
        "deals":       ["open", "won", "lost"],

        # Activities split by urgency window — the "what's on my plate"
        # convention every CRM carries.
        "activities":  ["today", "upcoming", "overdue"],

        # Contact triage split — the temperature buckets sales orgs use.
        "contacts":    ["hot", "warm", "cold"],

        # Manager pipeline breakdowns — by stage or by owner.
        "pipeline":    ["by-stage", "by-owner"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Deals — the pipeline. Kanban makes the flow literal.
        "deals":            ComponentPreference(shape="kanban",
                                                 primary_field="name"),
        "opportunities":    ComponentPreference(shape="kanban",
                                                 primary_field="name"),

        # People directories.
        "contacts":         ComponentPreference(shape="card-grid",
                                                 primary_field="fullName"),
        "leads":            ComponentPreference(shape="card-grid",
                                                 primary_field="fullName"),
        "companies":        ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
        "accounts":         ComponentPreference(shape="card-grid",
                                                 primary_field="name"),

        # Activities — append-only history.
        "activities":       ComponentPreference(shape="ledger-list",
                                                 primary_field="subject"),
        "activity_log":     ComponentPreference(shape="ledger-list",
                                                 primary_field="subject"),
        "call_logs":        ComponentPreference(shape="ledger-list",
                                                 primary_field="subject"),
        "email_logs":       ComponentPreference(shape="ledger-list",
                                                 primary_field="subject"),

        # Tasks — bulk-edit work.
        "tasks":            ComponentPreference(shape="table",
                                                 primary_field="title"),

        # Product catalog — browse by identity.
        "products":         ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
    },

    # ── Empty states — matter-of-fact utility, no warmth theatre ────
    signature_states={
        # Deals surface.
        "empty_deals":          "No deals in the pipeline yet. Add your "
                                 "first opportunity to start tracking.",
        "empty_open":           "No open deals right now.",
        "empty_won":            "No closed-won deals yet — the first one "
                                 "lands here when a deal closes.",
        "empty_lost":           "No lost deals recorded.",

        # Contacts surface.
        "empty_contacts":       "No contacts yet. Import a list or add "
                                 "your first contact to get started.",
        "empty_hot":            "No hot leads right now.",
        "empty_warm":           "No warm leads at the moment.",
        "empty_cold":           "No cold contacts flagged for outreach.",

        # Activities surface.
        "empty_activities":     "No activity logged yet. Calls, emails, "
                                 "and meetings will appear here.",
        "empty_today":          "Nothing scheduled today. Your queue is clear.",
        "empty_upcoming":       "No upcoming activity.",
        "empty_overdue":        "No overdue tasks — nice work.",

        # Tasks surface.
        "empty_tasks":          "No open tasks.",

        # Pipeline / manager.
        "empty_pipeline":       "No deals in the pipeline yet.",
        "empty_by_stage":       "No deals grouped by stage yet.",
        "empty_by_owner":       "No deals to break down by owner.",

        # Companies / accounts.
        "empty_companies":      "No companies on file. Add your first "
                                 "account to start tracking relationships.",
        "empty_accounts":       "No accounts assigned yet.",
        "empty_leads":          "No leads yet. New submissions land here.",

        # Admin.
        "empty_dashboard":      "No pipeline activity yet. Metrics will "
                                 "populate as deals start moving.",
        "empty_products":       "No products in the catalog. Add your first "
                                 "product to attach to deals.",
        "empty_pipelines":      "No pipelines configured yet.",
        "empty_users":          "No users provisioned yet.",
        "empty_team":           "No team members yet.",
        "empty_reports":        "No reports available yet.",
        "empty_settings":       "Nothing configured yet.",

        # Generic filtered-out state.
        "no_results":           "No matches for the current filter. Try "
                                 "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Deals lifecycle — universal CRM stages.
        "open":         {"status": ["open", "in_progress", "active", "qualified"]},
        "won":          {"status": ["won", "closed_won", "closedwon", "closed-won"]},
        "lost":         {"status": ["lost", "closed_lost", "closedlost", "closed-lost"]},

        # Contact temperature.
        "hot":          {"status": ["hot", "engaged"]},
        "warm":         {"status": ["warm", "nurture"]},
        "cold":         {"status": ["cold", "dormant"]},

        # Activities urgency — no lifecycle filter (date-driven, runtime
        # doesn't support ranges yet). Visual split only.
        "today":        {},
        "upcoming":     {},
        "overdue":      {},

        # Pipeline breakdowns — no shared status filter; grouped upstream.
        "by-stage":     {},
        "by-owner":     {},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        # Deals lifecycle.
        "open":             {"variant": "warning", "label": "Open"},
        "in_progress":      {"variant": "warning", "label": "In progress"},
        "won":              {"variant": "success", "label": "Won"},
        "closed_won":       {"variant": "success", "label": "Closed-won"},
        "lost":             {"variant": "danger",  "label": "Lost"},
        "closed_lost":      {"variant": "danger",  "label": "Closed-lost"},
        "qualified":        {"variant": "success", "label": "Qualified"},
        "disqualified":     {"variant": "neutral", "label": "Disqualified"},

        # Contact temperature.
        "hot":              {"variant": "danger",  "label": "Hot"},
        "warm":             {"variant": "warning", "label": "Warm"},
        "cold":             {"variant": "neutral", "label": "Cold"},
    },

    # A sales team opens the CRM to answer one question: am I going to
    # hit the number? That makes the headline a *value*, not a count —
    # open pipeline in currency is the metric the whole business runs
    # on, and "total contacts" is the metric nobody has ever acted on.
    # The rest are the pressure points: what's still open, what already
    # closed, which leads are warm enough to call today, and what the
    # rep is late on. Deals lead as a kanban because the board IS the
    # pipeline (see component_preferences) — a dashboard that flattens
    # it into a table throws away the only view reps trust.
    dashboard_recipe={
        "kpis": [
            {"label": "Open pipeline",   "entity": "deals",
             "op": "sum", "field": "amount",
             "filter": {"status": ["open", "in_progress", "qualified"]}},
            {"label": "Open deals",      "entity": "deals",
             "op": "count",
             "filter": {"status": ["open", "in_progress", "qualified"]}},
            {"label": "Deals won",       "entity": "deals",
             "op": "count", "filter": {"status": ["won", "closed_won"]}},
            {"label": "Average deal size", "entity": "deals",
             "op": "avg", "field": "amount"},
            {"label": "Hot leads",       "entity": "leads",
             "op": "count", "filter": {"status": ["hot"]}},
            {"label": "Open tasks",      "entity": "tasks",
             "op": "count", "filter": {"status": ["open", "in_progress"]}},
        ],
        "sections": [
            {"title": "Open pipeline", "entity": "deals", "shape": "kanban",
             "filter": {"status": ["open", "in_progress", "qualified"]},
             "limit": 12},
            # Follow-ups are date-driven, not status-driven — same reason
            # section_filters leaves today/upcoming/overdue empty. The
            # ledger is already newest-first, which is the whole ask.
            {"title": "Recent activity", "entity": "activities",
             "shape": "ledger-list", "limit": 10},
            {"title": "Contacts to call", "entity": "contacts",
             "shape": "card-grid", "filter": {"status": ["hot", "warm"]},
             "limit": 6},
        ],
    },

    # Reading order is the rep's scan order: who/what, then whose money,
    # then how much, then when. Amount and close date earn their columns
    # because every pipeline conversation is "how much, by when" —
    # created-at never does, which is exactly what generic list builders
    # kept leading with. Detail sections mirror how a rep narrates a
    # deal in a pipeline review: the deal, the forecast, the ownership.
    page_recipes={
        "deals": {
            "list_columns": ["name", "company", "stage", "amount",
                             "closeDate", "owner"],
            "filter_chips": ["stage", "status", "owner"],
            "detail_sections": [
                {"label": "Deal",      "fields": ["name", "company", "stage",
                                                  "description"]},
                {"label": "Forecast",  "fields": ["amount", "probability",
                                                  "closeDate"]},
                {"label": "Ownership", "fields": ["owner", "source",
                                                  "nextStep"]},
            ],
        },
        "contacts": {
            "list_columns": ["fullName", "title", "company", "email",
                             "phone", "status"],
            "filter_chips": ["status", "company", "owner"],
            "detail_sections": [
                {"label": "Person",       "fields": ["fullName", "title",
                                                     "email", "phone"]},
                {"label": "Company",      "fields": ["company", "department",
                                                     "linkedinUrl"]},
                {"label": "Relationship", "fields": ["owner", "status",
                                                     "lastContactedAt"]},
            ],
        },
        "leads": {
            "list_columns": ["fullName", "company", "email", "source",
                             "status", "owner"],
            "filter_chips": ["status", "source", "owner"],
            "detail_sections": [
                {"label": "Lead",          "fields": ["fullName", "company",
                                                      "email", "phone"]},
                {"label": "Qualification", "fields": ["source", "status",
                                                      "score"]},
                {"label": "Ownership",     "fields": ["owner", "assignedAt"]},
            ],
        },
        "companies": {
            "list_columns": ["name", "industry", "size", "website", "owner"],
            "filter_chips": ["industry", "owner"],
            "detail_sections": [
                {"label": "Company",       "fields": ["name", "industry",
                                                      "website",
                                                      "description"]},
                {"label": "Firmographics", "fields": ["size", "revenue",
                                                      "location"]},
                {"label": "Relationship",  "fields": ["owner", "status",
                                                      "accountTier"]},
            ],
        },
        "activities": {
            "list_columns": ["subject", "type", "contact", "dueDate",
                             "owner", "status"],
            "filter_chips": ["type", "status", "owner"],
            "detail_sections": [
                {"label": "Activity",   "fields": ["subject", "type", "notes"]},
                {"label": "Related to", "fields": ["contact", "deal",
                                                   "company"]},
                {"label": "Scheduling", "fields": ["dueDate", "completedAt",
                                                   "owner"]},
            ],
        },
        "tasks": {
            "list_columns": ["title", "relatedTo", "assignee", "dueDate",
                             "priority", "status"],
            "filter_chips": ["status", "priority", "assignee"],
            "detail_sections": [
                {"label": "Task",       "fields": ["title", "description",
                                                   "priority"]},
                {"label": "Assignment", "fields": ["assignee", "dueDate",
                                                   "status"]},
                {"label": "Related to", "fields": ["relatedTo", "deal",
                                                   "contact"]},
            ],
        },
        "products": {
            "list_columns": ["name", "sku", "category", "price", "status"],
            "filter_chips": ["category", "status"],
            "detail_sections": [
                {"label": "Product", "fields": ["name", "sku", "category",
                                                "description"]},
                {"label": "Pricing", "fields": ["price", "currency",
                                                "discount"]},
            ],
        },
    },
)
