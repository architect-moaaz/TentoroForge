"""DEFECT-STATUS-VERB / B-07 / C-06 — deterministic lifecycle-verb, status,
functionless-guard and state-advance helpers on the live /smith/chat path."""
import copy
from routers.blueprint_generate import (
    _lifecycle_verb, _status_report, _is_functionless_brief, _advance_state_to_review,
    _requirement_query, _requirement_report,
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


# ── DEFECT-I-05: 'Trace REQ-001' answered from the Blueprint, not denied ──

def test_requirement_query_detects_a_traced_id():
    assert _requirement_query("Trace REQ-001.") == "REQ-001"
    assert _requirement_query("trace req 12") == "REQ-012"
    assert _requirement_query("is REQ-3 implemented?") == "REQ-003"
    assert _requirement_query("where is REQ-007 done") == "REQ-007"


def test_requirement_query_ignores_edits_and_non_ids():
    # An edit that names an id is the mover's, not a trace.
    assert _requirement_query("reword REQ-001 to be clearer") is None
    assert _requirement_query("remove REQ-2") is None
    # No id at all.
    assert _requirement_query("add a candidate page") is None
    assert _requirement_query("build a requisition tracker") is None  # 'req' w/o a number
    assert _requirement_query("") is None


def test_requirement_report_names_the_requirement_and_verdict():
    doc = {"requirements": [
        {"id": "REQ-001", "description": "Recruiters can add candidates."},
        {"id": "REQ-002", "description": "Scheduling emails the candidate."},
    ]}
    out = _requirement_report(doc, "REQ-001")
    assert "REQ-001" in out
    assert "Recruiters can add candidates." in out
    # A verdict line is present (PASSED/FAILED/UNKNOWN — value depends on trace).
    assert "Verdict:" in out or "trace" in out.lower() or "cites it" in out.lower()


def test_requirement_report_is_honest_about_a_missing_id():
    doc = {"requirements": [{"id": "REQ-001", "description": "x"}]}
    out = _requirement_report(doc, "REQ-999")
    assert "REQ-999" in out and "isn't a requirement" in out
    # …and never denies the whole scheme the way the model did.
    assert "no requirement IDs" not in out


def test_requirement_report_when_nothing_is_defined_yet():
    out = _requirement_report({"requirements": []}, "REQ-001")
    assert "no requirements defined" in out and "define" in out.lower()
