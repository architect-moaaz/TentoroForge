"""Healthcare-platform vocabulary — patients, encounters, vitals,
prescriptions, EHR / EMR, clinical workflows.

Shape mirrors booking_platform / banking_platform. Reads as "what does
every clinical app (Epic, Cerner, Athenahealth, Healthie) carry that
a code generator would otherwise re-invent every time?"

Design decisions worth naming:

  - **Patient list is a table for clinicians.** Bulk-scan work: a
    dense sortable roster with status flags, last-visit, next-appt.
    Context-scoped to ``clinician`` so patients don't see a
    patients-table view.

  - **Appointments use schedule-grid.** Clinician's day is a
    time-of-day calendar; universally expected shape.

  - **Encounters use card-list.** Each visit is a "chief complaint"
    card summary the clinician expands into a full note.

  - **Prescriptions + vitals use dense table + ledger.** Meds are
    comparison work (interactions, dosages); vitals are append-only
    time-series.

  - **Empty-state copy is professional-calm.** Clinical readers are
    working — theatre or chirpiness reads as unprofessional. No
    exclamation marks. No "Nice work!" — this is medicine.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


HEALTHCARE_PLATFORM = ArchetypeVocabulary(
    id="healthcare-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Patient — records + appointments + care surface.
        "patient":    ["appointments", "records", "prescriptions", "messages"],

        # Nurse — task queue + patient list + vitals.
        "nurse":      ["patient-list", "vitals-queue", "tasks", "messages"],

        # Doctor / physician — schedule + patient care.
        "doctor":     ["schedule", "patient-list", "encounters", "prescriptions"],
        "physician":  ["schedule", "patient-list", "encounters", "prescriptions"],

        # Admin — configuration + reporting + compliance.
        "admin":      ["dashboard", "users", "schedules", "reports", "compliance"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Patient list — status split.
        "patient-list":   ["active", "discharged", "flagged"],
        "patients":       ["active", "discharged", "flagged"],

        # Appointment queue — time-window split.
        "appointments":   ["today", "upcoming", "past"],

        # Encounter lifecycle.
        "encounters":     ["open", "closed"],
        "visits":         ["open", "closed"],

        # Rx lifecycle.
        "prescriptions":  ["active", "expired", "cancelled"],
        "medications":    ["active", "expired", "cancelled"],

        # Vitals queue.
        "vitals-queue":   ["overdue", "due-soon"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Patient roster — clinician-scoped table.
        "patients":         ComponentPreference(shape="table",
                                                 primary_field="fullName",
                                                 context="clinician"),

        # Schedule — time-of-day grid.
        "appointments":     ComponentPreference(shape="schedule-grid",
                                                 primary_field="patientName"),

        # Encounter summaries — one card per visit.
        "encounters":       ComponentPreference(shape="card-list",
                                                 primary_field="chiefComplaint"),
        "visits":           ComponentPreference(shape="card-list",
                                                 primary_field="chiefComplaint"),

        # Meds — comparison table.
        "prescriptions":    ComponentPreference(shape="table",
                                                 primary_field="medicationName"),
        "medications":      ComponentPreference(shape="table",
                                                 primary_field="medicationName"),

        # Vitals — append-only time-series.
        "vitals":           ComponentPreference(shape="ledger-list",
                                                 primary_field="type"),
        "vital_signs":      ComponentPreference(shape="ledger-list",
                                                 primary_field="type"),

        # People directories.
        "providers":        ComponentPreference(shape="card-grid",
                                                 primary_field="fullName"),
        "doctors":          ComponentPreference(shape="card-grid",
                                                 primary_field="fullName"),
        "physicians":       ComponentPreference(shape="card-grid",
                                                 primary_field="fullName"),
        "nurses":           ComponentPreference(shape="card-grid",
                                                 primary_field="fullName"),

        # Messages.
        "messages":         ComponentPreference(shape="card-list",
                                                 primary_field="subject"),
    },

    # ── Empty states — professional-calm, never chirpy ────────────
    signature_states={
        # Patient view.
        "empty_appointments":   "No appointments scheduled. Book your "
                                 "next visit when you're ready.",
        "empty_records":        "No records on file yet.",
        "empty_prescriptions":  "No active prescriptions.",
        "empty_medications":    "No active medications.",
        "empty_messages":       "No messages. Your care team will reach "
                                 "out here when needed.",

        # Clinician view.
        "empty_patient_list":   "No patients assigned to you.",
        "empty_patients":       "No patients on the roster.",
        "empty_active":         "No active patients in this view.",
        "empty_discharged":     "No discharged patients in this window.",
        "empty_flagged":        "No flagged patients — the roster is clear.",
        "empty_schedule":       "No appointments on the schedule today.",
        "empty_today":          "Nothing scheduled today.",
        "empty_upcoming":       "No upcoming appointments in this window.",
        "empty_past":           "No past appointments in this window.",
        "empty_encounters":     "No encounters logged in this window.",
        "empty_visits":         "No visits logged in this window.",
        "empty_open":           "No open encounters.",
        "empty_closed":         "No closed encounters in this window.",
        "empty_expired":        "No expired prescriptions.",
        "empty_cancelled":      "No cancelled prescriptions.",

        # Nurse / vitals.
        "empty_vitals_queue":   "The vitals queue is clear.",
        "empty_overdue":        "No overdue vitals.",
        "empty_due_soon":       "No vitals due soon.",
        "empty_vitals":         "No vitals recorded yet.",
        "empty_tasks":          "No open tasks.",

        # Admin operational.
        "empty_dashboard":      "No activity yet. Metrics populate as "
                                 "encounters are logged.",
        "empty_users":          "No users provisioned yet.",
        "empty_schedules":      "No schedules configured yet.",
        "empty_reports":        "No reports generated yet.",
        "empty_compliance":     "No compliance items open.",

        # Directories.
        "empty_providers":      "No providers on the roster.",
        "empty_doctors":        "No doctors on the roster.",
        "empty_nurses":         "No nurses on the roster.",

        # Generic filtered-out state.
        "no_results":           "No matches for the current filter. Try "
                                 "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Patient status.
        "active":       {"status": ["active", "admitted", "outpatient"]},
        "discharged":   {"status": ["discharged", "released"]},
        "flagged":      {"status": ["flagged", "alert", "watchlist"]},

        # Encounter lifecycle.
        "open":         {"status": ["open", "in_progress"]},
        "closed":       {"status": ["closed", "completed", "signed"]},

        # Prescription lifecycle.
        "expired":      {"status": ["expired"]},
        "cancelled":    {"status": ["cancelled", "discontinued", "stopped"]},

        # Appointment time windows — no lifecycle filter.
        "today":        {},
        "upcoming":     {},
        "past":         {},

        # Vitals queue — no lifecycle filter (date-driven).
        "overdue":      {},
        "due-soon":     {},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        "active":       {"variant": "success", "label": "Active"},
        "admitted":     {"variant": "warning", "label": "Admitted"},
        "discharged":   {"variant": "neutral", "label": "Discharged"},
        "flagged":      {"variant": "danger",  "label": "Flagged"},
        "scheduled":    {"variant": "warning", "label": "Scheduled"},
        "cancelled":    {"variant": "neutral", "label": "Cancelled"},
        "no_show":      {"variant": "danger",  "label": "No-show"},
        "no-show":      {"variant": "danger",  "label": "No-show"},
        "completed":    {"variant": "success", "label": "Completed"},
        "expired":      {"variant": "neutral", "label": "Expired"},
        "open":         {"variant": "warning", "label": "Open"},
        "closed":       {"variant": "neutral", "label": "Closed"},
        "discontinued": {"variant": "neutral", "label": "Discontinued"},
    },

    # What a clinic opens the app to see. "Total patients" is a number
    # nobody in a clinic has ever acted on. The morning questions are:
    # who's coming in, whose note is still open, and who needs watching.
    # Open encounters lead alongside the schedule because an unclosed
    # encounter is unbilled work and an unsigned record — the one item
    # here with a deadline attached to it.
    dashboard_recipe={
        "kpis": [
            {"label": "Scheduled",       "entity": "appointments",
             "op": "count", "filter": {"status": ["scheduled"]}},
            {"label": "Open encounters", "entity": "encounters",
             "op": "count", "filter": {"status": ["open"]}},
            {"label": "Flagged",         "entity": "patients",
             "op": "count", "filter": {"status": ["flagged"]}},
            {"label": "Active patients", "entity": "patients",
             "op": "count", "filter": {"status": ["active", "admitted"]}},
            {"label": "No-shows",        "entity": "appointments",
             "op": "count", "filter": {"status": ["no_show"]}},
        ],
        "sections": [
            {"title": "Today's schedule", "entity": "appointments",
             "shape": "schedule-grid", "filter": {"status": ["scheduled"]},
             "limit": 10},
            {"title": "Encounters to close", "entity": "encounters",
             "shape": "card-list", "filter": {"status": ["open"]},
             "limit": 8},
            {"title": "Flagged patients", "entity": "patients",
             "shape": "table", "filter": {"status": ["flagged"]}, "limit": 6},
        ],
    },

    # What each screen SHOWS. Clinical lists are identified by MRN and
    # name together — name alone is ambiguous in any roster with two
    # Smiths, and getting the wrong chart is the defining error of this
    # domain. Date of birth rides along for the same reason: it's the
    # second identifier every clinic verifies out loud. Detail pages are
    # grouped the way a chart is: who they are, how to reach them, what
    # we're treating, who pays.
    page_recipes={
        "patients": {
            "list_columns": ["mrn", "fullName", "dateOfBirth", "status",
                             "primaryProvider", "lastVisitAt"],
            "filter_chips": ["status", "primaryProvider"],
            "detail_sections": [
                {"label": "Patient",  "fields": ["mrn", "fullName",
                                                 "dateOfBirth", "sex"]},
                {"label": "Contact",  "fields": ["phone", "email",
                                                 "addressLine1",
                                                 "emergencyContact"]},
                {"label": "Care",     "fields": ["primaryProvider", "status",
                                                 "allergies",
                                                 "activeConditions"]},
                {"label": "Coverage", "fields": ["insuranceProvider",
                                                 "policyNumber"]},
            ],
        },

        # The schedule row. Visit type sets the room and the slot length,
        # so it belongs beside the time, not inside the record.
        "appointments": {
            "list_columns": ["patientName", "startAt", "provider",
                             "appointmentType", "status"],
            "filter_chips": ["status", "provider"],
            "detail_sections": [
                {"label": "Visit",        "fields": ["patientName",
                                                     "appointmentType",
                                                     "reason"]},
                {"label": "When & where", "fields": ["startAt", "endAt",
                                                     "location", "provider"]},
                {"label": "Status",       "fields": ["status", "checkedInAt",
                                                     "notes"]},
            ],
        },

        # Chief complaint is how a clinician recognises a past visit —
        # it does the work a title would.
        "encounters": {
            "list_columns": ["patientName", "chiefComplaint", "encounterDate",
                             "provider", "status"],
            "filter_chips": ["status", "provider"],
            "detail_sections": [
                {"label": "Encounter",  "fields": ["patientName",
                                                   "chiefComplaint",
                                                   "encounterDate"]},
                {"label": "Assessment", "fields": ["diagnosis", "assessment",
                                                   "plan"]},
                {"label": "Sign-off",   "fields": ["provider", "status",
                                                   "signedAt"]},
            ],
        },

        # Meds are read as a triple — drug, dose, how often. Splitting
        # those across a list and a detail page is how dosing errors
        # happen, so all three stay on the row.
        "prescriptions": {
            "list_columns": ["medicationName", "patientName", "dosage",
                             "frequency", "status", "prescribedAt"],
            "filter_chips": ["status", "prescriber"],
            "detail_sections": [
                {"label": "Medication", "fields": ["medicationName", "dosage",
                                                   "route", "frequency"]},
                {"label": "Course",     "fields": ["startDate", "endDate",
                                                   "refillsRemaining", "status"]},
                {"label": "Prescriber", "fields": ["prescriber", "prescribedAt",
                                                   "pharmacy", "notes"]},
            ],
        },

        # A vitals reading means nothing without its unit, and little
        # without the range it's judged against.
        "vitals": {
            "list_columns": ["patientName", "type", "value", "unit",
                             "recordedAt"],
            "filter_chips": ["type"],
            "detail_sections": [
                {"label": "Reading", "fields": ["type", "value", "unit"]},
                {"label": "Range",   "fields": ["normalRange", "abnormalFlag",
                                                "notes"]},
                {"label": "Context", "fields": ["patientName", "encounter",
                                                "recordedAt", "recordedBy"]},
            ],
        },

        # Providers are found by specialty far more often than by name.
        "providers": {
            "list_columns": ["fullName", "specialty", "npi", "department",
                             "email"],
            "filter_chips": ["specialty", "department"],
            "detail_sections": [
                {"label": "Provider", "fields": ["fullName", "credentials",
                                                 "specialty"]},
                {"label": "Practice", "fields": ["department", "npi",
                                                 "licenseNumber"]},
                {"label": "Contact",  "fields": ["email", "phone",
                                                 "officeLocation"]},
            ],
        },

        # Clinical inboxes are triaged by urgency before recency.
        "messages": {
            "list_columns": ["subject", "patientName", "sender", "priority",
                             "sentAt"],
            "filter_chips": ["priority"],
            "detail_sections": [
                {"label": "Message",  "fields": ["subject", "body"]},
                {"label": "Thread",   "fields": ["patientName", "sender",
                                                 "recipient", "sentAt"]},
                {"label": "Handling", "fields": ["priority", "readAt",
                                                 "respondedAt"]},
            ],
        },
    },
)
