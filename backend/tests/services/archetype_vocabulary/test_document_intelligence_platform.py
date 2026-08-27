"""Tests for the document-intelligence-platform archetype vocabulary.

Pins the contract downstream composers rely on: the vocabulary is
registered, the three canonical personas (uploader/reviewer/admin) have
screens, batches split into the industry-standard three-way lifecycle,
component shapes read as expected (ledger-list for batches, kanban for
review), and status badges carry the doc-intel colour semantics
(extracted=success, extraction_failed=danger, low_confidence=warning).
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    clear_cache,
    known_archetypes,
    load_vocabulary,
)


class TestDocIntelPlatformRegistered:
    def setup_method(self):
        clear_cache()

    def test_vocab_registered(self):
        assert "document-intelligence-platform" in known_archetypes()

    def test_vocab_loads_via_registry(self):
        v = load_vocabulary("document-intelligence-platform")
        assert v is not None
        assert v.id == "document-intelligence-platform"

    def test_load_normalises_input(self):
        for raw in (
            "Document Intelligence Platform",
            "document_intelligence_platform",
            "document-intelligence-platform",
            "DOCUMENT-INTELLIGENCE-PLATFORM",
        ):
            v = load_vocabulary(raw)
            assert v is not None, raw
            assert v.id == "document-intelligence-platform", raw


class TestDocIntelPersonas:
    """The three canonical doc-intel personas — uploader (or user /
    analyst), reviewer, admin — must all be represented."""

    def setup_method(self):
        clear_cache()

    def _vocab(self):
        v = load_vocabulary("document-intelligence-platform")
        assert v is not None
        return v

    def test_uploader_role_has_screens(self):
        v = self._vocab()
        keys = v.primary_screens_per_persona.keys()
        assert any(k in keys for k in ("uploader", "user", "analyst"))

    def test_reviewer_role_has_screens(self):
        v = self._vocab()
        keys = v.primary_screens_per_persona.keys()
        assert any(k in keys for k in ("reviewer", "data_reviewer"))

    def test_admin_role_has_screens(self):
        v = self._vocab()
        assert "admin" in v.primary_screens_per_persona

    def test_uploader_screens_cover_core_docintel_surfaces(self):
        v = self._vocab()
        for alias in ("uploader", "user", "analyst"):
            if alias in v.primary_screens_per_persona:
                screens = v.primary_screens_per_persona[alias]
                assert "upload" in screens
                assert "history" in screens
                # Search is the defining archetype surface — every
                # uploader alias must reach it directly.
                assert "search" in screens
                break


class TestDocIntelSectionRecipes:
    def setup_method(self):
        clear_cache()

    def _vocab(self):
        v = load_vocabulary("document-intelligence-platform")
        assert v is not None
        return v

    def test_history_splits_processing_completed_failed(self):
        v = self._vocab()
        assert v.section_recipes.get("history") == [
            "processing", "completed", "failed",
        ]

    def test_documents_splits_extracted_needsreview_failed(self):
        v = self._vocab()
        assert v.section_recipes.get("documents") == [
            "extracted", "needs-review", "extraction-failed",
        ]

    def test_review_queue_splits_lowconfidence_flagged_pending(self):
        v = self._vocab()
        assert v.section_recipes.get("review-queue") == [
            "low-confidence", "flagged", "corrections-pending",
        ]

    def test_search_results_splits_by_relevance_and_date(self):
        v = self._vocab()
        assert v.section_recipes.get("search-results") == [
            "by-relevance", "by-date",
        ]


class TestDocIntelComponentPreferences:
    def setup_method(self):
        clear_cache()

    def _vocab(self):
        v = load_vocabulary("document-intelligence-platform")
        assert v is not None
        return v

    def test_batches_shape_is_ledger_list(self):
        v = self._vocab()
        pref = v.component_preferences.get("batches")
        assert pref is not None
        assert pref.shape == "ledger-list"
        assert pref.primary_field == "batchId"

    def test_documents_shape_is_card_grid(self):
        v = self._vocab()
        pref = v.component_preferences.get("documents")
        assert pref is not None
        assert pref.shape == "card-grid"
        assert pref.primary_field == "filename"

    def test_extractions_shape_is_table(self):
        v = self._vocab()
        pref = v.component_preferences.get("extractions")
        assert pref is not None
        assert pref.shape == "table"
        assert pref.primary_field == "field_name"

    def test_search_results_shape_is_card_list(self):
        v = self._vocab()
        pref = v.component_preferences.get("search_results")
        assert pref is not None
        assert pref.shape == "card-list"

    def test_review_queue_shape_is_kanban(self):
        v = self._vocab()
        pref = v.component_preferences.get("review_queue")
        assert pref is not None
        assert pref.shape == "kanban"

    def test_sources_shape_is_card_grid(self):
        v = self._vocab()
        pref = v.component_preferences.get("sources")
        assert pref is not None
        assert pref.shape == "card-grid"


class TestDocIntelStatusBadges:
    def setup_method(self):
        clear_cache()

    def _vocab(self):
        v = load_vocabulary("document-intelligence-platform")
        assert v is not None
        return v

    def test_extracted_is_success(self):
        v = self._vocab()
        assert v.status_badges["extracted"]["variant"] == "success"

    def test_failed_is_danger(self):
        v = self._vocab()
        assert v.status_badges["failed"]["variant"] == "danger"

    def test_processing_is_warning(self):
        v = self._vocab()
        assert v.status_badges["processing"]["variant"] == "warning"

    def test_low_confidence_is_warning(self):
        v = self._vocab()
        assert v.status_badges["low_confidence"]["variant"] == "warning"

    def test_verified_is_success(self):
        v = self._vocab()
        assert v.status_badges["verified"]["variant"] == "success"

    def test_flagged_is_danger(self):
        v = self._vocab()
        assert v.status_badges["flagged"]["variant"] == "danger"

    def test_connected_is_success(self):
        v = self._vocab()
        assert v.status_badges["connected"]["variant"] == "success"


class TestDocIntelSignatureStates:
    def setup_method(self):
        clear_cache()

    def _vocab(self):
        v = load_vocabulary("document-intelligence-platform")
        assert v is not None
        return v

    def test_empty_batches_is_populated(self):
        v = self._vocab()
        assert v.signature_states.get("empty_batches"), (
            "empty_batches copy is missing"
        )

    def test_empty_documents_is_populated(self):
        v = self._vocab()
        assert v.signature_states.get("empty_documents")

    def test_empty_search_results_is_populated(self):
        v = self._vocab()
        # Note: keyed with a hyphen to match the section name.
        assert v.signature_states.get("empty_search-results")

    def test_empty_review_queue_is_populated(self):
        v = self._vocab()
        assert v.signature_states.get("empty_review-queue")

    def test_no_results_is_populated(self):
        v = self._vocab()
        assert v.signature_states.get("no_results")
