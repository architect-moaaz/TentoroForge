"""Booking-platform vocabulary — Yoga studios, salons, sport-court booking,
class scheduling, appointment-taking businesses.

Reference implementation matched to the patterns visible in the
Claude Artifact yoga-studio demo. Every field here is the answer to
"what convention does every booking app follow that a code generator
would otherwise miss?"

Design decisions worth naming:

  - **Bookings + Reviews use card-list, not table.** They're "your
    things" views — the reader wants icon + title + when-and-where +
    single action, not a sortable data grid. Tables are for admin
    comparison work.

  - **Instructors use card-grid, not table.** Browsing people is a
    directory task (photo + name + expertise + link), not comparison
    across rows.

  - **Members stays a table for admins.** ``context="admin"`` scopes
    it — a member browsing themselves shouldn't get a members table.

  - **Sessions use schedule-grid.** A time-of-day column view is the
    booking-app signature move — Airbnb/StreetEasy for real-estate
    calendars, MindBody/ClassPass for fitness. A table of sessions
    reads as an admin backend.

  - **my-bookings splits into Upcoming/Past.** Universal booking-app
    convention. Cancel action on Upcoming rows; review/rebook actions
    on Past rows (composer picks per section).

  - **Empty-state copy is warm + invitational**, matching a wellness
    tone but avoiding domain-specific words that would break for
    non-yoga booking apps (salons, courts). "Sessions" is generic
    enough to work across the class.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


BOOKING_PLATFORM = ArchetypeVocabulary(
    id="booking-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    # Ordered by importance. The persona-tabs sub-nav layer (follow-on
    # PB-7) reads this to render the tab strip within each persona.
    primary_screens_per_persona={
        # Member: browse → book → manage → review
        "member":       ["schedule", "my-bookings", "membership", "reviews"],
        # Instructor: what's next → what's my availability → who came
        "instructor":   ["sessions", "availability", "roster"],
        # Admin: dashboard + operational data + configuration
        "studio_admin": ["dashboard", "analytics", "classes", "instructors", "rooms", "plans"],
        # Common role aliases the planner emits — same primary screens
        "admin":        ["dashboard", "analytics", "classes", "instructors", "rooms", "plans"],
        "manager":      ["dashboard", "analytics", "classes", "instructors", "rooms", "plans"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # The signature "your bookings" pattern: Upcoming above, Past
        # below. Section names double as filter predicate keys the
        # composer maps to real filter expressions (upcoming: date >=
        # today; past: date < today).
        "my-bookings":       ["upcoming", "past"],
        "bookings":          ["upcoming", "past"],
        "reservations":      ["upcoming", "past"],
        "appointments":      ["upcoming", "past"],

        # Schedule shows the current period + a peek at the next.
        # Composer emits two Card blocks under one page header.
        "schedule":          ["today", "this-week"],
        "upcoming-classes":  ["today", "this-week"],
        # A yoga app's /classes route is the member's public schedule
        # view — same split as /schedule.
        "classes":           ["today", "this-week"],
        "class-sessions":    ["today", "this-week"],
        "class_sessions":    ["today", "this-week"],
        "sessions":          ["today", "this-week"],
        # Review lists split into recent (< 30 days) vs older archive.
        "reviews":           ["recent", "archive"],
        "my-reviews":        ["recent", "archive"],

        # Analytics = KPI strip + trend chart + top-N list. Matches
        # the Studio Admin analytics view in the Claude yoga demo.
        "analytics":         ["kpi-strip", "bookings-trend", "top-instructors"],

        # Membership = current plan card + switch-plans grid.
        "membership":        ["current-plan", "switch-plans"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Your-things views: card-list. Each row: title + inline meta
        # (instructor · when · where) + right-aligned action.
        "bookings":     ComponentPreference(shape="card-list",
                                             primary_field="className"),
        "reservations": ComponentPreference(shape="card-list",
                                             primary_field="className"),
        "appointments": ComponentPreference(shape="card-list",
                                             primary_field="serviceName"),
        "reviews":      ComponentPreference(shape="card-list",
                                             primary_field="className"),

        # Sessions = the schedule grid. When rendered as an admin
        # view (studio_admin's Classes tab) the same entity switches
        # to a table for editing.
        "sessions":         ComponentPreference(shape="schedule-grid"),
        "class_sessions":   ComponentPreference(shape="schedule-grid"),
        "classSessions":    ComponentPreference(shape="schedule-grid"),

        # People directories: card-grid with photo + name + expertise.
        "instructors":  ComponentPreference(shape="card-grid",
                                             primary_field="fullName"),
        "teachers":     ComponentPreference(shape="card-grid",
                                             primary_field="fullName"),
        "trainers":     ComponentPreference(shape="card-grid",
                                             primary_field="fullName"),
        "staff":        ComponentPreference(shape="card-grid",
                                             primary_field="fullName"),

        # Spaces: card-grid with capacity chip.
        "rooms":        ComponentPreference(shape="card-grid",
                                             primary_field="name"),
        "studios":      ComponentPreference(shape="card-grid",
                                             primary_field="name"),
        "courts":       ComponentPreference(shape="card-grid",
                                             primary_field="name"),

        # Plans: card-grid with pricing.
        "plans":                    ComponentPreference(shape="card-grid",
                                                        primary_field="name"),
        "membership_plans":         ComponentPreference(shape="card-grid",
                                                        primary_field="name"),
        "membershipPlans":          ComponentPreference(shape="card-grid",
                                                        primary_field="name"),
        "subscription_plans":       ComponentPreference(shape="card-grid",
                                                        primary_field="name"),

        # Instructor availability windows — a personal schedule view.
        # schedule-grid keys off startAt when present, else calendar,
        # else table (composer's built-in fallback chain).
        "instructor_availabilities":  ComponentPreference(shape="schedule-grid"),
        "instructor_availability":    ComponentPreference(shape="schedule-grid"),
        "availabilities":             ComponentPreference(shape="schedule-grid"),
        "availability":               ComponentPreference(shape="schedule-grid"),

        # Recurring schedule templates — admin authoring UI. Table is
        # the right shape (bulk edit, sortable, columnar).
        "recurring_schedule_templates": ComponentPreference(shape="table"),
        "schedule_templates":           ComponentPreference(shape="table"),
        "templates":                    ComponentPreference(shape="table"),

        # Waitlist entries — a queue view; table is right (position,
        # member, class, when).
        "waitlist_promotions": ComponentPreference(shape="table"),
        "waitlists":           ComponentPreference(shape="table"),

        # ── Admin-scoped: same entity, different shape ─────────────
        # Members are a directory for admins (bulk compare) but never
        # shown as a table to a Member persona (they don't see other
        # members). Context-scoped to admin.
        "members":      ComponentPreference(shape="table",
                                             context="studio_admin"),
        "users":        ComponentPreference(shape="table",
                                             context="studio_admin"),
        "customers":    ComponentPreference(shape="table",
                                             context="studio_admin"),
    },

    # ── Empty states — the domain voice fills these ────────────────
    signature_states={
        # Schedule: warm invitation, not "no data". Matches the Claude
        # yoga demo's "Try another date or clear your filters — new
        # Vinyasa sessions are added weekly." tone but stays generic
        # enough for salons / courts / any booking app.
        "empty_schedule":         "No sessions this day. Try another date — "
                                  "new sessions are added weekly.",
        "empty_today":            "Nothing scheduled today. Peek at this week "
                                  "or check back tomorrow.",
        "empty_this_week":        "This week is open. New sessions land here "
                                  "as they're scheduled.",

        # My bookings: the first-timer nudge.
        "empty_bookings":         "You haven't booked anything yet. Browse "
                                  "the schedule to reserve your first spot.",
        "empty_upcoming":         "Nothing coming up. Browse the schedule to "
                                  "book your next session.",
        "empty_past":             "No past sessions yet. Once you attend, "
                                  "they'll show here for review.",

        # Reviews: post-attendance nudge.
        "empty_reviews":          "No reviews yet. After your first session, "
                                  "share how it went.",
        "empty_recent":           "No recent reviews. Older ones live in the archive.",
        "empty_archive":          "Nothing archived yet.",

        # Instructor / attendance.
        "empty_upcoming_classes": "No classes on your schedule this week. "
                                  "Check your availability window.",
        "empty_availability":     "You haven't set your availability yet. "
                                  "Add the days and times you can teach.",
        "empty_attendance":       "No sessions to check attendance for yet.",

        # Admin operational.
        "empty_classes":          "No classes scheduled. Add your first "
                                  "class to start taking bookings.",
        "empty_instructors":      "No instructors on the roster. Invite "
                                  "your first teacher to get started.",
        "empty_rooms":            "No rooms yet. Add your studio spaces so "
                                  "classes can be assigned.",
        "empty_plans":            "No membership plans yet. Create your "
                                  "first plan to let members subscribe.",
        "empty_analytics":        "No activity yet. Analytics will show up "
                                  "here once bookings start coming in.",
        # The landing page on day one — the dashboard recipe resolves to
        # nothing until there are bookings, so this is the first copy a
        # new studio owner ever reads. Same warm-invitational voice.
        "empty_dashboard":        "Nothing booked yet. Your day fills in here "
                                  "as members reserve their spots.",

        # Generic "no filtered results" — the "you filtered too tight"
        # variant of empty. Distinct from the empty-collection cases
        # above so the copy can suggest widening the filter.
        "no_results":             "No matches for the current filter. Try "
                                  "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    # One filter per named section in `section_recipes`. The runtime's
    # list-op filter is equality-only today, so each section picks the
    # SINGLE canonical status value that best characterises it. A
    # follow-on runtime slice can extend to multi-value / range filters
    # (upcoming = date >= today, past = date < today) — until then, this
    # covers the wellness-app + salon + court booking flow which all
    # carry a status column with these values.
    section_filters={
        # Bookings lifecycle: pre-attendance vs post-attendance.
        # Values are ordered preference lists — the section-split
        # resolver picks the first one that appears in the entity's
        # declared enum_values, and drops the filter entirely when
        # none match (visual split still ships, filter left off so
        # the section isn't guaranteed-empty).
        "upcoming":         {"status": ["confirmed", "booked", "reserved",
                                        "pending", "waitlisted", "upcoming"]},
        "past":             {"status": ["attended", "completed", "checked_in",
                                        "cancelled", "no_show", "past"]},
        # Schedule sub-splits — no filter; both peek at the same list
        # under different headers (Today / This Week). A follow-on slice
        # can add real date-range filtering once the runtime supports it.
        "today":            {},
        "this-week":        {},
        # Analytics tiles — no filter (each section is a widget kind,
        # not a filtered list).
        "kpi-strip":        {},
        "bookings-trend":   {},
        "top-instructors":  {},
        # Membership sub-splits — no filter
        "current-plan":     {},
        "switch-plans":     {},
        # Review lifecycle — recent vs archived. Runtime supports
        # equality only; a future slice can add date-range filtering
        # for a real 30-day cutoff. Both empty for now — the visual
        # split still communicates the grouping.
        "recent":           {},
        "archive":          {},
    },

    # ── Status badge variants ──────────────────────────────────────
    # Match the Claude yoga demo's status colours: attended = calm
    # sage green, no-show = warm rust red, cancelled = neutral,
    # reviewed = accent (secondary brand hue).
    status_badges={
        "attended":     {"variant": "success", "label": "Attended"},
        "no_show":      {"variant": "danger",  "label": "No-show"},
        "cancelled":    {"variant": "neutral", "label": "Cancelled"},
        "reviewed":     {"variant": "accent",  "label": "Reviewed"},
        "pending":      {"variant": "warning", "label": "Pending"},
        "confirmed":    {"variant": "success", "label": "Confirmed"},
        "waitlisted":   {"variant": "warning", "label": "Waitlisted"},
        "completed":    {"variant": "success", "label": "Completed"},
        "checked_in":   {"variant": "success", "label": "Checked in"},
    },

    # What a studio opens the app to see. The front desk's question is
    # never "how many members do we have" — it's "is today filling, and
    # is anyone stuck outside a class they want?" So confirmed bookings
    # lead and the waitlist sits second: a waitlisted member is the one
    # number here you can act on in a minute (open a spot, add a class).
    # No-shows come last because they're a weekly pattern, not a
    # this-morning decision.
    dashboard_recipe={
        "kpis": [
            {"label": "Booked",         "entity": "bookings",
             "op": "count", "filter": {"status": ["confirmed", "checked_in"]}},
            {"label": "Waitlisted",     "entity": "bookings",
             "op": "count", "filter": {"status": ["waitlisted", "pending"]}},
            {"label": "Sessions",       "entity": "sessions", "op": "count"},
            {"label": "Members",        "entity": "members",  "op": "count"},
            {"label": "No-shows",       "entity": "bookings",
             "op": "count", "filter": {"status": ["no_show"]}},
        ],
        "sections": [
            # The schedule IS the studio's dashboard body — everything
            # else is commentary on it.
            {"title": "Today's schedule", "entity": "sessions",
             "shape": "schedule-grid", "limit": 8},
            {"title": "Waiting for a spot", "entity": "bookings",
             "shape": "card-list",
             "filter": {"status": ["waitlisted", "pending"]}, "limit": 6},
            {"title": "Recent reviews", "entity": "reviews",
             "shape": "card-list", "limit": 5},
        ],
    },

    # What each screen SHOWS. A booking business reads in the order it
    # speaks: what class, who, when, with whom. The class name leads
    # every booking-shaped list because that's how the front desk refers
    # to a reservation out loud ("the 6pm Vinyasa"), never by id or
    # booked-at date. Capacity vs booked count sit adjacent on sessions —
    # "is it full?" is the only question asked of that row.
    page_recipes={
        "bookings": {
            "list_columns": ["className", "memberName", "startAt",
                             "instructor", "status"],
            "filter_chips": ["status", "instructor"],
            "detail_sections": [
                {"label": "Booking",       "fields": ["className", "memberName",
                                                      "status"]},
                {"label": "When & where",  "fields": ["startAt", "endAt", "room"]},
                {"label": "Attendance",    "fields": ["checkedInAt",
                                                      "cancelledAt", "notes"]},
            ],
        },

        # The schedule row. Instructor and room are what a member picks
        # on, capacity is what the admin manages on — both fit.
        "sessions": {
            "list_columns": ["className", "instructor", "startAt", "room",
                             "capacity", "bookedCount"],
            "filter_chips": ["instructor", "room", "status"],
            "detail_sections": [
                {"label": "Class",    "fields": ["className", "description",
                                                 "level"]},
                {"label": "Schedule", "fields": ["startAt", "endAt", "room"]},
                {"label": "Capacity", "fields": ["capacity", "bookedCount",
                                                 "waitlistCount"]},
            ],
        },

        # A teacher directory is browsed for expertise, so specialties
        # sit right behind the name — the thing a member chooses on.
        "instructors": {
            "list_columns": ["fullName", "specialties", "certifications",
                             "email", "phone"],
            "filter_chips": ["specialties"],
            "detail_sections": [
                {"label": "Instructor", "fields": ["fullName", "bio", "photoUrl"]},
                {"label": "Teaching",   "fields": ["specialties",
                                                   "certifications",
                                                   "yearsExperience"]},
                {"label": "Contact",    "fields": ["email", "phone"]},
            ],
        },

        # Admin-only roster. Plan and renewal date are the two columns a
        # studio owner actually manages members by.
        "members": {
            "list_columns": ["fullName", "email", "plan", "joinedAt", "status"],
            "filter_chips": ["status", "plan"],
            "detail_sections": [
                {"label": "Member",     "fields": ["fullName", "email", "phone"]},
                {"label": "Membership", "fields": ["plan", "status", "joinedAt",
                                                   "renewsAt"]},
                {"label": "Activity",   "fields": ["bookingsCount",
                                                   "lastVisitAt", "noShowCount"]},
            ],
        },

        # Pricing is the whole point of a plan row; credits are the
        # second thing anyone compares.
        "plans": {
            "list_columns": ["name", "price", "billingPeriod", "classCredits",
                             "activeMembers"],
            "filter_chips": ["billingPeriod"],
            "detail_sections": [
                {"label": "Plan",     "fields": ["name", "description", "price",
                                                 "billingPeriod"]},
                {"label": "Includes", "fields": ["classCredits", "guestPasses",
                                                 "perks"]},
                {"label": "Uptake",   "fields": ["activeMembers", "status"]},
            ],
        },

        "rooms": {
            "list_columns": ["name", "capacity", "location", "equipment",
                             "status"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Space",          "fields": ["name", "description",
                                                       "location"]},
                {"label": "Capacity & kit", "fields": ["capacity", "equipment"]},
            ],
        },

        # A review is read as "which class, how many stars" — the
        # rating has to be scannable without opening the card.
        "reviews": {
            "list_columns": ["className", "memberName", "rating", "instructor",
                             "createdAt"],
            "filter_chips": ["rating", "instructor"],
            "detail_sections": [
                {"label": "Review",   "fields": ["className", "instructor",
                                                 "rating"]},
                {"label": "Feedback", "fields": ["comment", "createdAt"]},
                {"label": "Reviewer", "fields": ["memberName", "plan"]},
            ],
        },

        # A queue: position is the only thing the member asks about.
        "waitlists": {
            "list_columns": ["className", "memberName", "position", "startAt",
                             "status"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Waitlist entry", "fields": ["className", "memberName",
                                                       "position"]},
                {"label": "Session",        "fields": ["startAt", "room",
                                                       "instructor"]},
                {"label": "Outcome",        "fields": ["status", "promotedAt",
                                                       "notifiedAt"]},
            ],
        },
    },
)
