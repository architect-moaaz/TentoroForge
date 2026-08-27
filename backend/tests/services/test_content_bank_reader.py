"""Tests for services.content_bank_reader — Spec C3.

Reader + template substitutor for the brief's authored content bank.
Every emitter (empty states, toasts, notifications, CTA labels) calls
through the same surface so voice stays consistent across the app.
"""
from __future__ import annotations

import pytest

from schemas.design_brief import ContentBank
from services.content_bank_reader import (
    cta_verb,
    empty_state,
    fingerprint,
    get_string,
    notification,
    substitute,
    toast,
)


def _sample_bank() -> ContentBank:
    return ContentBank(
        empty_states={
            "list": "No {entity_plural} on file yet",
            "search": "No {entity_plural} match \"{query}\"",
        },
        toasts={
            "created": "{entity_singular} recorded",
            "error_generic": "Couldn't save — try again",
        },
        notifications={
            "task_assigned": "You've been assigned a {task_kind}",
        },
        cta_verbs={"primary": "Record", "create": "Add", "delete": "Remove"},
    )


# ────────────────────────────────────────────────────────────
# substitute()
# ────────────────────────────────────────────────────────────

class TestSubstitute:
    def test_replaces_known_tokens(self):
        assert substitute("Hello {name}", {"name": "World"}) == "Hello World"

    def test_leaves_unknown_tokens_intact(self):
        """A mis-spelled key surfaces literally, not silently drops."""
        assert substitute("Value is {typo}", {"name": "X"}) == "Value is {typo}"

    def test_empty_template_returned_as_is(self):
        assert substitute("", {"a": "b"}) == ""

    def test_no_subs_returns_template_verbatim(self):
        assert substitute("Hi {name}", None) == "Hi {name}"


# ────────────────────────────────────────────────────────────
# get_string() — fallback behavior
# ────────────────────────────────────────────────────────────

class TestGetString:
    def test_returns_bank_value_when_present(self):
        assert get_string(_sample_bank(), "empty_states", "list",
                          "generic fallback",
                          {"entity_plural": "invoices"}) == "No invoices on file yet"

    def test_falls_back_when_bank_silent(self):
        assert get_string(_sample_bank(), "empty_states", "missing_kind",
                          "Generic fallback text") == "Generic fallback text"

    def test_falls_back_when_bank_is_none(self):
        assert get_string(None, "empty_states", "list", "fallback") == "fallback"

    def test_falls_back_when_section_missing(self):
        empty = ContentBank()
        assert get_string(empty, "empty_states", "list", "fallback") == "fallback"

    def test_fallback_also_gets_substituted(self):
        """A fallback template may itself contain {tokens} — sub them."""
        assert get_string(None, "empty_states", "list",
                          "No {entity_plural} yet",
                          {"entity_plural": "leases"}) == "No leases yet"


# ────────────────────────────────────────────────────────────
# Section-specific readers
# ────────────────────────────────────────────────────────────

class TestSections:
    def test_empty_state_reader(self):
        bank = _sample_bank()
        assert empty_state(bank, "list", "generic", entity_plural="invoices") == \
            "No invoices on file yet"
        assert empty_state(bank, "search", "generic",
                           entity_plural="invoices", query="Q1") == \
            'No invoices match "Q1"'

    def test_toast_reader(self):
        assert toast(_sample_bank(), "created", "Saved",
                     entity_singular="Payment") == "Payment recorded"

    def test_toast_falls_back(self):
        assert toast(_sample_bank(), "updated", "Saved",
                     entity_singular="Payment") == "Saved"

    def test_notification_reader(self):
        assert notification(_sample_bank(), "task_assigned",
                            "You have a new task",
                            task_kind="approval") == "You've been assigned a approval"

    def test_cta_verb_reader(self):
        assert cta_verb(_sample_bank(), "primary", "Save") == "Record"
        assert cta_verb(_sample_bank(), "unknown_kind", "Fallback") == "Fallback"


# ────────────────────────────────────────────────────────────
# Bank as plain dict — the JSON-loaded path
# ────────────────────────────────────────────────────────────

class TestAcceptsDictShape:
    def test_reader_works_on_plain_dict(self):
        bank = {
            "empty_states": {"list": "None yet"},
            "toasts": {"created": "OK"},
        }
        assert empty_state(bank, "list", "fallback") == "None yet"
        assert toast(bank, "created", "fallback") == "OK"


# ────────────────────────────────────────────────────────────
# Fingerprint — for cross-app variation check
# ────────────────────────────────────────────────────────────

class TestFingerprint:
    def test_same_bank_same_fp(self):
        assert fingerprint(_sample_bank()) == fingerprint(_sample_bank())

    def test_different_banks_different_fp(self):
        bank_a = ContentBank(toasts={"created": "Saved"})
        bank_b = ContentBank(toasts={"created": "Recorded"})
        assert fingerprint(bank_a) != fingerprint(bank_b)

    def test_none_bank_returns_empty_fp(self):
        assert fingerprint(None) == ""

    def test_empty_bank_returns_empty_fp(self):
        assert fingerprint(ContentBank()) == ""
