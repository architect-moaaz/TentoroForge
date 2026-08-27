"""Dev-tools-platform vocabulary — GitHub Actions / Sentry / Grafana /
CircleCI / Datadog-like CI/CD + monitoring + incident-response tooling.

Shape mirrors the other archetype vocabs. Values are the conventions
every real observability / CI product commits to that a generator
would otherwise re-invent.

Design decisions worth naming:

  - **Builds + deployments use ledger-list.** Append-only run history
    with a status chip on the leading edge, mono-format branch / SHA
    columns, right-aligned duration. The signature of every CI UI.

  - **Errors + incidents use kanban.** Both flow through a triage
    pipeline (unresolved → in progress → resolved / ignored). Kanban
    makes the flow literal — same reason CRM deals and banking
    applications live on a kanban.

  - **Oncall shifts use schedule-grid.** Rotation timelines are a
    time-of-day view — schedule-grid is the shape the runtime
    already binds calendars against.

  - **Dashboards + projects + integrations use card-grid.** Browse-
    by-identity directories.

  - **Alerts stay a table** — rule catalog work, comparison across
    columns (severity / owner / recent-fires).

  - **Empty-state copy is matter-of-fact utility** — dev / SRE
    surfaces read as work tools; chirpy copy is tone-deaf when a
    reader is on-call at 3am.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


DEV_TOOLS_PLATFORM = ArchetypeVocabulary(
    id="dev-tools-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Developer / engineer — daily view: my builds, my deploys, my errors.
        "developer":    ["builds", "deployments", "errors", "alerts"],
        "engineer":     ["builds", "deployments", "errors", "alerts"],

        # SRE / ops / oncall — incidents + oncall + monitoring surface.
        "sre":      ["incidents", "alerts", "oncall", "dashboards"],
        "ops":      ["incidents", "alerts", "oncall", "dashboards"],
        "oncall":   ["incidents", "alerts", "oncall", "dashboards"],

        # Admin — platform config + users + audit.
        "admin":            ["dashboard", "users", "projects",
                              "integrations", "audit-log"],
        "platform_admin":   ["dashboard", "users", "projects",
                              "integrations", "audit-log"],

        # Viewer — read-only.
        "viewer":   ["dashboards", "errors"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Builds / CI runs lifecycle.
        "builds":       ["running", "passed", "failed", "cancelled"],
        "ci_runs":      ["running", "passed", "failed", "cancelled"],

        # Deployments lifecycle.
        "deployments":  ["succeeded", "in-progress", "rolled-back", "failed"],

        # Errors / issues triage — the sentry-style triage pipeline.
        "errors":       ["unresolved", "in-progress", "resolved", "ignored"],
        "issues":       ["unresolved", "in-progress", "resolved", "ignored"],

        # Alerts lifecycle.
        "alerts":       ["firing", "resolved", "silenced"],

        # Incidents lifecycle — the PagerDuty / statuspage split.
        "incidents":    ["open", "investigating", "monitoring", "resolved"],

        # Oncall rotations.
        "oncall":       ["current", "upcoming", "past"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Builds / CI runs — append-only history, mono-heavy.
        "builds":           ComponentPreference(shape="ledger-list",
                                                 primary_field="branchName"),
        "ci_runs":          ComponentPreference(shape="ledger-list",
                                                 primary_field="branchName"),
        "workflow_runs":    ComponentPreference(shape="ledger-list",
                                                 primary_field="branchName"),

        # Deployments — append-only history keyed on commit SHA.
        "deployments":      ComponentPreference(shape="ledger-list",
                                                 primary_field="commitSha"),

        # Errors / issues — triage pipeline.
        "errors":           ComponentPreference(shape="kanban",
                                                 primary_field="message"),
        "issues":           ComponentPreference(shape="kanban",
                                                 primary_field="message"),
        "exceptions":       ComponentPreference(shape="kanban",
                                                 primary_field="message"),

        # Alerts — rule catalog.
        "alerts":           ComponentPreference(shape="table",
                                                 primary_field="ruleName"),

        # Incidents — triage pipeline.
        "incidents":        ComponentPreference(shape="kanban",
                                                 primary_field="title"),

        # Oncall rotations — schedule grid.
        "oncall_shifts":    ComponentPreference(shape="schedule-grid",
                                                 primary_field="engineerName"),

        # Dashboards — browse directory.
        "dashboards":               ComponentPreference(shape="card-grid",
                                                         primary_field="name"),
        "monitoring_dashboards":    ComponentPreference(shape="card-grid",
                                                         primary_field="name"),

        # Projects / repos — browse directory.
        "projects":         ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
        "repositories":     ComponentPreference(shape="card-grid",
                                                 primary_field="name"),

        # Audit log — append-only ledger.
        "audit_log":        ComponentPreference(shape="ledger-list",
                                                 primary_field="action"),
        "audit_events":     ComponentPreference(shape="ledger-list",
                                                 primary_field="action"),
    },

    # ── Empty states — matter-of-fact utility ──────────────────────
    signature_states={
        # Screen headliners.
        "empty_builds":         "No builds yet. Push a commit to trigger "
                                 "the first run.",
        "empty_ci_runs":        "No CI runs yet. Push a commit to trigger "
                                 "the first run.",
        "empty_deployments":    "No deployments yet. Trigger one from a "
                                 "green build.",
        "empty_errors":         "No errors reported. Everything is healthy.",
        "empty_issues":         "No open issues. Everything is healthy.",
        "empty_alerts":         "No alerts firing. Configured monitors "
                                 "will surface here when triggered.",
        "empty_incidents":      "No open incidents. Alerts you page will "
                                 "show here.",
        "empty_oncall":         "Nobody on-call right now. Configure a "
                                 "rotation to page.",
        "empty_dashboards":     "No dashboards yet. Build one to visualise "
                                 "your metrics.",
        "empty_projects":       "No projects yet. Add one to start tracking.",
        "empty_integrations":   "No integrations connected.",
        "empty_audit_log":      "No audit events for this period yet.",
        "empty_users":          "No users provisioned yet.",
        "empty_dashboard":      "No activity yet. Metrics will populate "
                                 "here once agents start reporting.",

        # Per-section splits.
        "empty_running":        "Nothing running right now.",
        "empty_passed":         "No passing builds in this window.",
        "empty_failed":         "No failed builds — nice work.",
        "empty_cancelled":      "No cancelled builds.",
        "empty_succeeded":      "No successful deployments in this window.",
        "empty_in_progress":    "Nothing in progress right now.",
        "empty_rolled_back":    "No rollbacks recorded.",
        "empty_unresolved":     "No unresolved issues — all clear.",
        "empty_resolved":       "No resolved items in this window.",
        "empty_ignored":        "Nothing ignored.",
        "empty_firing":         "No alerts firing. All quiet.",
        "empty_silenced":       "No silenced alerts.",
        "empty_open":           "No open incidents. Nice work.",
        "empty_investigating":  "Nothing under investigation.",
        "empty_monitoring":     "Nothing in monitoring state.",
        "empty_current":        "Nobody on-call right now.",
        "empty_upcoming":       "No upcoming rotations scheduled.",
        "empty_past":           "No past rotations to show.",

        # Filtered-out state.
        "no_results":       "No matches for the current filter. Try "
                             "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Builds / CI runs lifecycle.
        "running":          {"status": ["running", "in_progress", "queued"]},
        "passed":           {"status": ["passed", "success", "succeeded"]},
        "failed":           {"status": ["failed", "failure", "error"]},
        "cancelled":        {"status": ["cancelled", "canceled", "aborted"]},

        # Deployments lifecycle.
        "succeeded":        {"status": ["succeeded", "success", "deployed"]},
        "in-progress":      {"status": ["in_progress", "deploying"]},
        "rolled-back":      {"status": ["rolled_back", "rolledback", "reverted"]},

        # Errors / issues triage.
        "unresolved":       {"status": ["unresolved", "open", "new"]},
        "resolved":         {"status": ["resolved", "closed", "fixed"]},
        "ignored":          {"status": ["ignored", "muted", "wontfix"]},

        # Alerts lifecycle.
        "firing":           {"status": ["firing", "alerting", "triggered"]},
        "silenced":         {"status": ["silenced", "snoozed"]},

        # Incidents lifecycle.
        "open":             {"status": ["open", "triggered"]},
        "investigating":    {"status": ["investigating", "identified"]},
        "monitoring":       {"status": ["monitoring", "recovering"]},

        # Oncall rotations — visual splits (date-driven).
        "current":          {},
        "upcoming":         {},
        "past":             {},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        # Builds / runs.
        "running":          {"variant": "warning", "label": "Running"},
        "queued":           {"variant": "warning", "label": "Queued"},
        "passed":           {"variant": "success", "label": "Passed"},
        "success":          {"variant": "success", "label": "Success"},
        "succeeded":        {"variant": "success", "label": "Succeeded"},
        "failed":           {"variant": "danger",  "label": "Failed"},
        "failure":          {"variant": "danger",  "label": "Failure"},
        "cancelled":        {"variant": "neutral", "label": "Cancelled"},
        "aborted":          {"variant": "neutral", "label": "Aborted"},

        # Deployments.
        "in_progress":      {"variant": "warning", "label": "In progress"},
        "deploying":        {"variant": "warning", "label": "Deploying"},
        "deployed":         {"variant": "success", "label": "Deployed"},
        "rolled_back":      {"variant": "danger",  "label": "Rolled back"},
        "reverted":         {"variant": "danger",  "label": "Reverted"},

        # Errors / issues.
        "unresolved":       {"variant": "danger",  "label": "Unresolved"},
        "resolved":         {"variant": "success", "label": "Resolved"},
        "ignored":          {"variant": "neutral", "label": "Ignored"},
        "wontfix":          {"variant": "neutral", "label": "Won't fix"},

        # Alerts.
        "firing":           {"variant": "danger",  "label": "Firing"},
        "alerting":         {"variant": "danger",  "label": "Alerting"},
        "silenced":         {"variant": "neutral", "label": "Silenced"},
        "snoozed":          {"variant": "neutral", "label": "Snoozed"},

        # Service health.
        "degraded":         {"variant": "warning", "label": "Degraded"},
        "healthy":          {"variant": "success", "label": "Healthy"},

        # Incidents.
        "open":             {"variant": "danger",  "label": "Open"},
        "investigating":    {"variant": "warning", "label": "Investigating"},
        "monitoring":       {"variant": "accent",  "label": "Monitoring"},
        "identified":       {"variant": "warning", "label": "Identified"},
    },

    # What an on-call engineer opens the app to see at 3am: what is
    # paging me, what is broken, and how long until CI tells me my fix
    # landed. "Total projects" is the number nobody in this business has
    # ever needed. Build duration earns a tile because a CI platform
    # that slows down is a platform people route around.
    dashboard_recipe={
        "kpis": [
            {"label": "Alerts firing",      "entity": "alerts",
             "op": "count", "filter": {"status": ["firing", "alerting"]}},
            {"label": "Open incidents",     "entity": "incidents",
             "op": "count", "filter": {"status": ["open"]}},
            {"label": "Failed builds",      "entity": "builds",
             "op": "count", "filter": {"status": ["failed", "failure"]}},
            {"label": "Unresolved errors",  "entity": "errors",
             "op": "count", "filter": {"status": ["unresolved", "open"]}},
            {"label": "Avg build time",     "entity": "builds",
             "op": "avg", "field": "durationSeconds"},
        ],
        "sections": [
            # Paging first — nothing on this page outranks a live alert.
            {"title": "Firing now", "entity": "alerts",
             "shape": "table", "filter": {"status": ["firing", "alerting"]},
             "limit": 6},

            # Incidents prefer kanban on their own screen; on a dashboard
            # a column board is unreadable at tile height, so the top
            # open incidents collapse to a list.
            {"title": "Open incidents", "entity": "incidents",
             "shape": "card-list", "filter": {"status": ["open"]}, "limit": 5},

            # "What changed?" is the second question of every incident;
            # the deploy stream is the answer, so it lives on the page
            # rather than a click away.
            {"title": "Recent deployments", "entity": "deployments",
             "shape": "ledger-list", "limit": 10},
        ],
    },

    # Reading order per screen. CI/observability rows are read
    # left-to-right as "which code, what happened, who owns it, how
    # long" — branch/commit lead because that is how an engineer
    # recognises their own run in a wall of them.
    page_recipes={
        "builds": {
            "list_columns": ["branchName", "commitSha", "status",
                             "triggeredBy", "duration", "startedAt"],
            "filter_chips": ["status", "project"],
            "detail_sections": [
                {"label": "Run",     "fields": ["branchName", "commitSha",
                                                "status", "triggeredBy"]},
                {"label": "Timing",  "fields": ["startedAt", "finishedAt",
                                                "duration"]},
                {"label": "Output",  "fields": ["logUrl", "artifacts",
                                                "testsPassed", "testsFailed"]},
            ],
        },
        "deployments": {
            "list_columns": ["environment", "commitSha", "status",
                             "deployedBy", "deployedAt"],
            "filter_chips": ["status", "environment"],
            "detail_sections": [
                {"label": "Release",  "fields": ["environment", "commitSha",
                                                 "version", "status"]},
                {"label": "Timing",   "fields": ["deployedAt", "duration"]},
                {"label": "Rollback", "fields": ["rolledBackAt", "rollbackReason",
                                                 "previousVersion"]},
            ],
        },
        "errors": {
            # Occurrence count is the triage signal — a one-off and a
            # 40k-event storm are different jobs, so it sits in the list.
            "list_columns": ["message", "level", "status",
                             "occurrenceCount", "lastSeenAt", "assignee"],
            "filter_chips": ["status", "level", "project"],
            "detail_sections": [
                {"label": "Error",       "fields": ["message", "level",
                                                    "errorType", "status"]},
                {"label": "Occurrences", "fields": ["occurrenceCount",
                                                    "firstSeenAt", "lastSeenAt",
                                                    "affectedUsers"]},
                {"label": "Triage",      "fields": ["assignee", "project",
                                                    "environment", "resolvedAt"]},
            ],
        },
        "incidents": {
            "list_columns": ["title", "severity", "status", "commander",
                             "startedAt", "resolvedAt"],
            "filter_chips": ["status", "severity"],
            "detail_sections": [
                {"label": "Incident", "fields": ["title", "severity",
                                                 "status", "description"]},
                {"label": "Response", "fields": ["commander", "responders",
                                                 "escalationPolicy"]},
                {"label": "Timeline", "fields": ["startedAt", "acknowledgedAt",
                                                 "resolvedAt", "durationMinutes"]},
            ],
        },
        "alerts": {
            "list_columns": ["ruleName", "severity", "status", "target",
                             "threshold", "lastFiredAt"],
            "filter_chips": ["status", "severity"],
            "detail_sections": [
                {"label": "Rule",    "fields": ["ruleName", "description",
                                                "query", "threshold"]},
                {"label": "Routing", "fields": ["severity", "notificationChannel",
                                                "owner"]},
                {"label": "History", "fields": ["lastFiredAt", "fireCount",
                                                "status"]},
            ],
        },
        "oncall_shifts": {
            # Who, not when: the reader is checking whether the name on
            # the pager is theirs.
            "list_columns": ["engineerName", "rotation", "startsAt",
                             "endsAt", "escalationLevel"],
            "filter_chips": ["rotation", "escalationLevel"],
            "detail_sections": [
                {"label": "Shift",   "fields": ["engineerName", "rotation",
                                                "escalationLevel"]},
                {"label": "Window",  "fields": ["startsAt", "endsAt", "timezone"]},
                {"label": "Contact", "fields": ["phone", "email",
                                                "notificationMethod"]},
            ],
        },
        "projects": {
            "list_columns": ["name", "repositoryUrl", "defaultBranch",
                             "owner", "lastBuildStatus"],
            "filter_chips": ["owner", "language"],
            "detail_sections": [
                {"label": "Project",    "fields": ["name", "description", "owner"]},
                {"label": "Repository", "fields": ["repositoryUrl",
                                                   "defaultBranch", "language"]},
                {"label": "Health",     "fields": ["lastBuildStatus",
                                                   "openErrorCount",
                                                   "lastDeployedAt"]},
            ],
        },
        "audit_log": {
            "list_columns": ["action", "actor", "resource", "createdAt",
                             "ipAddress"],
            "filter_chips": ["action", "actor"],
            "detail_sections": [
                {"label": "Event", "fields": ["action", "resource", "result",
                                              "createdAt"]},
                {"label": "Actor", "fields": ["actor", "ipAddress", "userAgent"]},
            ],
        },
    },
)
