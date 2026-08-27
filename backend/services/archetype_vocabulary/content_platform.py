"""Content-platform vocabulary — CMS, blog, editorial, knowledge base,
publishing workflows.

Shape mirrors booking_platform / banking_platform. Reads as "what does
every CMS / editorial system (WordPress, Ghost, Sanity, Contentful,
Notion) do that a code generator would otherwise re-invent every time?"

Design decisions worth naming:

  - **Articles use card-list.** Each article is a title + snippet +
    author + status meta with a single "edit" or "read" action — the
    card-list pattern verbatim.

  - **Media use card-grid.** Media libraries are browsed visually —
    thumbnail grid is the industry-standard shape.

  - **Categories use card-grid.** Browse-by-taxonomy is a directory
    task; card-grid with count chips reads right.

  - **Tags use table.** Bulk tag management (rename, merge, delete)
    is comparison work — table.

  - **Comments use ledger-list.** Append-only conversation.

  - **Empty-state copy is friendly.** Editorial teams write copy for
    a living — mechanical empty-states read as embarrassing.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


CONTENT_PLATFORM = ArchetypeVocabulary(
    id="content-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Writer / author — content authoring surface.
        "writer": ["drafts", "published", "media", "tasks"],
        "author": ["drafts", "published", "media", "tasks"],

        # Editor — review + curate.
        "editor": ["review-queue", "published", "authors", "categories"],

        # Admin — configure taxonomy + users + settings.
        "admin":  ["dashboard", "users", "categories", "tags", "settings"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Article lifecycle.
        "articles":      ["draft", "in-review", "published", "archived"],
        "posts":         ["draft", "in-review", "published", "archived"],

        # Review queue lifecycle.
        "review-queue":  ["submitted", "revising", "approved"],

        # Media library by kind.
        "media":         ["images", "videos", "documents"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Articles / posts — card-list.
        "articles":     ComponentPreference(shape="card-list",
                                             primary_field="title"),
        "posts":        ComponentPreference(shape="card-list",
                                             primary_field="title"),
        "pages":        ComponentPreference(shape="card-list",
                                             primary_field="title"),

        # Media library — visual grid.
        "media":        ComponentPreference(shape="card-grid",
                                             primary_field="filename"),
        "assets":       ComponentPreference(shape="card-grid",
                                             primary_field="filename"),

        # Categories — browse by taxonomy.
        "categories":   ComponentPreference(shape="card-grid",
                                             primary_field="name"),

        # Tags — bulk-edit table.
        "tags":         ComponentPreference(shape="table",
                                             primary_field="label"),

        # Comments — append-only thread.
        "comments":     ComponentPreference(shape="ledger-list",
                                             primary_field="body"),

        # Authors directory.
        "authors":      ComponentPreference(shape="card-grid",
                                             primary_field="fullName"),
        "writers":      ComponentPreference(shape="card-grid",
                                             primary_field="fullName"),
    },

    # ── Empty states — friendly editorial voice ────────────────────
    signature_states={
        # Article surface.
        "empty_articles":       "No articles yet. Start writing — your "
                                 "first draft lands here.",
        "empty_posts":          "No posts yet. Start writing — your "
                                 "first draft lands here.",
        "empty_drafts":         "No drafts in progress. Start something new.",
        "empty_draft":          "No drafts saved.",
        "empty_in_review":      "Nothing under review — send a draft over "
                                 "when it's ready for edits.",
        "empty_published":      "Nothing published yet. Push your first "
                                 "post live to reach readers.",
        "empty_archived":       "Nothing archived yet.",

        # Review queue.
        "empty_review_queue":   "The review queue is clear. Nice work.",
        "empty_submitted":      "Nothing submitted for review.",
        "empty_revising":       "Nothing back with the author for revisions.",
        "empty_approved":       "No approved-and-waiting articles.",

        # Media surface.
        "empty_media":          "No media uploaded yet. Add images, video, "
                                 "or docs to reuse across posts.",
        "empty_images":         "No images uploaded.",
        "empty_videos":         "No videos uploaded.",
        "empty_documents":      "No documents uploaded.",

        # Taxonomy.
        "empty_categories":     "No categories yet. Add your first category "
                                 "to start grouping content.",
        "empty_tags":           "No tags yet. Tags appear here as writers "
                                 "add them to posts.",

        # Directory.
        "empty_authors":        "No authors on the roster yet.",
        "empty_writers":        "No writers on the roster yet.",

        # Comments.
        "empty_comments":       "No comments yet. Reader responses will "
                                 "appear here.",

        # Admin.
        "empty_dashboard":      "No activity yet. Metrics populate as "
                                 "posts go live and readers arrive.",
        "empty_users":          "No users provisioned yet.",
        "empty_tasks":          "No open tasks.",
        "empty_settings":       "Nothing configured yet.",

        # Generic filtered-out state.
        "no_results":           "No matches for the current filter. Try "
                                 "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Article lifecycle.
        "draft":        {"status": ["draft"]},
        "in-review":    {"status": ["in_review", "under_review", "submitted"]},
        "published":    {"status": ["published", "live"]},
        "archived":     {"status": ["archived", "unlisted"]},

        # Review queue lifecycle.
        "submitted":    {"status": ["submitted", "queued"]},
        "revising":     {"status": ["revising", "needs_revision", "changes_requested"]},
        "approved":     {"status": ["approved", "ready_to_publish"]},

        # Media by kind — no shared status filter (kind is a different
        # column); left empty for visual splits.
        "images":       {},
        "videos":       {},
        "documents":    {},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        "draft":        {"variant": "neutral", "label": "Draft"},
        "in_review":    {"variant": "warning", "label": "In review"},
        "under_review": {"variant": "warning", "label": "Under review"},
        "submitted":    {"variant": "warning", "label": "Submitted"},
        "published":    {"variant": "success", "label": "Published"},
        "archived":     {"variant": "neutral", "label": "Archived"},
        "rejected":     {"variant": "danger",  "label": "Rejected"},
        "scheduled":    {"variant": "accent",  "label": "Scheduled"},
        "approved":     {"variant": "success", "label": "Approved"},
    },

    # An editor's dashboard is a publishing calendar, not a traffic
    # report. What matters at 9am is the queue: what is waiting on me,
    # what I have cleared and can ship, what goes live next, and what is
    # still being written. Pageviews and post totals belong in analytics
    # — they tell an editor nothing about whether tomorrow's slot is
    # filled, which is the only thing the desk is actually anxious about.
    dashboard_recipe={
        "kpis": [
            {"label": "Awaiting review", "entity": "articles",
             "op": "count",
             "filter": {"status": ["in_review", "submitted",
                                   "under_review"]}},
            {"label": "Ready to publish", "entity": "articles",
             "op": "count", "filter": {"status": ["approved"]}},
            {"label": "Scheduled",       "entity": "articles",
             "op": "count", "filter": {"status": ["scheduled"]}},
            {"label": "Drafts in progress", "entity": "articles",
             "op": "count", "filter": {"status": ["draft"]}},
            # No status filter: comment moderation states vary wildly
            # per app, and a wrong guess silently zeroes the tile. The
            # raw count still answers "is there a pile waiting?".
            {"label": "New comments",    "entity": "comments",
             "op": "count"},
        ],
        "sections": [
            {"title": "Awaiting review", "entity": "articles",
             "shape": "card-list",
             "filter": {"status": ["in_review", "submitted"]}, "limit": 8},
            {"title": "Publishing next", "entity": "articles",
             "shape": "card-list",
             "filter": {"status": ["scheduled", "approved"]}, "limit": 6},
            {"title": "Recent comments", "entity": "comments",
             "shape": "ledger-list", "limit": 10},
        ],
    },

    # Editorial lists are scanned as headline, byline, state — a desk
    # reads WHO wrote it and WHERE it is in the workflow before anything
    # else, so status sits high rather than buried at the far right.
    # Detail sections split the way a CMS record is actually worked:
    # the writing, the editorial state, and the publishing metadata are
    # three different jobs done by three different people.
    page_recipes={
        "articles": {
            "list_columns": ["title", "author", "category", "status",
                             "publishedAt", "views"],
            "filter_chips": ["status", "category", "author"],
            "detail_sections": [
                {"label": "Article",    "fields": ["title", "slug",
                                                   "excerpt", "body"]},
                {"label": "Editorial",  "fields": ["author", "editor",
                                                   "status"]},
                {"label": "Publishing", "fields": ["category", "tags",
                                                   "publishedAt"]},
            ],
        },
        "posts": {
            "list_columns": ["title", "author", "category", "status",
                             "publishedAt"],
            "filter_chips": ["status", "category", "author"],
            "detail_sections": [
                {"label": "Post",       "fields": ["title", "slug",
                                                   "excerpt", "body"]},
                {"label": "Editorial",  "fields": ["author", "editor",
                                                   "status"]},
                {"label": "Publishing", "fields": ["category", "tags",
                                                   "publishedAt"]},
            ],
        },
        "pages": {
            "list_columns": ["title", "slug", "status", "author",
                             "updatedAt"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Page",       "fields": ["title", "slug", "body"]},
                {"label": "Publishing", "fields": ["status", "author",
                                                   "updatedAt"]},
            ],
        },
        "media": {
            "list_columns": ["filename", "type", "size", "uploadedBy",
                             "uploadedAt"],
            "filter_chips": ["type", "uploadedBy"],
            "detail_sections": [
                {"label": "Asset",      "fields": ["filename", "type",
                                                   "altText"]},
                {"label": "File",       "fields": ["size", "dimensions",
                                                   "url"]},
                {"label": "Provenance", "fields": ["uploadedBy",
                                                   "uploadedAt", "license"]},
            ],
        },
        "categories": {
            "list_columns": ["name", "slug", "articleCount", "description"],
            "filter_chips": ["parentCategory"],
            "detail_sections": [
                {"label": "Category", "fields": ["name", "slug",
                                                 "description"]},
                {"label": "Usage",    "fields": ["articleCount",
                                                 "parentCategory"]},
            ],
        },
        "tags": {
            "list_columns": ["label", "slug", "usageCount"],
            "filter_chips": [],
            "detail_sections": [
                {"label": "Tag",   "fields": ["label", "slug", "description"]},
                {"label": "Usage", "fields": ["usageCount"]},
            ],
        },
        "comments": {
            "list_columns": ["body", "author", "articleTitle", "status",
                             "createdAt"],
            "filter_chips": ["status", "articleTitle"],
            "detail_sections": [
                {"label": "Comment",    "fields": ["body", "author",
                                                   "email"]},
                {"label": "Context",    "fields": ["articleTitle",
                                                   "createdAt"]},
                {"label": "Moderation", "fields": ["status", "flagged"]},
            ],
        },
        "authors": {
            "list_columns": ["fullName", "email", "role", "articleCount",
                             "status"],
            "filter_chips": ["role", "status"],
            "detail_sections": [
                {"label": "Author", "fields": ["fullName", "email", "bio"]},
                {"label": "Output", "fields": ["articleCount",
                                               "publishedCount",
                                               "lastPublishedAt"]},
            ],
        },
    },
)
