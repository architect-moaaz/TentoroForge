"""Legislative-platform vocabulary — bills, ordinances, committees, roll-call
votes, agendas and minutes. Granicus / Legistar / OpenGov / eScribe /
NovusAGENDA / state-legislature bill-tracking systems: the software a
clerk's office lives in and a legislature reads.

Deliberately spans both halves of the domain, because they share a shape
and diverge only in vocabulary: a state or national **legislature**
(sessions, chambers, crossover deadlines, bills) and a **municipal
council** (ordinances, consent agenda, public comment, meetings). Entity
keys are declared under both spellings — ``bills`` and ``ordinances``,
``hearings`` and ``meetings`` — because match_entity_name bridges plural
drift, not different words, and an app will use one set or the other.

Design decisions worth naming:

  - **Bills use kanban, keyed on legislative stage.** introduced →
    in-committee → reported → floor → passed/failed → enacted. The stage
    is the noun everyone in the building actually speaks; a legislative
    app that renders bills as a flat table has lost the plot. This is
    the defining choice of the archetype.

  - **Roll-call votes are ledger-list.** Append-only, never editable —
    the same primitive banking uses, for the same reason. A recorded
    vote is a legal record, not a row someone corrects later.

  - **Agenda items declare NO list_order.** Item 1, 2, 3 is a sequence
    the clerk sets deliberately, and a domain default would override a
    human's explicit ordering. Silence is the correct declaration: it
    leaves the composer's (and the clerk's) sequence alone. This is the
    one screen in the domain where sorting is wrong.

  - **The clerk is the power user, not the legislator.** This software
    is bought and lived in by clerks — agendas, minutes, publication,
    records requests — while members dip in to read and vote. The
    persona screens reflect that inversion rather than the org chart.

  - **Deadlines drive the dashboard, not volume.** "What must be
    published by Friday", "committee deadlines this week", "comment
    windows closing". Nobody in a clerk's office wants a bill count.
    Every list that has a deadline column leads with it, ascending —
    what is about to lapse, not what was last touched.

  - **The public portal is a first-class persona.** Open-meeting and
    sunshine laws make published agendas, minutes and votes a legal
    obligation, so `public` gets real screens rather than one
    afterthought page.

  - **Empty-state copy is institutional-plain.** This is the public
    record. Chirpy copy reads wrong next to a statutory notice.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


LEGISLATIVE_PLATFORM = ArchetypeVocabulary(
    id="legislative-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    # Clerk first, and deliberately widest: the agenda/minutes/publish
    # loop is the job the product exists for. Members read and vote.
    # Chairs run committees. Public reads the record.
    primary_screens_per_persona={
        "clerk":          ["agenda", "minutes", "bills", "publication-queue",
                            "records-requests"],
        "city_clerk":     ["agenda", "minutes", "ordinances",
                            "publication-queue", "records-requests"],
        "secretary":      ["agenda", "minutes", "bills", "publication-queue"],

        "member":         ["my-bills", "floor-calendar", "votes", "committees"],
        "legislator":     ["my-bills", "floor-calendar", "votes", "committees"],
        "councilmember":  ["my-ordinances", "agenda", "votes", "committees"],

        "chair":          ["committee", "hearings", "referred-bills", "agenda"],
        "committee_chair": ["committee", "hearings", "referred-bills", "agenda"],

        "staff":          ["bills", "amendments", "hearings", "research"],
        "analyst":        ["bills", "amendments", "hearings", "research"],

        # Sunshine-law surface. Read-only, but not second-class.
        "public":         ["bills", "meetings", "votes", "members"],
        "constituent":    ["bills", "meetings", "votes", "members"],

        "admin":          ["dashboard", "members", "committees", "sessions",
                            "users"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Where a bill is in its life — the only split that matters.
        "bills":            ["in-committee", "on-floor", "enacted"],
        "ordinances":       ["in-committee", "on-floor", "adopted"],
        "my-bills":         ["drafting", "introduced", "advancing"],
        "my-ordinances":    ["drafting", "introduced", "advancing"],
        "referred-bills":   ["awaiting-hearing", "heard", "reported"],

        # Meetings are a time axis, always.
        "hearings":         ["upcoming", "today", "past"],
        "meetings":         ["upcoming", "today", "past"],
        "floor-calendar":   ["today", "this-week", "later"],

        # A municipal agenda is legally split this way: consent items
        # pass as a block without debate, regular items are debated,
        # public hearings carry a noticing requirement.
        "agenda":           ["consent", "regular", "public-hearing"],

        # Minutes and publication are a compliance pipeline.
        "minutes":          ["draft", "pending-approval", "approved"],
        "publication-queue": ["due", "published", "overdue"],
        "records-requests": ["open", "in-progress", "fulfilled"],

        "amendments":       ["proposed", "adopted", "rejected"],
        "public-comments":  ["new", "acknowledged", "entered-into-record"],
    },

    # ── Section filter predicates ───────────────────────────────────
    section_filters={
        "in-committee":         {"stage": "in-committee"},
        "on-floor":             {"stage": "on-floor"},
        "enacted":              {"stage": "enacted"},
        "adopted":              {"stage": "adopted"},
        "drafting":             {"stage": "draft"},
        "introduced":           {"stage": "introduced"},
        "awaiting-hearing":     {"status": "referred"},
        "heard":                {"status": "heard"},
        "reported":             {"status": "reported"},
        "consent":              {"itemType": "consent"},
        "regular":              {"itemType": "regular"},
        "public-hearing":       {"itemType": "public-hearing"},
        "draft":                {"status": "draft"},
        "pending-approval":     {"status": "pending"},
        "approved":             {"status": "approved"},
        "due":                  {"status": "due"},
        "published":            {"status": "published"},
        "overdue":              {"status": "overdue"},
        "open":                 {"status": "open"},
        "in-progress":          {"status": "in-progress"},
        "fulfilled":            {"status": "fulfilled"},
        "proposed":             {"status": "proposed"},
        "rejected":             {"status": "rejected"},
        # Time-relative sections carry no equality filter — the runtime
        # enforces filters with `eq`, and "upcoming" is a range.
        "upcoming":             {},
        "today":                {},
        "past":                 {},
        "this-week":            {},
        "later":                {},
        "advancing":            {},
        "new":                  {},
        "acknowledged":         {},
        "entered-into-record":  {},
    },

    # ── Shape per entity ────────────────────────────────────────────
    component_preferences={
        # The defining choice: a bill IS its stage.
        "bills":            ComponentPreference(shape="kanban",
                                                primary_field="billNumber"),
        "ordinances":       ComponentPreference(shape="kanban",
                                                primary_field="ordinanceNumber"),
        "resolutions":      ComponentPreference(shape="kanban",
                                                primary_field="resolutionNumber"),

        # Append-only legal records.
        "votes":            ComponentPreference(shape="ledger-list",
                                                primary_field="motion"),
        "roll_calls":       ComponentPreference(shape="ledger-list",
                                                primary_field="motion"),

        # People, browsed by face and name.
        "members":          ComponentPreference(shape="card-grid",
                                                primary_field="fullName"),
        "legislators":      ComponentPreference(shape="card-grid",
                                                primary_field="fullName"),
        "committees":       ComponentPreference(shape="card-grid",
                                                primary_field="name"),

        # Calendared events.
        "hearings":         ComponentPreference(shape="schedule-grid"),
        "meetings":         ComponentPreference(shape="schedule-grid"),

        # Ordered documents — dense, numbered, scanned top to bottom.
        "agendas":          ComponentPreference(shape="table",
                                                primary_field="meetingDate"),
        "agenda_items":     ComponentPreference(shape="table",
                                                primary_field="title"),
        "minutes":          ComponentPreference(shape="table",
                                                primary_field="meetingDate"),
        "amendments":       ComponentPreference(shape="table",
                                                primary_field="amendmentNumber"),
        "public_comments":  ComponentPreference(shape="card-list",
                                                primary_field="submittedBy"),
        "records_requests": ComponentPreference(shape="table",
                                                primary_field="requestNumber"),
        "sessions":         ComponentPreference(shape="table",
                                                primary_field="name"),
    },

    # ── Domain-voiced empty states ──────────────────────────────────
    # Plain and institutional. This copy sits next to statutory notices.
    signature_states={
        "empty_bills":            "No bills have been introduced this session.",
        "empty_ordinances":       "No ordinances have been introduced.",
        "empty_agenda":           "No items have been placed on this agenda.",
        "empty_agenda_items":     "No items have been placed on this agenda.",
        "empty_minutes":          "No minutes have been recorded for this meeting.",
        "empty_votes":            "No votes have been recorded.",
        "empty_hearings":         "No hearings are scheduled.",
        "empty_meetings":         "No meetings are scheduled.",
        "empty_committees":       "No committees have been constituted.",
        "empty_members":          "No members are seated.",
        "empty_amendments":       "No amendments have been offered.",
        "empty_public_comments":  "No public comment has been submitted.",
        "empty_records_requests": "No records requests are open.",
        "empty_publication_queue": "Nothing is awaiting publication.",
        "empty_dashboard":        "Nothing requires action today.",
        "no_results":             "No records match those filters.",
    },

    # ── Status badges ───────────────────────────────────────────────
    status_badges={
        "enacted":       {"variant": "success"},
        "adopted":       {"variant": "success"},
        "passed":        {"variant": "success"},
        "approved":      {"variant": "success"},
        "published":     {"variant": "success"},
        "fulfilled":     {"variant": "success"},

        "failed":        {"variant": "danger"},
        "vetoed":        {"variant": "danger"},
        "rejected":      {"variant": "danger"},
        "overdue":       {"variant": "danger"},
        "died-in-committee": {"variant": "danger",
                              "label": "Died in committee"},

        "tabled":        {"variant": "warning"},
        "postponed":     {"variant": "warning"},
        "pending":       {"variant": "warning"},
        "due":           {"variant": "warning"},

        "introduced":    {"variant": "accent"},
        "reported":      {"variant": "accent"},
        "on-floor":      {"variant": "accent"},

        # Records-request lifecycle. These are filtered on by the
        # dashboard, so they need badges like any other shown status.
        "open":          {"variant": "accent"},
        "in-progress":   {"variant": "warning", "label": "In progress"},

        "draft":         {"variant": "neutral"},
        "in-committee":  {"variant": "neutral"},
        "referred":      {"variant": "neutral"},
        "withdrawn":     {"variant": "neutral"},
    },

    # ── What belongs on THIS domain's dashboard ─────────────────────
    # Deadlines and obligations, not counts. A clerk opens this to find
    # out what lapses if they do nothing today.
    dashboard_recipe={
        "kpis": [
            {"label": "Bills in committee", "entity": "bills", "op": "count",
             "filter": {"stage": ["in-committee", "referred", "committee"]}},
            {"label": "On the floor", "entity": "bills", "op": "count",
             "filter": {"stage": ["on-floor", "floor", "calendared"]}},
            {"label": "Awaiting publication", "entity": "minutes",
             "op": "count", "filter": {"status": ["pending", "draft"]}},
            {"label": "Open records requests", "entity": "records_requests",
             "op": "count", "filter": {"status": ["open", "in-progress"]}},
        ],
        "sections": [
            {"title": "Next meetings", "entity": "meetings",
             "shape": "schedule-grid", "limit": 5},
            {"title": "Action required this week", "entity": "bills",
             "shape": "table", "limit": 8},
            {"title": "Recent votes", "entity": "votes",
             "shape": "ledger-list", "limit": 6},
            {"title": "Public comment awaiting review", "entity": "public_comments",
             "shape": "card-list", "limit": 5},
        ],
    },

    # ── What each page SHOWS, and which row leads ───────────────────
    page_recipes={
        # Identity → who moved it → where it is → when it lapses.
        "bills": {
            "list_columns": ["billNumber", "title", "sponsor", "stage",
                             "committee", "nextActionDate"],
            # What is about to lapse. A legislature sorted by "recently
            # updated" tells a clerk nothing about what dies on Friday.
            "list_order": {"field": ["nextActionDate", "deadlineAt",
                                     "crossoverDate", "actionDeadline"],
                           "dir": "asc"},
            "filter_chips": ["stage", "committee", "session", "sponsor"],
            "detail_sections": [
                {"label": "Bill",     "fields": ["billNumber", "title",
                                                 "summary", "billType"]},
                {"label": "Sponsors", "fields": ["sponsor", "coSponsors",
                                                 "introducedDate"]},
                {"label": "Status",   "fields": ["stage", "committee",
                                                 "nextActionDate",
                                                 "lastActionText"]},
                {"label": "Text",     "fields": ["fullText", "version",
                                                 "attachments"]},
            ],
        },
        "ordinances": {
            "list_columns": ["ordinanceNumber", "title", "sponsor", "stage",
                             "committee", "nextActionDate"],
            "list_order": {"field": ["nextActionDate", "deadlineAt",
                                     "hearingDate"], "dir": "asc"},
            "filter_chips": ["stage", "committee", "sponsor"],
            "detail_sections": [
                {"label": "Ordinance", "fields": ["ordinanceNumber", "title",
                                                  "summary"]},
                {"label": "Sponsors",  "fields": ["sponsor", "coSponsors",
                                                  "introducedDate"]},
                {"label": "Status",    "fields": ["stage", "committee",
                                                  "nextActionDate"]},
            ],
        },
        "resolutions": {
            "list_columns": ["resolutionNumber", "title", "sponsor",
                             "stage", "adoptedDate"],
            "list_order": {"field": ["nextActionDate", "introducedDate"],
                           "dir": "asc"},
            "filter_chips": ["stage", "sponsor"],
        },

        # A vote record IS about when it happened — recency is correct
        # here, and this entry exists partly to prove list_order is a
        # domain judgement rather than a standing bias against dates.
        "votes": {
            "list_columns": ["voteDate", "motion", "billNumber",
                             "ayes", "nays", "result"],
            "list_order": {"field": ["voteDate", "recordedAt", "takenAt"],
                           "dir": "desc"},
            "filter_chips": ["result", "session", "committee"],
            "detail_sections": [
                {"label": "Motion",  "fields": ["motion", "billNumber",
                                                "voteDate", "result"]},
                {"label": "Tally",   "fields": ["ayes", "nays", "abstentions",
                                                "absent"]},
                {"label": "Record",  "fields": ["memberVotes", "recordedBy"]},
            ],
        },
        "roll_calls": {
            "list_columns": ["voteDate", "motion", "billNumber",
                             "ayes", "nays", "result"],
            "list_order": {"field": ["voteDate", "recordedAt"], "dir": "desc"},
            "filter_chips": ["result", "session"],
        },

        # Upcoming first — a calendar reads forward.
        "hearings": {
            "list_columns": ["scheduledAt", "committee", "location",
                             "subject", "status"],
            "list_order": {"field": ["scheduledAt", "hearingDate",
                                     "meetingDate"], "dir": "asc"},
            "filter_chips": ["committee", "status", "location"],
            "detail_sections": [
                {"label": "Hearing", "fields": ["subject", "committee",
                                                "scheduledAt", "location"]},
                {"label": "Notice",  "fields": ["noticePostedAt",
                                                "noticeUrl", "status"]},
                {"label": "Record",  "fields": ["agenda", "minutes",
                                                "attendance"]},
            ],
        },
        "meetings": {
            "list_columns": ["meetingDate", "body", "location",
                             "status", "agendaPublished"],
            "list_order": {"field": ["meetingDate", "scheduledAt"],
                           "dir": "asc"},
            "filter_chips": ["body", "status", "location"],
        },

        "agendas": {
            "list_columns": ["meetingDate", "body", "status",
                             "itemCount", "publishedAt"],
            "list_order": {"field": ["meetingDate", "scheduledAt"],
                           "dir": "asc"},
            "filter_chips": ["body", "status"],
        },

        # NO list_order, deliberately. Item 1, 2, 3 is a sequence the
        # clerk sets; a domain default here would silently reorder a
        # legal document.
        "agenda_items": {
            "list_columns": ["itemNumber", "title", "itemType",
                             "billNumber", "action"],
            "filter_chips": ["itemType", "action"],
            "detail_sections": [
                {"label": "Item",    "fields": ["itemNumber", "title",
                                                "itemType", "description"]},
                {"label": "Subject", "fields": ["billNumber", "sponsor",
                                                "attachments"]},
                {"label": "Outcome", "fields": ["action", "voteId", "notes"]},
            ],
        },

        "minutes": {
            "list_columns": ["meetingDate", "body", "status",
                             "approvedAt", "publishedAt"],
            # Minutes are a compliance queue — oldest unapproved first.
            "list_order": {"field": ["meetingDate", "recordedAt"],
                           "dir": "asc"},
            "filter_chips": ["body", "status"],
        },

        "amendments": {
            "list_columns": ["amendmentNumber", "billNumber", "sponsor",
                             "status", "offeredDate"],
            "list_order": {"field": ["offeredDate", "createdAt"],
                           "dir": "asc"},
            "filter_chips": ["status", "sponsor"],
        },

        "members": {
            "list_columns": ["fullName", "district", "party", "role",
                             "committees"],
            # A roster reads alphabetically. Nobody looks up a member by
            # when their record was last edited.
            "list_order": {"field": ["lastName", "fullName", "name"],
                           "dir": "asc"},
            "filter_chips": ["party", "district", "role"],
            "detail_sections": [
                {"label": "Member",      "fields": ["fullName", "district",
                                                    "party", "role"]},
                {"label": "Contact",     "fields": ["email", "phone",
                                                    "officeAddress"]},
                {"label": "Assignments", "fields": ["committees", "termStart",
                                                    "termEnd"]},
            ],
        },

        "committees": {
            "list_columns": ["name", "chair", "memberCount",
                             "referredCount", "nextMeeting"],
            "list_order": {"field": ["name", "title"], "dir": "asc"},
            "filter_chips": ["type", "status"],
        },

        "public_comments": {
            "list_columns": ["submittedAt", "submittedBy", "subject",
                             "billNumber", "status"],
            # A comment window closes; oldest unread first is the
            # obligation order.
            "list_order": {"field": ["submittedAt", "createdAt"],
                           "dir": "asc"},
            "filter_chips": ["status", "billNumber"],
        },

        "records_requests": {
            "list_columns": ["requestNumber", "requester", "subject",
                             "status", "dueDate"],
            # Statutory response clocks — what expires first leads.
            "list_order": {"field": ["dueDate", "deadlineAt", "requestedAt"],
                           "dir": "asc"},
            "filter_chips": ["status", "requester"],
        },

        "sessions": {
            "list_columns": ["name", "startDate", "endDate", "status",
                             "billCount"],
            "list_order": {"field": ["startDate", "convenedAt"],
                           "dir": "desc"},
            "filter_chips": ["status"],
        },
    },
)
