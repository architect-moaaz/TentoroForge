"""Tests for requirement_contract — extracts USER-NAMED constraints from the
raw prompt so the plan validator + fidelity critic can hold the LLM to them.

The contract turns "user words" into a HARD gate: named routes, named
components (per page), named action-types, an explicit landing declaration,
and out-of-scope negations. Every one becomes a check the LLM cannot
silently drop or rename (as it did in the Banking Archive gen — `/history`
became `/batches`, `ocr_document` became `http_call`, etc).
"""
from __future__ import annotations

import pytest

from services.requirement_contract import extract_contract, RequirementContract


# ────────────────────────────────────────────────────────────
# Fixtures — the Banking Archive prompt (verbatim from igi1eqs7)
# ────────────────────────────────────────────────────────────

_BANKING_PROMPT = """
Build "Banking Archive" — a document-intelligence app for a bank's back-office
team to digitise, OCR, and search paper/PDF records on-prem.

Personas:
- Archivist: uploads batches, watches processing, spot-checks results.
- Admin: manages users + retention policies (out of scope for v1 pages).

Workflows:

2. IngestDocument workflow (one run per document, async):
   Step 1 — ocr_document (PaddleOCR sidecar): ocrFileRef={{input.fileId}}.
   Step 2 — ai_classify: labels=[statement, contract, kyc].
   Step 3 — ai_extract: fields=[account_number, customer_name].

Pages:
/upload  — Archivist uploads. Multi-file dropzone + Upload button.
/history — (landing) Table of Batches, newest first.
/history/{id} — Batch detail with Table of Documents.
/search  — SearchInput bound to a tsvector search.
/document/{id} — Two-column viewer with DescriptionList + Banner when failed.

Design:
- Landing route: /history.
- Nav: Upload, History, Search.
- No currency formatting.

Non-goals (out of scope for v1):
- Editing extracted fields inline.
- Payments, transfers, any money movement.
"""


# ────────────────────────────────────────────────────────────
# Named routes
# ────────────────────────────────────────────────────────────

class TestNamedRoutes:
    def test_extracts_slash_prefixed_paths(self):
        c = extract_contract(_BANKING_PROMPT)
        paths = {r["path"] for r in c.named_routes}
        # Slash-prefixed tokens at the start of a description bullet.
        assert "/upload" in paths
        assert "/history" in paths
        assert "/search" in paths

    def test_extracts_parameterised_paths(self):
        c = extract_contract(_BANKING_PROMPT)
        paths = {r["path"] for r in c.named_routes}
        # {id} params kept verbatim so the planner can't drop them.
        assert "/history/{id}" in paths
        assert "/document/{id}" in paths

    def test_dedupes_repeats(self):
        c = extract_contract("Landing is /home. Also see /home for details.")
        paths = [r["path"] for r in c.named_routes]
        assert paths.count("/home") == 1

    def test_ignores_url_prefixes_and_versions(self):
        c = extract_contract("Docs at https://example.com/api/v1 not a route.")
        paths = {r["path"] for r in c.named_routes}
        # /api/v1 is part of a full URL — not a user-named app route.
        assert "/api/v1" not in paths
        assert "/api" not in paths


# ────────────────────────────────────────────────────────────
# Named components — per page
# ────────────────────────────────────────────────────────────

class TestNamedComponents:
    def test_component_named_on_specific_page(self):
        c = extract_contract(_BANKING_PROMPT)
        # "/search  — SearchInput bound to a tsvector search."
        pairs = {(nc["page"], nc["component"]) for nc in c.named_components}
        assert ("/search", "SearchInput") in pairs

    def test_multiple_components_on_one_page(self):
        c = extract_contract(_BANKING_PROMPT)
        pairs = {(nc["page"], nc["component"]) for nc in c.named_components}
        # /document mentions DescriptionList AND Banner
        assert ("/document/{id}", "DescriptionList") in pairs
        assert ("/document/{id}", "Banner") in pairs

    def test_table_recognised_capitalised(self):
        c = extract_contract(_BANKING_PROMPT)
        pairs = {(nc["page"], nc["component"]) for nc in c.named_components}
        # /history — "Table of Batches"; /history/{id} — "Table of Documents"
        assert ("/history", "Table") in pairs
        assert ("/history/{id}", "Table") in pairs

    def test_file_upload_recognised(self):
        c = extract_contract(_BANKING_PROMPT)
        pairs = {(nc["page"], nc["component"]) for nc in c.named_components}
        # /upload has "Multi-file dropzone + Upload button" → FileUpload
        components_on_upload = {c for p, c in pairs if p == "/upload"}
        assert "FileUpload" in components_on_upload

    def test_lowercase_prose_words_not_treated_as_components(self):
        c = extract_contract("On /home: show the user's recent orders.")
        pairs = {(nc["page"], nc["component"]) for nc in c.named_components}
        # Common English words shouldn't be interpreted as component types.
        assert not any(c.lower() in {"the", "user", "recent", "orders"} for _, c in pairs)


