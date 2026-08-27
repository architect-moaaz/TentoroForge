"""Document-intelligence-platform vocabulary — OCR, extraction, doc AI,
searchable knowledge bases. Docparser / Rossum / Nanonets / Textract /
Google Document AI / knowledge-base products where the whole app is
"upload a doc, get structured data + text search back".

Reference implementation matched to the shape every doc-intel product
carries — the conventions the LLM would otherwise re-invent every time.
Same shape as banking_platform.py; values are what document-intelligence
IS instead of what banking is.

Design decisions worth naming:

  - **Batches use ledger-list, documents use card-grid.** An upload
    batch is a lifecycle row — batchId + count + status + timestamp,
    dense, scannable in date order. A document is a "your things"
    tile — filename + status + snippet, browsed by identity. Two
    different mental models on adjacent screens.

  - **Search results use card-list, ranked.** The output of full-text
    search across the extracted corpus is a card-list, one pill-card
    per hit (icon + title + snippet + entity badge + click →
    source). Distinct from documents itself.

  - **Review queue uses kanban.** Extraction results with low
    confidence flow through low-confidence → flagged → corrections-
    pending → verified — kanban makes the flow literal.

  - **Empty-state copy is professional-utility.** Doc-intel users are
    ops folks + data analysts running batches at 2am; chirpy copy
    reads unprofessional. Warm-but-terse.

  - **Search vocabulary is the defining archetype signal.** Every
    persona has a "search" screen or section; the keywords list
    carries "full-text search / knowledge base / indexed search"
    exactly so a "searchable document archive" description snaps to
    this archetype rather than falling to content-platform.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


DOCUMENT_INTELLIGENCE_PLATFORM = ArchetypeVocabulary(
    id="document-intelligence-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    # Uploader/user/analyst — the "I dropped files, now what came out"
    # surface. Reviewer — the queue of low-confidence extractions to fix
    # by hand. Admin — the operating panel: sources, rules, users,
    # retention. Every persona keeps `search` reachable — search IS the
    # product.
    primary_screens_per_persona={
        "uploader":         ["upload", "history", "search", "documents"],
        "user":             ["upload", "history", "search", "documents"],
        "analyst":          ["upload", "history", "search", "documents"],

        "reviewer":         ["review-queue", "extraction-errors", "confidence-low"],
        "data_reviewer":    ["review-queue", "extraction-errors", "confidence-low"],

        "admin":            ["dashboard", "sources", "extraction-rules",
                              "users", "retention"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Upload batches lifecycle — the three states every processing
        # queue splits by.
        "history":                  ["processing", "completed", "failed"],
        "batches":                  ["processing", "completed", "failed"],

        # Documents by extraction outcome. `extracted` = done, ready.
        # `needs-review` = extraction succeeded but confidence dipped
        # below the threshold. `extraction-failed` = the doc itself
        # couldn't be parsed (unsupported format, corrupted, etc).
        "documents":                ["extracted", "needs-review", "extraction-failed"],

        # Review queue lifecycle — the three buckets a doc-intel review
        # ops team splits by. `corrections-pending` = a reviewer touched
        # the row but hasn't submitted yet.
        "review-queue":             ["low-confidence", "flagged", "corrections-pending"],

        # Search results split by rank vs freshness — every doc-intel
        # search screen offers these two lenses.
        "search-results":           ["by-relevance", "by-date"],

        # Sources (S3 buckets, mail hooks, upload endpoints) split by
        # connection health.
        "sources":                  ["connected", "disconnected", "failed"],

        # Retention lifecycle — GDPR + policy-driven archival + purge.
        "retention":                ["active", "archived", "purged"],
    },

    # ── Shape per entity ────────────────────────────────────────────
    component_preferences={
        # Batches / upload_batches / document_batches — ledger-list. A
        # batch is a lifecycle row with batchId + count + status +
        # timestamp; ledger-list (Slice-3) is the exact shape.
        "batches":                  ComponentPreference(shape="ledger-list",
                                                        primary_field="batchId"),
        "upload_batches":           ComponentPreference(shape="ledger-list",
                                                        primary_field="batchId"),
        "document_batches":         ComponentPreference(shape="ledger-list",
                                                        primary_field="batchId"),

        # Documents themselves — card-grid. Filename + status + a small
        # snippet, browsed by identity.
        "documents":                ComponentPreference(shape="card-grid",
                                                        primary_field="filename"),

        # Extractions / extracted_fields / extraction_results — table.
        # Dense field-by-field view (field_name + value + confidence)
        # is what reviewers compare, so a real table earns its place.
        "extractions":              ComponentPreference(shape="table",
                                                        primary_field="field_name"),
        "extracted_fields":         ComponentPreference(shape="table",
                                                        primary_field="field_name"),
        "extraction_results":       ComponentPreference(shape="table",
                                                        primary_field="field_name"),

        # Search results — card-list. One pill-card per hit (icon +
        # title + snippet + entity badge). Distinct from the browse
        # `documents` grid.
        "search_results":           ComponentPreference(shape="card-list",
                                                        primary_field="title"),

        # Extraction rules / templates — table. Admin config, dense
        # column-per-attribute view.
        "extraction_rules":         ComponentPreference(shape="table",
                                                        primary_field="name"),
        "templates":                ComponentPreference(shape="table",
                                                        primary_field="name"),

        # Sources / connectors — card-grid. "Your saved connectors"
        # browsed by identity, not compared as rows.
        "sources":                  ComponentPreference(shape="card-grid",
                                                        primary_field="name"),
        "connectors":               ComponentPreference(shape="card-grid",
                                                        primary_field="name"),

        # Review queue / review items — kanban. The lifecycle IS the
        # UI (low-confidence → flagged → corrections-pending).
        "review_queue":             ComponentPreference(shape="kanban",
                                                        primary_field="documentName"),
        "review_items":             ComponentPreference(shape="kanban",
                                                        primary_field="documentName"),
    },

    # ── Empty-state copy — professional-utility, never chirpy ──────
    signature_states={
        # Uploader surface — the moment they open the app cold, or after
        # clearing their inbox.
        "empty_upload":             "Drop files here to get started, or "
                                     "browse from your device.",
        "empty_history":            "No uploads yet. Drop files to get "
                                     "started.",
        "empty_batches":            "No uploads yet. Drop files to get "
                                     "started.",
        "empty_documents":          "No extracted documents yet. Uploads "
                                     "land here after processing.",
        "empty_processing":         "Nothing processing right now.",
        "empty_completed":          "No completed batches yet.",
        "empty_failed":             "No failed batches. Everything ran "
                                     "cleanly.",
        "empty_extracted":          "No extracted documents in this view.",
        "empty_needs_review":       "No documents need review. Extractions "
                                     "look confident.",
        "empty_extraction_failed":  "No extraction failures. Every upload "
                                     "parsed cleanly.",

        # Search surface — pristine (no query) vs no-hits are separate
        # states so the copy can distinguish "type to start" from "try
        # different keywords".
        "empty_search":             "Search across your documents.",
        "empty_search-results":     "No matches found. Try different "
                                     "keywords or check spelling.",
        "empty_by_relevance":       "No matches for the current query.",
        "empty_by_date":            "No matches for the current query.",

        # Reviewer surface.
        "empty_review-queue":       "Queue is clear. All extractions look "
                                     "good.",
        "empty_low_confidence":     "No low-confidence extractions right "
                                     "now.",
        "empty_flagged":            "Nothing flagged.",
        "empty_corrections_pending": "No corrections in progress.",
        "empty_extraction-errors":  "No extraction errors on file.",
        "empty_confidence-low":     "No low-confidence extractions right "
                                     "now.",

        # Admin surface.
        "empty_dashboard":          "No activity yet. Metrics will appear "
                                     "here once uploads start processing.",
        "empty_sources":            "No sources connected. Add an upload "
                                     "endpoint or S3 bucket to start "
                                     "ingesting.",
        "empty_connected":          "No connected sources yet.",
        "empty_disconnected":       "No disconnected sources.",
        "empty_extraction-rules":   "No extraction rules configured. Add "
                                     "your first template to start "
                                     "extracting structured data.",
        "empty_users":              "No users provisioned yet.",
        "empty_retention":          "No retention policy configured. All "
                                     "documents are retained indefinitely.",
        "empty_active":             "No active documents in this policy.",
        "empty_archived":           "Nothing archived yet.",
        "empty_purged":             "Nothing purged yet.",

        # Generic filtered-out state.
        "no_results":               "No matches for the current filter. "
                                     "Try widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Batch lifecycle.
        "processing":               {"status": ["processing", "in_progress", "running"]},
        "completed":                {"status": ["completed", "done", "extracted"]},
        "failed":                   {"status": ["failed", "error", "rejected"]},

        # Document extraction outcome.
        "extracted":                {"status": ["extracted", "completed", "done"]},
        "needs-review":             {"status": ["needs_review", "low_confidence"]},
        "extraction-failed":        {"status": ["extraction_failed", "failed", "unparseable"]},

        # Review queue lifecycle.
        "low-confidence":           {"status": ["low_confidence", "flagged_low"]},
        "flagged":                  {"status": ["flagged", "escalated"]},
        "corrections-pending":      {"status": ["in_correction", "pending_submit"]},

        # Search-results split — no server-side filter (ranking mode is
        # UI-side). Empty dict = visual split only.
        "by-relevance":             {},
        "by-date":                  {},

        # Source health.
        "connected":                {"status": ["connected", "active", "healthy"]},
        "disconnected":             {"status": ["disconnected", "inactive"]},

        # Retention lifecycle.
        "active":                   {"status": ["active", "retained"]},
        "archived":                 {"status": ["archived"]},
        "purged":                   {"status": ["purged", "deleted"]},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        # Batch lifecycle.
        "queued":               {"variant": "neutral", "label": "Queued"},
        "processing":           {"variant": "warning", "label": "Processing"},
        "in_progress":          {"variant": "warning", "label": "In progress"},
        "running":              {"variant": "warning", "label": "Running"},
        "completed":            {"variant": "success", "label": "Completed"},
        "done":                 {"variant": "success", "label": "Done"},
        "extracted":            {"variant": "success", "label": "Extracted"},
        "failed":               {"variant": "danger",  "label": "Failed"},
        "error":                {"variant": "danger",  "label": "Error"},
        "rejected":             {"variant": "danger",  "label": "Rejected"},

        # Extraction outcome.
        "needs_review":         {"variant": "warning", "label": "Needs review"},
        "low_confidence":       {"variant": "warning", "label": "Low confidence"},
        "flagged_low":          {"variant": "warning", "label": "Low confidence"},
        "extraction_failed":    {"variant": "danger",  "label": "Extraction failed"},
        "unparseable":          {"variant": "danger",  "label": "Unparseable"},
        "verified":             {"variant": "success", "label": "Verified"},

        # Review queue.
        "flagged":              {"variant": "danger",  "label": "Flagged"},
        "escalated":            {"variant": "danger",  "label": "Escalated"},
        "in_correction":        {"variant": "warning", "label": "In correction"},
        "pending_submit":       {"variant": "warning", "label": "Pending submit"},

        # Source health.
        "connected":            {"variant": "success", "label": "Connected"},
        "active":               {"variant": "success", "label": "Active"},
        "healthy":              {"variant": "success", "label": "Healthy"},
        "disconnected":         {"variant": "warning", "label": "Disconnected"},
        "inactive":             {"variant": "neutral", "label": "Inactive"},

        # Retention lifecycle.
        "retained":             {"variant": "success", "label": "Retained"},
        "archived":             {"variant": "neutral", "label": "Archived"},
        "purged":               {"variant": "neutral", "label": "Purged"},
        "deleted":              {"variant": "neutral", "label": "Deleted"},
    },

    # A doc-intel operator opens the app to answer one question: what
    # does the machine want a human for? Everything that extracted
    # cleanly is already done and needs no screen space. So the tiles
    # are the exception queue — review backlog, shaky confidence, dead
    # batches, broken ingest — plus average confidence, which is the
    # one number that tells you whether the model itself is drifting.
    dashboard_recipe={
        "kpis": [
            {"label": "Needs review",       "entity": "documents",
             "op": "count", "filter": {"status": ["needs_review", "low_confidence"]}},
            {"label": "Low confidence",     "entity": "extractions",
             "op": "count", "filter": {"status": ["low_confidence", "flagged_low"]}},
            {"label": "Failed batches",     "entity": "batches",
             "op": "count", "filter": {"status": ["failed", "error"]}},
            {"label": "Processing now",     "entity": "batches",
             "op": "count", "filter": {"status": ["processing", "in_progress"]}},
            {"label": "Avg confidence",     "entity": "extractions",
             "op": "avg", "field": "confidenceScore"},
            {"label": "Sources offline",    "entity": "sources",
             "op": "count", "filter": {"status": ["disconnected", "inactive"]}},
        ],
        "sections": [
            # The review backlog is the operator's actual work queue;
            # it leads even though it is the least "dashboard-y" shape.
            {"title": "Documents needing review", "entity": "documents",
             "shape": "card-grid",
             "filter": {"status": ["needs_review", "low_confidence"]}, "limit": 8},

            # Field-level, because "which field did it fumble" is the
            # question — the document is fine, one value isn't.
            {"title": "Low-confidence extractions", "entity": "extractions",
             "shape": "table",
             "filter": {"status": ["low_confidence", "flagged_low"]}, "limit": 8},

            # "Did my batch land?" — the single most-asked question by
            # anyone who dropped files ten minutes ago.
            {"title": "Recent upload batches", "entity": "batches",
             "shape": "ledger-list", "limit": 10},
        ],
    },

    # Reading order per screen. Confidence is a first-class column
    # everywhere it exists — in doc-intel it is the field that decides
    # whether a human touches the row at all, so it never gets buried
    # behind timestamps.
    page_recipes={
        "documents": {
            "list_columns": ["filename", "documentType", "status",
                             "confidenceScore", "pageCount", "uploadedAt"],
            "filter_chips": ["status", "documentType"],
            "detail_sections": [
                {"label": "Document",   "fields": ["filename", "documentType",
                                                   "pageCount", "fileSize"]},
                {"label": "Extraction", "fields": ["status", "confidenceScore",
                                                   "extractedAt", "templateName"]},
                {"label": "Source",     "fields": ["source", "uploadedBy",
                                                   "uploadedAt", "batchId"]},
            ],
        },
        "batches": {
            "list_columns": ["batchId", "status", "documentCount", "source",
                             "submittedBy", "createdAt"],
            "filter_chips": ["status", "source"],
            "detail_sections": [
                {"label": "Batch",    "fields": ["batchId", "source", "submittedBy"]},
                {"label": "Progress", "fields": ["status", "documentCount",
                                                 "processedCount", "failedCount"]},
                {"label": "Timing",   "fields": ["createdAt", "completedAt",
                                                 "durationSeconds"]},
            ],
        },
        "extractions": {
            # field → value → confidence is the reviewer's eye path:
            # what was asked for, what came back, do I trust it.
            "list_columns": ["fieldName", "value", "confidenceScore",
                             "status", "documentName", "reviewedBy"],
            "filter_chips": ["status", "fieldName"],
            "detail_sections": [
                {"label": "Field",      "fields": ["fieldName", "value", "dataType"]},
                {"label": "Confidence", "fields": ["confidenceScore", "status",
                                                   "pageNumber", "boundingBox"]},
                {"label": "Review",     "fields": ["reviewedBy", "reviewedAt",
                                                   "correctedValue"]},
            ],
        },
        "review_queue": {
            "list_columns": ["documentName", "status", "confidenceScore",
                             "assignedTo", "flaggedReason", "queuedAt"],
            "filter_chips": ["status", "assignedTo"],
            "detail_sections": [
                {"label": "Item",       "fields": ["documentName", "status",
                                                   "flaggedReason"]},
                {"label": "Confidence", "fields": ["confidenceScore", "fieldCount",
                                                   "lowConfidenceFieldCount"]},
                {"label": "Assignment", "fields": ["assignedTo", "queuedAt",
                                                   "resolvedAt"]},
            ],
        },
        "sources": {
            "list_columns": ["name", "sourceType", "status", "documentCount",
                             "lastSyncedAt"],
            "filter_chips": ["status", "sourceType"],
            "detail_sections": [
                {"label": "Source",     "fields": ["name", "sourceType",
                                                   "description"]},
                {"label": "Connection", "fields": ["status", "endpoint",
                                                   "credentialRef", "lastSyncedAt"]},
                {"label": "Volume",     "fields": ["documentCount",
                                                   "lastDocumentAt"]},
            ],
        },
        "extraction_rules": {
            "list_columns": ["name", "documentType", "fieldCount", "status",
                             "updatedAt"],
            "filter_chips": ["status", "documentType"],
            "detail_sections": [
                {"label": "Rule",      "fields": ["name", "description",
                                                  "documentType"]},
                {"label": "Fields",    "fields": ["fieldCount", "requiredFields",
                                                  "confidenceThreshold"]},
                {"label": "Lifecycle", "fields": ["status", "createdBy",
                                                  "updatedAt"]},
            ],
        },
        "search_results": {
            # Search IS the product here, so the hit row is authored
            # rather than left to fall back to a generic table: title,
            # the snippet that proves the match, then the rank.
            "list_columns": ["title", "snippet", "documentType", "score",
                             "source"],
            "filter_chips": ["documentType", "source"],
            "detail_sections": [
                {"label": "Match",    "fields": ["title", "snippet", "score"]},
                {"label": "Document", "fields": ["documentType", "source",
                                                 "uploadedAt"]},
            ],
        },
    },
)
