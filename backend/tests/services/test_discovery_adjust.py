"""Tests for services.discovery_adjust — DA anchor.

Every op tested for happy path, idempotency, input purity, and
rejection of invalid input. Same shape as test_plan_adjust — the
reliability guarantee for the Adjust-Discovery flow rests on these
ops staying honest.

The dossier shape targeted here is the *domain-discovery* dossier
rendered by DiscoveryCard (domain / complianceNotes / designPatterns /
entitySuggestions / commonPitfalls / visualLanguage), NOT the
structured brief (actors + journeys).
"""
from __future__ import annotations

import copy

import pytest

from services.discovery_adjust import (
    DossierAdjustError,
    add_compliance,
    add_design_pattern,
    add_entity_suggestion,
    add_pitfall,
    compute_diff,
    remove_compliance,
    remove_design_pattern,
    remove_entity_suggestion,
    remove_pitfall,
    set_description,
    set_domain,
    set_visual_language,
    validate_dossier_shape,
)


def _fresh_dossier() -> dict:
    return {
        "domain": "Recruitment",
        "domainAliases": ["Hiring", "Talent acquisition"],
        "description": "An applicant-tracking system for recruiters.",
        "confidence": 0.85,
        "complianceNotes": ["gdpr"],
        "designPatterns": [
            {"name": "Candidate pipeline",
             "description": "Kanban of applications by stage."},
        ],
        "entitySuggestions": [
            {"name": "Applicant", "likelyFields": ["name", "email"]},
        ],
        "commonPitfalls": ["Undifferentiated status labels"],
        "uncertainAreas": [],
        "visualLanguage": {
            "paletteCharacter": "professional",
            "typographyTone": "clean",
            "densityPreference": "medium",
        },
    }


# ------------------------------------------------------------------------- #
# domain / description                                                       #
# ------------------------------------------------------------------------- #

class TestSetDomain:
    def test_replaces(self):
        d = _fresh_dossier()
        d2 = set_domain(d, text="Hospitality")
        assert d2["domain"] == "Hospitality"

    def test_rejects_empty(self):
        with pytest.raises(DossierAdjustError):
            set_domain(_fresh_dossier(), text="   ")

    def test_does_not_mutate_input(self):
        d = _fresh_dossier()
        original = copy.deepcopy(d)
        set_domain(d, text="Hospitality")
        assert d == original


class TestSetDescription:
    def test_replaces(self):
        d = _fresh_dossier()
        d2 = set_description(d, text="New description")
        assert d2["description"] == "New description"

    def test_empty_clears(self):
        d = _fresh_dossier()
        d2 = set_description(d, text="")
        assert d2["description"] == ""


# ------------------------------------------------------------------------- #
# compliance                                                                 #
# ------------------------------------------------------------------------- #

class TestCompliance:
    def test_add_new(self):
        d = _fresh_dossier()
        d2 = add_compliance(d, regime="hipaa")
        assert "hipaa" in d2["complianceNotes"]

    def test_add_idempotent(self):
        d = _fresh_dossier()
        d2 = add_compliance(d, regime="gdpr")
        assert d2["complianceNotes"].count("gdpr") == 1

    def test_add_lowercases(self):
        d = _fresh_dossier()
        d2 = add_compliance(d, regime="HIPAA")
        assert "hipaa" in d2["complianceNotes"]

    def test_add_rejects_unknown_regime(self):
        with pytest.raises(DossierAdjustError, match="compliance regime"):
            add_compliance(_fresh_dossier(), regime="mystery-law")

    def test_remove(self):
        d = _fresh_dossier()
        d2 = remove_compliance(d, regime="gdpr")
        assert "gdpr" not in d2["complianceNotes"]

    def test_remove_idempotent(self):
        d = _fresh_dossier()
        d2 = remove_compliance(d, regime="pci")
        assert "pci" not in d2["complianceNotes"]


# ------------------------------------------------------------------------- #
# entity suggestions                                                         #
# ------------------------------------------------------------------------- #

class TestEntitySuggestion:
    def test_add(self):
        d = _fresh_dossier()
        d2 = add_entity_suggestion(d, name="Interview",
                                   likely_fields=["date", "notes"])
        added = next(e for e in d2["entitySuggestions"] if e["name"] == "Interview")
        assert added["likelyFields"] == ["date", "notes"]

    def test_add_idempotent(self):
        d = _fresh_dossier()
        d2 = add_entity_suggestion(d, name="Applicant")
        assert sum(1 for e in d2["entitySuggestions"] if e["name"] == "Applicant") == 1

    def test_accepts_multi_word_name(self):
        d = _fresh_dossier()
        d2 = add_entity_suggestion(d, name="Hiring pipeline")
        assert any(e["name"] == "Hiring pipeline" for e in d2["entitySuggestions"])

    def test_rejects_bad_name(self):
        with pytest.raises(DossierAdjustError):
            add_entity_suggestion(_fresh_dossier(), name="123bad")

    def test_remove(self):
        d = _fresh_dossier()
        d2 = remove_entity_suggestion(d, name="Applicant")
        assert not any(e["name"] == "Applicant" for e in d2["entitySuggestions"])

    def test_remove_idempotent(self):
        d = _fresh_dossier()
        d2 = remove_entity_suggestion(d, name="Ghost")
        assert d == d2


# ------------------------------------------------------------------------- #
# design patterns                                                            #
# ------------------------------------------------------------------------- #

