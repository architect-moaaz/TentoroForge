"""Pin the rule_type taxonomy so the Business Rules editor can't silently break.

The editor saves `condition_action` and `decision_table` rules through the
generic /rules create endpoint. If those types are ever dropped from the
accept-list, every save from the editor 400s with no obvious cause. There was
no test guarding this — this is it.
"""
from routers.rules import VALID_RULE_TYPES


def test_editor_rule_types_are_accepted():
    # The two Power-Apps-style editor types MUST be accepted by create_rule.
    assert "condition_action" in VALID_RULE_TYPES
    assert "decision_table" in VALID_RULE_TYPES


def test_legacy_and_ai_types_still_accepted():
    for t in ("validation", "access", "business", "computed", "state_machine",
              "trigger", "content_moderation", "similarity_check",
              "ai_validation", "ai_enrichment"):
        assert t in VALID_RULE_TYPES


def test_taxonomy_has_no_unexpected_drift():
    # Exact set — a change here is a deliberate taxonomy decision, not an accident.
    assert VALID_RULE_TYPES == {
        "validation", "access", "business", "computed", "state_machine", "trigger",
        "content_moderation", "similarity_check", "ai_validation", "ai_enrichment",
        "condition_action", "decision_table",
    }
