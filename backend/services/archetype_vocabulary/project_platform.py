"""Project-platform vocabulary — projects, tasks, milestones, timesheets,
agency / consulting / PM apps. Jira / Linear / Asana / Basecamp shape.

Shape mirrors booking_platform / banking_platform. Reads as "what does
every project management app (Jira, Linear, Asana, ClickUp, Basecamp)
carry that a code generator would otherwise re-invent every time?"

Design decisions worth naming:

  - **Tasks use kanban.** The board IS the PM signature — todo →
    in-progress → review → done. Column-per-status is literal.

  - **Projects + team members use card-grid.** Portfolio of work,
    directory of people — browse by identity.

  - **Milestones use card-list.** Ordered "your things" — one card
    per milestone with due date + progress meter.

  - **Timesheets + messages use ledger-list.** Append-only history.

  - **Invoices use table.** Bulk billing work — comparison,
    sortable, exportable.

  - **Empty-state copy is matter-of-fact utility.** Project tools
    are work tools — no theatre.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


PROJECT_PLATFORM = ArchetypeVocabulary(
    id="project-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Individual contributor — task-driven surface.
        "contributor":   ["my-tasks", "assigned", "timesheets"],
        "team_member":   ["my-tasks", "assigned", "timesheets"],

        # PM — the operational spine of the app.
        "project_manager": ["projects", "tasks", "milestones", "team", "reports"],
        "pm":              ["projects", "tasks", "milestones", "team", "reports"],
        "manager":         ["projects", "tasks", "milestones", "team", "reports"],

        # Admin — user + client + settings.
        "admin":  ["dashboard", "users", "clients", "settings", "reports"],

        # Client — their-projects surface.
        "client": ["my-projects", "invoices", "messages"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Portfolio lifecycle.
        "projects":     ["active", "on-hold", "completed", "archived"],

        # Task board columns.
        "tasks":        ["todo", "in-progress", "review", "done"],

        # Contributor's own queue.
        "my-tasks":     ["today", "this-week", "overdue"],

        # Milestone lifecycle.
        "milestones":   ["upcoming", "reached", "missed"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Projects — visual grid.
        "projects":     ComponentPreference(shape="card-grid",
                                             primary_field="name"),

        # Tasks — kanban board.
        "tasks":        ComponentPreference(shape="kanban",
                                             primary_field="title"),
        "issues":       ComponentPreference(shape="kanban",
                                             primary_field="title"),

        # Milestones — ordered cards.
        "milestones":   ComponentPreference(shape="card-list",
                                             primary_field="name"),

        # Timesheets — append-only ledger.
        "timesheets":   ComponentPreference(shape="ledger-list",
                                             primary_field="taskTitle"),
        "time_entries": ComponentPreference(shape="ledger-list",
                                             primary_field="taskTitle"),

        # People / client directories.
        "team_members":  ComponentPreference(shape="card-grid",
                                              primary_field="fullName"),
        "contributors":  ComponentPreference(shape="card-grid",
                                              primary_field="fullName"),
        "clients":       ComponentPreference(shape="card-grid",
                                              primary_field="name"),

        # Invoices — bulk-billing table.
        "invoices":     ComponentPreference(shape="table",
                                             primary_field="invoiceNumber"),

        # Messages / comments — thread ledger.
        "messages":     ComponentPreference(shape="ledger-list",
                                             primary_field="body"),
        "comments":     ComponentPreference(shape="ledger-list",
                                             primary_field="body"),
    },

    # ── Empty states — matter-of-fact utility ─────────────────────
    signature_states={
        # Contributor surface.
        "empty_my_tasks":       "No tasks assigned to you.",
        "empty_assigned":       "Nothing assigned right now.",
        "empty_today":          "Nothing due today.",
        "empty_this_week":      "Nothing due this week.",
        "empty_overdue":        "No overdue tasks — you're on top of it.",
        "empty_timesheets":     "No time logged yet. Start a timer on a "
                                 "task to track your hours.",

        # PM surface.
        "empty_projects":       "No projects yet. Create your first "
                                 "project to start tracking work.",
        "empty_active":         "No active projects.",
        "empty_on_hold":        "No projects on hold.",
        "empty_completed":      "No completed projects in this window.",
        "empty_archived":       "Nothing archived yet.",
        "empty_tasks":          "No tasks yet. Add your first task to "
                                 "start moving work forward.",
        "empty_todo":           "Nothing in the todo column.",
        "empty_in_progress":    "Nothing in progress.",
        "empty_review":         "Nothing waiting on review.",
        "empty_done":           "Nothing done yet in this window.",
        "empty_milestones":     "No milestones set. Add one to mark a "
                                 "checkpoint.",
        "empty_upcoming":       "No upcoming milestones.",
        "empty_reached":        "No milestones reached yet.",
        "empty_missed":         "No missed milestones — you're on track.",
        "empty_team":           "No team members yet.",
        "empty_team_members":   "No team members assigned to this project.",

        # Client surface.
        "empty_my_projects":    "No projects yet. Your project manager "
                                 "will kick things off shortly.",
        "empty_invoices":       "No invoices yet.",
        "empty_messages":       "No messages yet. Conversations with your "
                                 "team will appear here.",

        # Admin.
        "empty_dashboard":      "No activity yet. Metrics populate as "
                                 "projects and tasks move.",
        "empty_users":          "No users provisioned yet.",
        "empty_clients":        "No clients on file yet.",
        "empty_settings":       "Nothing configured yet.",
        "empty_reports":        "No reports generated yet.",

        # Generic filtered-out state.
        "no_results":           "No matches for the current filter. Try "
                                 "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Project lifecycle.
        "active":       {"status": ["active", "in_progress", "open"]},
        "on-hold":      {"status": ["on_hold", "paused"]},
        "completed":    {"status": ["completed", "done", "closed"]},
        "archived":     {"status": ["archived"]},

        # Task board columns.
        "todo":         {"status": ["todo", "to_do", "backlog", "open"]},
        "in-progress":  {"status": ["in_progress", "doing", "started"]},
        "review":       {"status": ["review", "in_review", "code_review"]},
        "done":         {"status": ["done", "completed", "closed"]},

        # Contributor queue windows — no lifecycle filter (date-driven).
        "today":        {},
        "this-week":    {},
        "overdue":      {},

        # Milestone lifecycle.
        "upcoming":     {"status": ["upcoming", "planned", "scheduled"]},
        "reached":      {"status": ["reached", "achieved", "hit"]},
        "missed":       {"status": ["missed", "overdue", "slipped"]},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        # Task board.
        "todo":         {"variant": "neutral", "label": "Todo"},
        "in_progress":  {"variant": "warning", "label": "In progress"},
        "review":       {"variant": "accent",  "label": "Review"},
        "done":         {"variant": "success", "label": "Done"},
        "blocked":      {"variant": "danger",  "label": "Blocked"},

        # Project lifecycle.
        "on_hold":      {"variant": "warning", "label": "On hold"},
        "completed":    {"variant": "success", "label": "Completed"},
        "archived":     {"variant": "neutral", "label": "Archived"},

        # Cross-cutting.
        "overdue":      {"variant": "danger",  "label": "Overdue"},
        "upcoming":     {"variant": "warning", "label": "Upcoming"},
    },

    # A project lead opens the app to find the trouble, not the total.
    # Every KPI here is an exception the lead has to act on today —
    # what has slipped, what is stuck, what is waiting on a reviewer,
    # which milestone is about to be missed. "Total tasks" is a number
    # that never changes anyone's afternoon; overdue and blocked
    # counts are the two that start every stand-up. Hours logged is the
    # one volume metric that earns its tile, because agencies bill it.
    dashboard_recipe={
        "kpis": [
            {"label": "Overdue tasks",  "entity": "tasks",
             "op": "count", "filter": {"status": ["overdue"]}},
            {"label": "Blocked",        "entity": "tasks",
             "op": "count", "filter": {"status": ["blocked"]}},
            {"label": "In review",      "entity": "tasks",
             "op": "count", "filter": {"status": ["review"]}},
            {"label": "Projects in flight", "entity": "projects",
             "op": "count", "filter": {"status": ["in_progress"]}},
            {"label": "Milestones at risk", "entity": "milestones",
             "op": "count", "filter": {"status": ["overdue"]}},
            {"label": "Hours logged",   "entity": "timesheets",
             "op": "sum", "field": "hours"},
        ],
        "sections": [
            # Table, not the board: this section exists to be triaged
            # row by row (reassign, re-date, unblock), which is bulk
            # edit work — the board is for flow, not for triage.
            {"title": "Overdue and blocked work", "entity": "tasks",
             "shape": "table", "filter": {"status": ["overdue", "blocked"]},
             "limit": 8},
            {"title": "Upcoming milestones", "entity": "milestones",
             "shape": "card-list", "filter": {"status": ["upcoming"]},
             "limit": 6},
            {"title": "Recent time entries", "entity": "timesheets",
             "shape": "ledger-list", "limit": 10},
        ],
    },

    # Project lists are read as "what, whose, when" — the three things
    # asked in every status meeting. Assignee and due date therefore
    # outrank every descriptive field, and status sits beside them so a
    # slipping item is visible without opening it. Detail sections
    # follow the PM's own framing of a record: the work itself, who
    # owns it, and where it sits in the plan.
    page_recipes={
        "projects": {
            "list_columns": ["name", "client", "status", "owner",
                             "dueDate", "progress"],
            "filter_chips": ["status", "client", "owner"],
            "detail_sections": [
                {"label": "Project",  "fields": ["name", "description",
                                                 "client"]},
                {"label": "Schedule", "fields": ["startDate", "dueDate",
                                                 "status"]},
                {"label": "Team",     "fields": ["owner", "teamMembers",
                                                 "budget"]},
            ],
        },
        "tasks": {
            "list_columns": ["title", "project", "assignee", "status",
                             "priority", "dueDate"],
            "filter_chips": ["status", "priority", "assignee", "project"],
            "detail_sections": [
                {"label": "Task",       "fields": ["title", "description",
                                                   "priority"]},
                {"label": "Assignment", "fields": ["assignee", "status",
                                                   "dueDate"]},
                {"label": "Context",    "fields": ["project", "milestone",
                                                   "estimatedHours"]},
            ],
        },
        "milestones": {
            "list_columns": ["name", "project", "dueDate", "status", "owner"],
            "filter_chips": ["status", "project"],
            "detail_sections": [
                {"label": "Milestone", "fields": ["name", "description",
                                                  "project"]},
                {"label": "Schedule",  "fields": ["dueDate", "completedAt",
                                                  "status"]},
                {"label": "Scope",     "fields": ["owner", "deliverables"]},
            ],
        },
        "timesheets": {
            "list_columns": ["taskTitle", "project", "member", "date",
                             "hours", "billable"],
            "filter_chips": ["project", "member", "billable"],
            "detail_sections": [
                {"label": "Entry", "fields": ["taskTitle", "project",
                                              "notes"]},
                {"label": "Time",  "fields": ["date", "hours", "billable"]},
                {"label": "Who",   "fields": ["member", "approvedBy",
                                              "status"]},
            ],
        },
        "team_members": {
            "list_columns": ["fullName", "role", "email", "capacity",
                             "status"],
            "filter_chips": ["role", "status"],
            "detail_sections": [
                {"label": "Person",   "fields": ["fullName", "role", "email"]},
                {"label": "Workload", "fields": ["capacity", "allocatedHours",
                                                 "activeProjects"]},
            ],
        },
        "clients": {
            "list_columns": ["name", "contactName", "email", "status",
                             "owner"],
            "filter_chips": ["status", "owner"],
            "detail_sections": [
                {"label": "Client",     "fields": ["name", "industry",
                                                   "website"]},
                {"label": "Contact",    "fields": ["contactName", "email",
                                                   "phone"]},
                {"label": "Commercial", "fields": ["owner", "status",
                                                   "billingRate"]},
            ],
        },
        "invoices": {
            "list_columns": ["invoiceNumber", "client", "issueDate",
                             "dueDate", "amount", "status"],
            "filter_chips": ["status", "client"],
            "detail_sections": [
                {"label": "Invoice", "fields": ["invoiceNumber", "client",
                                                "project"]},
                {"label": "Amounts", "fields": ["amount", "tax", "total"]},
                {"label": "Dates",   "fields": ["issueDate", "dueDate",
                                                "paidAt"]},
            ],
        },
        "messages": {
            "list_columns": ["body", "author", "project", "sentAt"],
            "filter_chips": ["project", "author"],
            "detail_sections": [
                {"label": "Message", "fields": ["body", "author"]},
                {"label": "Context", "fields": ["project", "sentAt"]},
            ],
        },
    },
)