class TestDesignPattern:
    def test_add(self):
        d = _fresh_dossier()
        d2 = add_design_pattern(d, name="Split-pane detail",
                                description="List + preview side by side.")
        added = next(p for p in d2["designPatterns"] if p["name"] == "Split-pane detail")
        assert added["description"] == "List + preview side by side."

    def test_add_idempotent(self):
        d = _fresh_dossier()
        d2 = add_design_pattern(d, name="Candidate pipeline")
        assert sum(1 for p in d2["designPatterns"] if p["name"] == "Candidate pipeline") == 1

    def test_remove(self):
        d = _fresh_dossier()
        d2 = remove_design_pattern(d, name="Candidate pipeline")
        assert not any(p["name"] == "Candidate pipeline" for p in d2["designPatterns"])


# ------------------------------------------------------------------------- #
# pitfalls                                                                   #
# ------------------------------------------------------------------------- #

class TestPitfalls:
    def test_add(self):
        d = _fresh_dossier()
        d2 = add_pitfall(d, text="Missing GDPR consent flow")
        assert "Missing GDPR consent flow" in d2["commonPitfalls"]

    def test_add_idempotent(self):
        d = _fresh_dossier()
        d2 = add_pitfall(d, text="Undifferentiated status labels")
        assert d2["commonPitfalls"].count("Undifferentiated status labels") == 1

    def test_add_rejects_empty(self):
        with pytest.raises(DossierAdjustError):
            add_pitfall(_fresh_dossier(), text="   ")

    def test_remove(self):
        d = _fresh_dossier()
        d2 = remove_pitfall(d, text="Undifferentiated status labels")
        assert "Undifferentiated status labels" not in d2["commonPitfalls"]


# ------------------------------------------------------------------------- #
# visual language                                                            #
# ------------------------------------------------------------------------- #

class TestVisualLanguage:
    def test_updates_named_keys_only(self):
        d = _fresh_dossier()
        d2 = set_visual_language(d, palette_character="vibrant")
        assert d2["visualLanguage"]["paletteCharacter"] == "vibrant"
        # Untouched keys survive.
        assert d2["visualLanguage"]["typographyTone"] == "clean"

    def test_multiple_keys_at_once(self):
        d = _fresh_dossier()
        d2 = set_visual_language(
            d, typography_tone="playful", density_preference="airy",
        )
        vl = d2["visualLanguage"]
        assert vl["typographyTone"] == "playful"
        assert vl["densityPreference"] == "airy"

    def test_empty_string_clears_that_key(self):
        d = _fresh_dossier()
        d2 = set_visual_language(d, palette_character="")
        assert d2["visualLanguage"]["paletteCharacter"] == ""


# ------------------------------------------------------------------------- #
# compute_diff                                                               #
# ------------------------------------------------------------------------- #

class TestDiff:
    def test_empty_for_identical(self):
        d = _fresh_dossier()
        assert compute_diff(d, d).is_empty()

    def test_captures_compliance_add(self):
        d = _fresh_dossier()
        d2 = add_compliance(d, regime="hipaa")
        diff = compute_diff(d, d2)
        assert diff.compliance_added == ["hipaa"]

    def test_captures_entity_add(self):
        d = _fresh_dossier()
        d2 = add_entity_suggestion(d, name="Interview")
        diff = compute_diff(d, d2)
        assert diff.entities_added == ["Interview"]

    def test_captures_domain_change(self):
        d = _fresh_dossier()
        d2 = set_domain(d, text="Hospitality")
        diff = compute_diff(d, d2)
        assert diff.domain_changed is True

    def test_captures_visual_change(self):
        d = _fresh_dossier()
        d2 = set_visual_language(d, palette_character="vibrant")
        diff = compute_diff(d, d2)
        assert diff.visual_changed is True

    def test_dict_serialization(self):
        d = _fresh_dossier()
        d2 = add_design_pattern(d, name="Split-pane detail")
        payload = compute_diff(d, d2).to_dict()
        assert payload["patterns_added"] == ["Split-pane detail"]
        assert payload["domain_changed"] is False


# ------------------------------------------------------------------------- #
# validate_dossier_shape                                                     #
# ------------------------------------------------------------------------- #

class TestValidate:
    def test_clean_dossier(self):
        assert validate_dossier_shape(_fresh_dossier()) == []

    def test_flags_unknown_regime(self):
        d = _fresh_dossier()
        d["complianceNotes"].append("mystery-law")
        warnings = validate_dossier_shape(d)
        assert any("mystery-law" in w for w in warnings)


# ------------------------------------------------------------------------- #
# Reliability anchor: multi-turn conversation                                #
# ------------------------------------------------------------------------- #

class TestConversationalReliability:
    def test_five_turn_conversation_lands_cumulatively(self):
        d = _fresh_dossier()

        # Turn 1: change domain
        d = set_domain(d, text="Hospitality")
        # Turn 2: add compliance
        d = add_compliance(d, regime="pci")
        # Turn 3: add entity suggestion
        d = add_entity_suggestion(d, name="Reservation",
                                  likely_fields=["guest_name", "arrival_at"])
        # Turn 4: add pattern
        d = add_design_pattern(d, name="Calendar grid",
                               description="Rooms x days scheduler.")
        # Turn 5: drop the initial pitfall
        d = remove_pitfall(d, text="Undifferentiated status labels")

        assert d["domain"] == "Hospitality"
        assert "pci" in d["complianceNotes"]
        assert any(e["name"] == "Reservation" for e in d["entitySuggestions"])
        assert any(p["name"] == "Calendar grid" for p in d["designPatterns"])
        assert "Undifferentiated status labels" not in d["commonPitfalls"]

        assert validate_dossier_shape(d) == []
