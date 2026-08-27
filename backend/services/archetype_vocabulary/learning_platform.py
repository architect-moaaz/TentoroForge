"""Learning-platform vocabulary — LMS, cohort-based courses, e-learning,
training, quizzes, assignments.

Shape mirrors booking_platform / banking_platform. Reads as "what does
every LMS (Canvas, Moodle, Teachable, Thinkific, Coursera) do that a
code generator would otherwise re-invent every time?"

Design decisions worth naming:

  - **Courses use card-grid.** Course browsing is a visual directory
    task — thumbnail + title + instructor + duration chip.

  - **Lessons/modules use card-list.** Within a course, lessons are
    ordered "your things" — one card per lesson, progress meter,
    single "start" action.

  - **Enrollments use table.** Instructor's roster view — sortable
    by name/progress/last-active, bulk-message support.

  - **Submissions use ledger-list.** Assignment submissions are
    append-only history per student.

  - **Certificates use card-grid.** Earned certificates are trophies —
    browsed by achievement, not compared as rows.

  - **Empty-state copy is friendly, encouraging.** Learning apps
    should feel motivating; mechanical empty-states break the tone.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


LEARNING_PLATFORM = ArchetypeVocabulary(
    id="learning-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Student / learner — enrolled surface + achievements.
        "student":    ["my-courses", "in-progress", "completed", "certificates"],
        "learner":    ["my-courses", "in-progress", "completed", "certificates"],

        # Instructor — teaching surface.
        "instructor": ["my-courses", "students", "assignments", "quizzes"],
        "teacher":    ["my-courses", "students", "assignments", "quizzes"],

        # Admin — catalog + user management + reporting.
        "admin":      ["dashboard", "courses", "users", "reports", "categories"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Catalog lifecycle.
        "courses":        ["published", "draft", "archived"],

        # Learner progress split.
        "my-courses":     ["in-progress", "completed", "not-started"],

        # Assignment lifecycle for a student's queue.
        "assignments":    ["due-soon", "submitted", "graded"],

        # Quiz lifecycle for a student's queue.
        "quizzes":        ["published", "draft", "past-due"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Course catalog — visual grid.
        "courses":       ComponentPreference(shape="card-grid",
                                              primary_field="title"),

        # Ordered lessons — one card per lesson.
        "lessons":       ComponentPreference(shape="card-list",
                                              primary_field="title"),
        "modules":       ComponentPreference(shape="card-list",
                                              primary_field="title"),

        # Enrollments — instructor's roster table.
        "enrollments":   ComponentPreference(shape="table",
                                              primary_field="studentName"),

        # Assignments — one card per assignment.
        "assignments":   ComponentPreference(shape="card-list",
                                              primary_field="title"),

        # Quizzes — one card per quiz.
        "quizzes":       ComponentPreference(shape="card-list",
                                              primary_field="title"),

        # Submissions — append-only per student.
        "submissions":   ComponentPreference(shape="ledger-list",
                                              primary_field="studentName"),

        # Certificates — achievement trophies.
        "certificates":  ComponentPreference(shape="card-grid",
                                              primary_field="courseName"),

        # People directories.
        "students":      ComponentPreference(shape="card-grid",
                                              primary_field="fullName"),
        "learners":      ComponentPreference(shape="card-grid",
                                              primary_field="fullName"),
        "instructors":   ComponentPreference(shape="card-grid",
                                              primary_field="fullName"),
        "teachers":      ComponentPreference(shape="card-grid",
                                              primary_field="fullName"),
    },

    # ── Empty states — friendly + encouraging ─────────────────────
    signature_states={
        # Learner surface.
        "empty_my_courses":     "You're not enrolled in anything yet. "
                                 "Browse the catalog to find your first course.",
        "empty_in_progress":    "Nothing in progress right now. Pick a "
                                 "course to jump back in.",
        "empty_completed":      "No completed courses yet. Finish your "
                                 "first one to see it here.",
        "empty_not_started":    "Nothing waiting to start.",
        "empty_certificates":   "No certificates yet. Complete a course "
                                 "to earn your first one.",

        # Instructor / catalog surface.
        "empty_courses":        "No courses yet. Publish your first "
                                 "course to start enrolling students.",
        "empty_published":      "Nothing published yet.",
        "empty_draft":          "No drafts in progress.",
        "empty_archived":       "Nothing archived yet.",
        "empty_students":       "No students enrolled yet.",
        "empty_learners":       "No learners enrolled yet.",
        "empty_lessons":        "No lessons added yet. Start structuring "
                                 "your course.",
        "empty_modules":        "No modules added yet.",

        # Assignments / quizzes.
        "empty_assignments":    "No assignments yet. Add one to give "
                                 "learners something to practice.",
        "empty_due_soon":       "Nothing due soon.",
        "empty_submitted":      "Nothing submitted yet.",
        "empty_graded":         "Nothing graded yet.",
        "empty_quizzes":        "No quizzes yet.",
        "empty_past_due":       "Nothing past due.",
        "empty_submissions":    "No submissions yet. Learner work will "
                                 "appear here as it comes in.",

        # Admin operational.
        "empty_dashboard":      "No activity yet. Metrics will populate "
                                 "as learners enroll and complete courses.",
        "empty_users":          "No users provisioned yet.",
        "empty_categories":     "No categories yet.",
        "empty_reports":        "No reports generated yet.",
        "empty_enrollments":    "No enrollments yet.",

        # Generic filtered-out state.
        "no_results":           "No matches for the current filter. Try "
                                 "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Learner progress.
        "in-progress":  {"status": ["in_progress", "active", "started"]},
        "completed":    {"status": ["completed", "finished", "passed"]},
        "not-started":  {"status": ["not_started", "enrolled", "new"]},

        # Catalog lifecycle.
        "published":    {"status": ["published", "live"]},
        "draft":        {"status": ["draft"]},
        "archived":     {"status": ["archived"]},

        # Assignment lifecycle.
        "due-soon":     {"status": ["assigned", "pending", "open"]},
        "submitted":    {"status": ["submitted", "turned_in"]},
        "graded":       {"status": ["graded", "returned"]},

        # Quiz lifecycle.
        "past-due":     {"status": ["past_due", "overdue", "expired"]},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        "not_started":  {"variant": "neutral", "label": "Not started"},
        "in_progress":  {"variant": "warning", "label": "In progress"},
        "completed":    {"variant": "success", "label": "Completed"},
        "passed":       {"variant": "success", "label": "Passed"},
        "failed":       {"variant": "danger",  "label": "Failed"},
        "graded":       {"variant": "success", "label": "Graded"},
        "submitted":    {"variant": "warning", "label": "Submitted"},
        "overdue":      {"variant": "danger",  "label": "Overdue"},
        "past_due":     {"variant": "danger",  "label": "Past due"},
        "published":    {"variant": "success", "label": "Published"},
        "draft":        {"variant": "neutral", "label": "Draft"},
        "archived":     {"variant": "neutral", "label": "Archived"},
    },

    # An instructor opens an LMS with two questions: what am I holding
    # up, and who is falling behind. Ungraded submissions are the first
    # because that queue blocks every learner in it; never-started
    # enrollments are the second because that is the drop-out cohort
    # while there is still time to intervene. Enrollment totals are a
    # vanity number — they say nothing about whether anyone is learning,
    # which is why average score earns a tile instead.
    dashboard_recipe={
        "kpis": [
            {"label": "Awaiting grading", "entity": "submissions",
             "op": "count", "filter": {"status": ["submitted"]}},
            {"label": "Past due",         "entity": "assignments",
             "op": "count", "filter": {"status": ["past_due", "overdue"]}},
            {"label": "Active learners",  "entity": "enrollments",
             "op": "count", "filter": {"status": ["in_progress"]}},
            {"label": "Never started",    "entity": "enrollments",
             "op": "count", "filter": {"status": ["not_started"]}},
            {"label": "Published courses", "entity": "courses",
             "op": "count", "filter": {"status": ["published"]}},
            {"label": "Average score",    "entity": "submissions",
             "op": "avg", "field": "score"},
        ],
        "sections": [
            {"title": "Awaiting grading", "entity": "submissions",
             "shape": "ledger-list", "filter": {"status": ["submitted"]},
             "limit": 10},
            {"title": "Assignments past due", "entity": "assignments",
             "shape": "card-list", "filter": {"status": ["past_due"]},
             "limit": 6},
            # Roster shape on purpose: this is the intervention list, and
            # intervening means scanning names against progress — the
            # exact comparison job enrollments already use a table for.
            {"title": "Learners at risk", "entity": "enrollments",
             "shape": "table", "filter": {"status": ["not_started"]},
             "limit": 8},
        ],
    },

    # Teaching screens are read learner-first: who, in what, how far.
    # Progress and last-active outrank every catalog attribute on a
    # roster because they are the two signals an instructor acts on;
    # on the catalog side the reader is choosing what to take, so the
    # order flips to title, who teaches it, and how hard it is.
    page_recipes={
        "courses": {
            "list_columns": ["title", "instructor", "category", "level",
                             "status", "enrolledCount"],
            "filter_chips": ["status", "category", "level"],
            "detail_sections": [
                {"label": "Course",     "fields": ["title", "description",
                                                   "category"]},
                {"label": "Delivery",   "fields": ["instructor", "level",
                                                   "durationHours"]},
                {"label": "Publishing", "fields": ["status", "price",
                                                   "publishedAt"]},
            ],
        },
        "lessons": {
            "list_columns": ["title", "module", "order", "durationMinutes",
                             "status"],
            "filter_chips": ["module", "status"],
            "detail_sections": [
                {"label": "Lesson",  "fields": ["title", "description",
                                                "module"]},
                {"label": "Content", "fields": ["videoUrl", "durationMinutes",
                                                "order"]},
            ],
        },
        "enrollments": {
            "list_columns": ["studentName", "courseName", "progress",
                             "status", "lastActiveAt", "grade"],
            "filter_chips": ["status", "courseName"],
            "detail_sections": [
                {"label": "Learner",  "fields": ["studentName", "email",
                                                 "courseName"]},
                {"label": "Progress", "fields": ["progress", "status",
                                                 "lastActiveAt"]},
                {"label": "Outcome",  "fields": ["grade", "completedAt",
                                                 "certificateIssued"]},
            ],
        },
        "assignments": {
            "list_columns": ["title", "courseName", "dueDate", "status",
                             "submissionCount"],
            "filter_chips": ["status", "courseName"],
            "detail_sections": [
                {"label": "Assignment", "fields": ["title", "instructions",
                                                   "courseName"]},
                {"label": "Schedule",   "fields": ["dueDate", "status"]},
                {"label": "Grading",    "fields": ["maxScore", "rubric",
                                                   "weight"]},
            ],
        },
        "quizzes": {
            "list_columns": ["title", "courseName", "questionCount",
                             "passingScore", "status"],
            "filter_chips": ["status", "courseName"],
            "detail_sections": [
                {"label": "Quiz",         "fields": ["title", "description",
                                                     "courseName"]},
                {"label": "Rules",        "fields": ["questionCount",
                                                     "passingScore",
                                                     "timeLimitMinutes"]},
                {"label": "Availability", "fields": ["status", "dueDate",
                                                     "attemptsAllowed"]},
            ],
        },
        "submissions": {
            "list_columns": ["studentName", "assignmentTitle", "submittedAt",
                             "status", "score"],
            "filter_chips": ["status", "assignmentTitle"],
            "detail_sections": [
                {"label": "Submission", "fields": ["studentName",
                                                   "assignmentTitle",
                                                   "submittedAt"]},
                {"label": "Grading",    "fields": ["status", "score",
                                                   "feedback"]},
                {"label": "Work",       "fields": ["fileUrl",
                                                   "attemptNumber"]},
            ],
        },
        "certificates": {
            "list_columns": ["courseName", "studentName", "issuedAt",
                             "credentialId"],
            "filter_chips": ["courseName"],
            "detail_sections": [
                {"label": "Certificate", "fields": ["courseName",
                                                    "studentName",
                                                    "credentialId"]},
                {"label": "Validity",    "fields": ["issuedAt", "expiresAt"]},
            ],
        },
        "students": {
            "list_columns": ["fullName", "email", "enrolledCourses",
                             "progress", "lastActiveAt"],
            "filter_chips": ["status", "enrolledCourses"],
            "detail_sections": [
                {"label": "Learner",      "fields": ["fullName", "email",
                                                     "phone"]},
                {"label": "Learning",     "fields": ["enrolledCourses",
                                                     "progress",
                                                     "lastActiveAt"]},
                {"label": "Achievements", "fields": ["completedCourses",
                                                     "certificates"]},
            ],
        },
        "instructors": {
            "list_columns": ["fullName", "email", "courseCount", "rating",
                             "status"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Instructor", "fields": ["fullName", "email",
                                                   "bio"]},
                {"label": "Teaching",   "fields": ["courseCount", "rating",
                                                   "specialties"]},
            ],
        },
    },
)
