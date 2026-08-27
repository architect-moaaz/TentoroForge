"""Tests for the healthcare-platform archetype vocabulary."""
from __future__ import annotations

import pytest

from services.archetype_vocabulary import (
    KNOWN_SHAPES,
    clear_cache,
    known_archetypes,
    load_vocabulary,
    component_preference,
)


_VALID_VARIANTS = {"success", "warning", "danger", "neutral", "accent"}


def _vocab():
    clear_cache()
    v = load_vocabulary("healthcare-platform")
    assert v is not None
    return v


class TestHealthcareRegistered:
    def test_vocab_registered(self):
        clear_cache()
        assert "healthcare-platform" in known_archetypes()

    def test_load_normalises_input(self):
        for raw in ("Healthcare Platform", "healthcare_platform"):
            clear_cache()
            v = load_vocabulary(raw)
            assert v is not None and v.id == "healthcare-platform"


class TestHealthcarePersonas:
    def test_patient_role_present(self):
        v = _vocab()
        assert "patient" in v.primary_screens_per_persona

    def test_doctor_aliases_present(self):
        v = _vocab()
        for alias in ("doctor", "physician"):
            assert alias in v.primary_screens_per_persona

    def test_nurse_role_present(self):
        v = _vocab()
        assert "nurse" in v.primary_screens_per_persona

    def test_admin_role_present(self):
        v = _vocab()
        assert "admin" in v.primary_screens_per_persona

    def test_doctor_gets_schedule_and_patients(self):
        v = _vocab()
        screens = v.primary_screens_per_persona["doctor"]
        assert "schedule" in screens
        assert "patient-list" in screens


class TestHealthcareSectionRecipes:
    def test_patient_list_splits(self):
        v = _vocab()
        assert v.section_recipes["patient-list"] == ["active", "discharged", "flagged"]

    def test_prescriptions_lifecycle(self):
        v = _vocab()
        assert v.section_recipes["prescriptions"] == ["active", "expired", "cancelled"]


@pytest.mark.parametrize("entity", [
    "patients", "appointments", "encounters", "prescriptions", "vitals",
    "providers", "messages",
])
class TestHealthcareComponentShapes:
    def test_shape_in_known_set(self, entity):
        v = _vocab()
        pref = v.component_preferences.get(entity)
        assert pref is not None and pref.shape in KNOWN_SHAPES


class TestHealthcareComponentSemantics:
    def test_appointments_is_schedule_grid(self):
        v = _vocab()
        assert v.component_preferences["appointments"].shape == "schedule-grid"

    def test_prescriptions_is_table(self):
        v = _vocab()
        assert v.component_preferences["prescriptions"].shape == "table"

    def test_vitals_is_ledger_list(self):
        v = _vocab()
        assert v.component_preferences["vitals"].shape == "ledger-list"

    def test_patients_is_clinician_scoped(self):
        v = _vocab()
        pref = v.component_preferences["patients"]
        assert pref.context.lower() == "clinician"
        # Context-scoped preference must NOT leak into unrelated personas.
        assert component_preference(v, "patients", "patient") is None
        # And should surface for the clinician role.
        assert component_preference(v, "patients", "clinician") is pref


class TestHealthcareSignatureStates:
    def test_empty_states_populated(self):
        v = _vocab()
        for section in ("active", "discharged", "flagged", "expired", "cancelled"):
            key = f"empty_{section}"
            assert v.signature_states.get(key), f"missing {key}"

    def test_no_results_present(self):
        v = _vocab()
        assert v.signature_states.get("no_results")


class TestHealthcareSectionFilters:
    def test_all_recipe_values_covered(self):
        v = _vocab()
        union: set[str] = set()
        for parts in v.section_recipes.values():
            union.update(parts)
        for name in union:
            assert name in v.section_filters, f"section {name!r} has no filter"


class TestHealthcareStatusBadges:
    def test_all_variants_valid(self):
        v = _vocab()
        for status, meta in v.status_badges.items():
            assert meta["variant"] in _VALID_VARIANTS, status

    def test_flagged_is_danger(self):
        v = _vocab()
        assert v.status_badges["flagged"]["variant"] == "danger"

    def test_active_is_success(self):
        v = _vocab()
        assert v.status_badges["active"]["variant"] == "success"
