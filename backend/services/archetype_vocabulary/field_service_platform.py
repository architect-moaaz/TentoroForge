"""Field-service-platform vocabulary — jobs, work orders, technicians,
dispatch, HVAC / plumbing / on-site repair operations.

Shape mirrors booking_platform / banking_platform. Reads as "what does
every FSM (ServiceTitan, Jobber, Housecall Pro, FieldEdge) carry that
a code generator would otherwise re-invent every time?"

Design decisions worth naming:

  - **Jobs / work orders use kanban.** The dispatch board IS the FSM
    signature: unassigned → assigned → en-route → onsite → completed.
    Column-per-status is literal.

  - **Technicians / customers use card-grid.** Directories of people
    and accounts — browse by identity, not compare as rows.

  - **Parts + inventory items use table.** Bulk part-catalog work —
    dense columns, sortable, editable in place.

  - **Schedule uses schedule-grid.** Dispatcher's day view — jobs
    per technician column.

  - **Time entries / activity log use ledger-list.** Append-only.

  - **Empty-state copy is professional-calm utility.** Field techs
    are reading in a truck or on a job site — no theatre.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


FIELD_SERVICE_PLATFORM = ArchetypeVocabulary(
    id="field-service-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Technician — day-of-work surface.
        "technician":     ["my-jobs", "today", "parts", "checklists"],
        "tech":           ["my-jobs", "today", "parts", "checklists"],
        "field_engineer": ["my-jobs", "today", "parts", "checklists"],

        # Dispatcher — the board surface.
        "dispatcher":     ["dispatch-board", "unassigned", "technicians", "schedule"],

        # Service manager — operational overview.
        "service_manager": ["dashboard", "jobs", "technicians", "customers", "reports"],
        "manager":         ["dashboard", "jobs", "technicians", "customers", "reports"],

        # Customer — request + follow-up surface.
        "customer":       ["service-requests", "appointments", "history"],

        # Admin — configuration + reporting.
        "admin":          ["dashboard", "users", "products", "settings", "reports"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Job lifecycle.
        "jobs":         ["scheduled", "in-progress", "completed", "cancelled"],
        "work-orders":  ["scheduled", "in-progress", "completed", "cancelled"],

        # Dispatch board — the dispatcher's live view.
        "dispatch-board": ["unassigned", "assigned", "en-route", "onsite"],

        # Technician's own queue.
        "my-jobs":      ["today", "this-week", "completed"],

        # Parts sub-splits.
        "parts":        ["in-stock", "on-order", "used"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Jobs / work orders — kanban dispatch board.
        "jobs":             ComponentPreference(shape="kanban",
                                                 primary_field="subject"),
        "work_orders":      ComponentPreference(shape="kanban",
                                                 primary_field="subject"),
        "service_requests": ComponentPreference(shape="kanban",
                                                 primary_field="subject"),

        # People directories.
        "technicians":      ComponentPreference(shape="card-grid",
                                                 primary_field="fullName"),
        "field_engineers":  ComponentPreference(shape="card-grid",
                                                 primary_field="fullName"),

        # Customer directory.
        "customers":        ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
        "accounts":         ComponentPreference(shape="card-grid",
                                                 primary_field="name"),

        # Parts catalog.
        "parts":            ComponentPreference(shape="table",
                                                 primary_field="partNumber"),
        "inventory_items":  ComponentPreference(shape="table",
                                                 primary_field="partNumber"),

        # Checklists / inspections.
        "checklists":       ComponentPreference(shape="card-list",
                                                 primary_field="title"),
        "inspections":      ComponentPreference(shape="card-list",
                                                 primary_field="title"),

        # Schedule — dispatcher's grid.
        "schedule":         ComponentPreference(shape="schedule-grid",
                                                 primary_field="jobSubject"),

        # Time entries / audit trail.
        "time_entries":     ComponentPreference(shape="ledger-list",
                                                 primary_field="technicianName"),
        "activity_log":     ComponentPreference(shape="ledger-list",
                                                 primary_field="technicianName"),
    },

    # ── Empty states — professional-calm utility ───────────────────
    signature_states={
        # Technician surface.
        "empty_my_jobs":         "No jobs assigned to you.",
        "empty_today":           "Nothing scheduled today.",
        "empty_this_week":       "No jobs on the schedule this week.",
        "empty_completed":       "No completed jobs in this window.",
        "empty_parts":           "No parts assigned to this job.",
        "empty_in_stock":        "No parts in stock.",
        "empty_on_order":        "No parts on order.",
        "empty_used":            "No parts used on this job yet.",
        "empty_checklists":      "No checklists for this job.",

        # Dispatcher surface.
        "empty_dispatch_board":  "No jobs on the board right now.",
        "empty_unassigned":      "No unassigned jobs — the board is clear.",
        "empty_assigned":        "No assigned jobs waiting to start.",
        "empty_en_route":        "No technicians en route.",
        "empty_onsite":          "No technicians onsite right now.",
        "empty_schedule":        "No jobs on the schedule.",

        # Job lifecycle.
        "empty_jobs":            "No jobs yet. Create your first work "
                                  "order to dispatch.",
        "empty_work_orders":     "No work orders yet. Create your first "
                                  "one to dispatch.",
        "empty_scheduled":       "No scheduled jobs.",
        "empty_in_progress":     "No jobs in progress.",
        "empty_cancelled":       "No cancelled jobs.",

        # Directories.
        "empty_technicians":     "No technicians on the roster. Add your "
                                  "first tech to start dispatching.",
        "empty_customers":       "No customers on file yet.",
        "empty_accounts":        "No accounts on file yet.",

        # Customer view.
        "empty_service_requests": "No open service requests.",
        "empty_appointments":     "No appointments booked.",
        "empty_history":          "No service history yet.",

        # Admin operational.
        "empty_dashboard":       "No activity yet. Metrics populate as "
                                  "jobs get dispatched.",
        "empty_users":           "No users provisioned yet.",
        "empty_products":        "No products in the catalog yet.",
        "empty_settings":        "Nothing configured yet.",
        "empty_reports":         "No reports generated yet.",
        "empty_time_entries":    "No time logged yet.",
        "empty_activity_log":    "No activity logged yet.",

        # Generic filtered-out state.
        "no_results":            "No matches for the current filter. Try "
                                  "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Job lifecycle.
        "scheduled":        {"status": ["scheduled", "booked"]},
        "in-progress":      {"status": ["in_progress", "onsite", "en_route"]},
        "completed":        {"status": ["completed", "done", "closed"]},
        "cancelled":        {"status": ["cancelled", "voided"]},

        # Dispatch board columns.
        "unassigned":       {"status": ["unassigned", "new", "open"]},
        "assigned":         {"status": ["assigned", "dispatched"]},
        "en-route":         {"status": ["en_route", "enroute", "on_the_way"]},
        "onsite":           {"status": ["onsite", "on_site", "in_progress"]},

        # Technician queue windows — no lifecycle filter (date-driven).
        "today":            {},
        "this-week":        {},

        # Parts sub-splits.
        "in-stock":         {"status": ["in_stock", "available"]},
        "on-order":         {"status": ["on_order", "ordered"]},
        "used":             {"status": ["used", "consumed"]},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        # Job lifecycle.
        "scheduled":        {"variant": "warning", "label": "Scheduled"},
        "en_route":         {"variant": "warning", "label": "En route"},
        "onsite":           {"variant": "warning", "label": "Onsite"},
        "in_progress":      {"variant": "warning", "label": "In progress"},
        "completed":        {"variant": "success", "label": "Completed"},
        "cancelled":        {"variant": "neutral", "label": "Cancelled"},
        "escalated":        {"variant": "danger",  "label": "Escalated"},
        "no_access":        {"variant": "danger",  "label": "No access"},
        "no-access":        {"variant": "danger",  "label": "No access"},
        "awaiting_parts":   {"variant": "warning", "label": "Awaiting parts"},
        "awaiting-parts":   {"variant": "warning", "label": "Awaiting parts"},
    },

    # What a dispatcher opens the app to see. The board answers "where
    # is everyone" on its own; the tiles answer "what won't happen today
    # unless I touch it". So the queue waiting to be dispatched leads,
    # then the two ways a job dies quietly — escalated and blocked on a
    # part — before the live in-motion counts. En route and onsite are
    # reassurance, not decisions, which is why they sit last.
    dashboard_recipe={
        "kpis": [
            {"label": "To dispatch",   "entity": "jobs",
             "op": "count", "filter": {"status": ["scheduled"]}},
            {"label": "Escalated",     "entity": "jobs",
             "op": "count", "filter": {"status": ["escalated"]}},
            {"label": "Awaiting parts", "entity": "jobs",
             "op": "count", "filter": {"status": ["awaiting_parts",
                                                  "awaiting-parts"]}},
            {"label": "En route",      "entity": "jobs",
             "op": "count", "filter": {"status": ["en_route"]}},
            {"label": "Onsite",        "entity": "jobs",
             "op": "count", "filter": {"status": ["onsite", "in_progress"]}},
        ],
        "sections": [
            # The board is the dispatcher's whole job; it gets the room.
            {"title": "Dispatch board", "entity": "jobs",
             "shape": "kanban", "limit": 12},
            {"title": "Blocked on parts", "entity": "jobs", "shape": "table",
             "filter": {"status": ["awaiting_parts", "awaiting-parts"]},
             "limit": 6},
            {"title": "Technicians", "entity": "technicians",
             "shape": "card-grid", "limit": 8},
        ],
    },

    # What each screen SHOWS. Field service is dispatched over the phone,
    # so every job-shaped list leads with the number a dispatcher reads
    # aloud, then the one-line subject, then the two facts that decide
    # everything else: which customer, which tech. Site address lives on
    # the record rather than the list — the tech needs it, the board
    # doesn't. Parts carry on-hand beside reorder point for the same
    # reason inventory does: it's a comparison, not a lookup.
    page_recipes={
        "jobs": {
            "list_columns": ["jobNumber", "subject", "customer", "technician",
                             "scheduledAt", "status"],
            "filter_chips": ["status", "technician", "priority"],
            "detail_sections": [
                {"label": "Job",           "fields": ["jobNumber", "subject",
                                                      "description", "priority"]},
                {"label": "Customer & site", "fields": ["customer", "siteAddress",
                                                        "contactName",
                                                        "contactPhone"]},
                {"label": "Dispatch",      "fields": ["technician", "scheduledAt",
                                                      "status", "completedAt"]},
                {"label": "Work done",     "fields": ["partsUsed", "laborHours",
                                                      "resolutionNotes"]},
            ],
        },

        # Same record under the other half of the industry's vocabulary.
        "work_orders": {
            "list_columns": ["workOrderNumber", "subject", "customer",
                             "technician", "scheduledAt", "status"],
            "filter_chips": ["status", "technician", "priority"],
            "detail_sections": [
                {"label": "Work order",      "fields": ["workOrderNumber",
                                                        "subject", "description",
                                                        "priority"]},
                {"label": "Customer & site", "fields": ["customer", "siteAddress",
                                                        "contactName",
                                                        "contactPhone"]},
                {"label": "Dispatch",        "fields": ["technician",
                                                        "scheduledAt", "status",
                                                        "completedAt"]},
                {"label": "Work done",       "fields": ["partsUsed", "laborHours",
                                                        "resolutionNotes"]},
            ],
        },

        # Inbound, before it becomes a job. Priority is the whole
        # triage decision, so it sits on the row.
        "service_requests": {
            "list_columns": ["subject", "customer", "requestedAt", "priority",
                             "status"],
            "filter_chips": ["status", "priority"],
            "detail_sections": [
                {"label": "Request",  "fields": ["subject", "description",
                                                 "priority"]},
                {"label": "Customer", "fields": ["customer", "contactName",
                                                 "contactPhone", "siteAddress"]},
                {"label": "Handling", "fields": ["status", "requestedAt",
                                                 "assignedTo", "jobNumber"]},
            ],
        },

        # A dispatcher picks a tech on two things only: can they do this
        # work, and are they near it. Skills and service area, in that
        # order, right behind the name.
        "technicians": {
            "list_columns": ["fullName", "skills", "serviceArea", "phone",
                             "activeJobs"],
            "filter_chips": ["skills", "serviceArea"],
            "detail_sections": [
                {"label": "Technician",       "fields": ["fullName", "employeeId",
                                                         "photoUrl"]},
                {"label": "Skills & coverage", "fields": ["skills",
                                                          "certifications",
                                                          "serviceArea"]},
                {"label": "Contact",          "fields": ["phone", "email",
                                                         "vehicle"]},
            ],
        },

        # Accounts are looked up by who answers the phone and where the
        # truck goes, not by account number.
        "customers": {
            "list_columns": ["name", "contactName", "phone", "city",
                             "accountType"],
            "filter_chips": ["accountType", "city"],
            "detail_sections": [
                {"label": "Account", "fields": ["name", "accountNumber",
                                                "accountType"]},
                {"label": "Site",    "fields": ["siteAddress", "city", "region",
                                                "postalCode"]},
                {"label": "Contact", "fields": ["contactName", "phone", "email"]},
                {"label": "Service", "fields": ["serviceContract",
                                                "lastServiceAt", "openJobs"]},
            ],
        },

        "parts": {
            "list_columns": ["partNumber", "name", "quantityOnHand",
                             "reorderPoint", "unitCost", "location"],
            "filter_chips": ["status", "location"],
            "detail_sections": [
                {"label": "Part",  "fields": ["partNumber", "name",
                                              "description", "manufacturer"]},
                {"label": "Stock", "fields": ["quantityOnHand", "reorderPoint",
                                              "location"]},
                {"label": "Cost",  "fields": ["unitCost", "sellPrice",
                                              "supplier"]},
            ],
        },

        # A checklist only matters once it's signed — the completion
        # timestamp is the record, not decoration.
        "checklists": {
            "list_columns": ["title", "job", "technician", "itemCount",
                             "completedAt"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Checklist", "fields": ["title", "description",
                                                  "jobType"]},
                {"label": "Items",     "fields": ["items", "itemCount",
                                                  "completedItems"]},
                {"label": "Sign-off",  "fields": ["technician", "completedAt",
                                                  "signature", "notes"]},
            ],
        },

        # Time is money in FSM literally: this ledger is what gets
        # invoiced, so billable rides on the row.
        "time_entries": {
            "list_columns": ["technicianName", "job", "startedAt",
                             "durationHours", "billable"],
            "filter_chips": ["technicianName", "billable"],
            "detail_sections": [
                {"label": "Entry",    "fields": ["technicianName", "job",
                                                 "activityType"]},
                {"label": "Duration", "fields": ["startedAt", "endedAt",
                                                 "durationHours"]},
                {"label": "Billing",  "fields": ["billable", "rate", "amount",
                                                 "notes"]},
            ],
        },
    },
)
