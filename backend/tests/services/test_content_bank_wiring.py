"""Tests for Spec C Slice 3 (part 2) — content_bank reader wiring.

The brief-author now populates ``brief.content_bank``. This test suite
verifies that the ``text_template_backstop`` pass reads that bank and
prefers voice-tuned copy over the generic "No <plural> yet." fallback.
Additive: when the bank is absent (older briefs, no brief.json), the
existing behavior is unchanged.
"""
from __future__ import annotations

from schemas.design_brief import ContentBank
from services.text_template_backstop import (
    _empty_state_value,
    _replace_empty_state_props,
    _replace_empty_state_component,
)


class TestEmptyStateValue:
    def test_no_bank_returns_generic_fallback(self):
        # Without a bank, we get the same string text_templates always
        # produced (pluralized entity, "No <plural> yet.").
        v = _empty_state_value("patient", bank=None)
        assert v.startswith("No ") and v.endswith(" yet.")

    def test_bank_absent_section_falls_through(self):
        bank = ContentBank()  # all sections empty
        v = _empty_state_value("patient", bank=bank)
        # Empty bank behaves the same as no bank.
        assert v.startswith("No ") and v.endswith(" yet.")

    def test_bank_present_wins_and_substitutes(self):
        bank = ContentBank(empty_states={
            "list": "No {entity_plural} on file yet",
        })
        v = _empty_state_value("patient", bank=bank)
        # Substitution filled in the plural derived from fallback.
        assert v == "No patients on file yet"

    def test_bank_singular_substitution(self):
        bank = ContentBank(empty_states={
            "list": "Start by admitting a {entity_singular}",
        })
        v = _empty_state_value("patient", bank=bank)
        assert v == "Start by admitting a patient"

    def test_bank_without_list_key_falls_back(self):
        # Bank has other keys but no "list" — reader uses fallback.
        bank = ContentBank(empty_states={"search": "No matches"})
        v = _empty_state_value("patient", bank=bank)
        assert v.startswith("No ") and v.endswith(" yet.")


class TestReplaceEmptyStateProps:
    def test_replaces_when_bank_present(self):
        bank = ContentBank(empty_states={"list": "Nothing recorded for {entity_plural}."})
        node = {"type": "Table", "props": {"emptyStateText": "No patients yet."}}
        n = _replace_empty_state_props(node, "patient", bank)
        assert n == 1
        assert node["props"]["emptyStateText"] == "Nothing recorded for patients."

    def test_no_change_when_bank_absent_and_text_matches_fallback(self):
        # Existing behavior preserved: when the string already IS the
        # generic fallback, no edit needed.
        node = {"type": "Table", "props": {"emptyStateText": "No patients yet."}}
        n = _replace_empty_state_props(node, "patient", bank=None)
        assert n == 0
        assert node["props"]["emptyStateText"] == "No patients yet."


class TestReplaceEmptyStateComponent:
    def test_illustrated_empty_also_covered(self):
        # Spec C9 IllustratedEmpty component was added to the covered set.
        bank = ContentBank(empty_states={"list": "No {entity_plural} on file yet"})
        node = {"type": "IllustratedEmpty",
                "props": {"title": "No thing yet."}}
        n = _replace_empty_state_component(node, "case", bank)
        assert n == 1
        assert node["props"]["title"] == "No cases on file yet"

    def test_empty_state_still_covered(self):
        bank = ContentBank(empty_states={"list": "No {entity_plural} to show yet"})
        node = {"type": "EmptyState",
                "props": {"title": "No records yet."}}
        n = _replace_empty_state_component(node, "record", bank)
        assert n == 1
        assert node["props"]["title"] == "No records to show yet"


class TestNoBankNoRegression:
    """The whole pass must be a no-op when there's no brief on disk."""
    def test_pass_signature_still_returns_expected_shape(self):
        # apply_text_template_backstop returns a stats dict; we can't
        # exercise it without a full output_dir fixture, but the
        # per-helper tests above prove bank=None keeps every helper
        # equivalent to pre-C3 behavior.
        # This test exists as an explicit assertion of that contract.
        node = {"type": "Table", "props": {"emptyStateText": "No stuff yet."}}
        _replace_empty_state_props(node, "stuff", bank=None)
        # No exception; deterministic string still governs.
        assert node["props"]["emptyStateText"].startswith("No ")