# ────────────────────────────────────────────────────────────
# Named action-types
# ────────────────────────────────────────────────────────────

class TestNamedActionTypes:
    def test_snake_case_action_types_extracted(self):
        c = extract_contract(_BANKING_PROMPT)
        ats = {at["action_type"] for at in c.named_action_types}
        assert "ocr_document" in ats
        assert "ai_classify" in ats
        assert "ai_extract" in ats

    def test_only_known_action_types_from_registry(self):
        """The extractor should not scoop up random snake_case identifiers
        that happen to appear — only ones from a whitelist of real
        workflow action types."""
        c = extract_contract("The plan uses a report_generation step "
                             "and then send_email + ai_extract.")
        ats = {at["action_type"] for at in c.named_action_types}
        assert "send_email" in ats
        assert "ai_extract" in ats
        # report_generation isn't a registered action-type → not extracted.
        assert "report_generation" not in ats

    def test_workflow_attribution_when_named_nearby(self):
        c = extract_contract(_BANKING_PROMPT)
        # ocr_document appears under "IngestDocument workflow" heading.
        ocr_entries = [at for at in c.named_action_types if at["action_type"] == "ocr_document"]
        assert ocr_entries
        # workflow field may be None or "IngestDocument" — both fine, but
        # if set, it must match the nearby heading.
        for entry in ocr_entries:
            wf = entry.get("workflow")
            assert wf is None or wf == "IngestDocument"


# ────────────────────────────────────────────────────────────
# Landing route
# ────────────────────────────────────────────────────────────

class TestLandingRoute:
    def test_landing_route_explicit(self):
        c = extract_contract(_BANKING_PROMPT)
        assert c.landing_route == "/history"

    def test_landing_route_variants(self):
        assert extract_contract("Landing route: /home").landing_route == "/home"
        assert extract_contract("Landing: /dash").landing_route == "/dash"
        assert extract_contract("The landing page is /overview.").landing_route == "/overview"

    def test_no_landing_declared(self):
        c = extract_contract("Build a CRM with contacts and deals.")
        assert c.landing_route is None


# ────────────────────────────────────────────────────────────
# Out-of-scope negations
# ────────────────────────────────────────────────────────────

class TestOutOfScope:
    def test_bulleted_out_of_scope(self):
        c = extract_contract(_BANKING_PROMPT)
        # Bullets under "Non-goals (out of scope for v1):"
        assert any("payments" in phrase.lower() for phrase in c.out_of_scope)
        assert any("editing extracted fields inline" in phrase.lower() for phrase in c.out_of_scope)

    def test_parenthetical_out_of_scope(self):
        c = extract_contract(_BANKING_PROMPT)
        # "Admin: manages users + retention policies (out of scope for v1 pages)."
        # → the surface Admin should be flagged out-of-scope.
        flat = " | ".join(c.out_of_scope).lower()
        assert "admin" in flat

    def test_no_negations_returns_empty(self):
        c = extract_contract("Build a simple todo list.")
        assert c.out_of_scope == []


# ────────────────────────────────────────────────────────────
# Contract stability — same input → same output; empty prompt safe.
# ────────────────────────────────────────────────────────────

class TestContractStability:
    def test_empty_prompt_returns_empty_contract(self):
        c = extract_contract("")
        assert c.named_routes == []
        assert c.named_components == []
        assert c.named_action_types == []
        assert c.landing_route is None
        assert c.out_of_scope == []

    def test_dict_shape_serialises_cleanly(self):
        """Contract must be JSON-round-trippable for storage in
        requirement.json.parsed_directives."""
        import json
        c = extract_contract(_BANKING_PROMPT)
        payload = c.to_dict()
        # Round-trip.
        s = json.dumps(payload)
        back = json.loads(s)
        assert set(back.keys()) == {
            "named_routes", "named_components", "named_action_types",
            "landing_route", "out_of_scope",
        }

    def test_deterministic(self):
        a = extract_contract(_BANKING_PROMPT).to_dict()
        b = extract_contract(_BANKING_PROMPT).to_dict()
        assert a == b
