"""DEFECT-STATUS-VERB / B-07 / C-06 — deterministic lifecycle-verb, status,
functionless-guard and state-advance helpers on the live /smith/chat path."""
import copy
from routers.blueprint_generate import (
    _lifecycle_verb, _status_report, _is_functionless_brief, _advance_state_to_review,
)


def test_lifecycle_verb_only_matches_a_bare_command():
    assert _lifecycle_verb("status") == "status"
    assert _lifecycle_verb("  STATUS. ") == "status"
    assert _lifecycle_verb("define") == "define"
    assert _lifecycle_verb("define the roles for me") is None  # a sentence, not the verb
    assert _lifecycle_verb("what is the status of my app") is None
    assert _lifecycle_verb("") is None


def test_status_report_never_defines_and_reads_state():
    assert "DISCOVERY" in _status_report({})
    assert "define" in _status_report({}).lower()
    doc = {"state": "BLUEPRINT_REVIEW", "requirements": [{"id": "REQ-001"}],
           "pages": [{"id": "PAGE-001"}], "decisions": [{"id": "DEC-001", "source": "user"}]}
    r = _status_report(doc)
    assert "BLUEPRINT_REVIEW" in r and "1 requirement" in r and "approve" in r.lower()


def test_functionless_brief_guard_is_conservative():
    assert _is_functionless_brief("A single page that just says Welcome.") is True
    assert _is_functionless_brief("A page that just shows Hello") is True
    # real apps are never refused
    assert _is_functionless_brief(
        "A recruitment tracker where recruiters create roles and manage candidates") is False
    assert _is_functionless_brief(
        "A leave-request app where staff submit requests and managers approve them") is False
    # a marketing page that says a tagline but also DOES something is not refused
    assert _is_functionless_brief("A landing page that says Welcome and lets users sign in") is False


class _FakeSvc:
    def __init__(self, doc):
        self.doc = doc
        self.saved = 0
    def save(self):
        self.saved += 1


def test_advance_state_walks_discovery_to_review():
    svc = _FakeSvc({"state": "DISCOVERY", "requirements": [{"id": "REQ-001"}]})
    _advance_state_to_review(svc)
    assert svc.doc["state"] == "BLUEPRINT_REVIEW"
    # idempotent-ish: from BLUEPRINT_REVIEW it stays put (no illegal jump)
    _advance_state_to_review(svc)
    assert svc.doc["state"] == "BLUEPRINT_REVIEW"
