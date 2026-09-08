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


# ── DEFECT-F-07: honest refusal for an unsupported external integration ──

from routers.blueprint_generate import (
    _unsupported_integration, _unsupported_integration_reply,
)


def test_unsupported_integration_is_detected():
    assert _unsupported_integration("Integrate with Greenhouse.") == "Greenhouse"
    assert _unsupported_integration("connect to Salesforce") == "Salesforce"
    assert _unsupported_integration("please sync with our Stripe account") \
        == "our Stripe account"
    assert _unsupported_integration("pull from HubSpot nightly") == "HubSpot nightly"


def test_supported_design_sources_are_not_refused():
    # Figma / UX Pilot have their own connect flow — never the F-07 refusal.
    assert _unsupported_integration("integrate with Figma") is None
    assert _unsupported_integration("connect to UX Pilot") is None


def test_internal_wiring_is_not_mistaken_for_an_integration():
    # "connect X to the dashboard/page/list" is internal, not external.
    assert _unsupported_integration("connect the form to the dashboard") is None
    assert _unsupported_integration("connect to the candidates page") is None
    assert _unsupported_integration("sync to the roles table") is None


def test_non_integration_messages_are_ignored():
    assert _unsupported_integration("add a candidates page") is None
    assert _unsupported_integration("what does this app do?") is None
    assert _unsupported_integration("") is None


def test_integration_reply_names_the_system_and_offers_an_alternative():
    r = _unsupported_integration_reply("Greenhouse")
    assert "Greenhouse" in r
    assert "requirement" in r.lower()          # offers the real alternative
    assert "figma" in r.lower() and "pilot" in r.lower()  # names what IS supported


# ── DEFECT-C-03/B-09: a change at the definition gate redrafts the definition ──

from routers.blueprint_generate import _is_built, _definition_edit


def test_is_built_is_the_emitted_app_not_the_definition(tmp_path):
    # A defined-but-unbuilt project: Blueprint on disk, no emitted app.
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text("{}")
    assert _is_built(str(tmp_path)) is False
    # After a build, app_emitter has written the Next app's package.json.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text("{}")
    assert _is_built(str(tmp_path)) is True


def test_definition_edit_detects_a_gate_modification():
    assert _definition_edit("Add a Clients module with a client list page.") is True
    assert _definition_edit("Add an approval step.") is True
    assert _definition_edit("there should be a manager approval") is True
    assert _definition_edit("remove the interviews module") is True
    assert _definition_edit("please add a payments page") is True


def test_definition_edit_leaves_questions_to_be_answered():
    assert _definition_edit("what does this app do?") is False
    assert _definition_edit("why did you decide that?") is False
    assert _definition_edit("where is candidate stage change implemented?") is False
    assert _definition_edit("trace REQ-001") is False
    assert _definition_edit("") is False


def test_definition_edit_ignores_bare_lifecycle_commands():
    # 'build' leads the edit verbs but is a command — must not redraft.
    assert _definition_edit("build") is False
    assert _definition_edit("approve") is False
    assert _definition_edit("define") is False
    assert _definition_edit("status") is False
    # …but 'build a dashboard at /' is still an edit.
    assert _definition_edit("build a dashboard at /") is True


# ── DEFECT-B-03: 'why did you decide X' cites the Blueprint, not a deflection ──

from routers.blueprint_generate import _cite_from_blueprint


def _doc_with_decisions():
    return {
        "decisions": [
            {"id": "DEC-004", "source": "user",
             "decision": "Only recruiters can add candidates.",
             "reason": "The team asked that candidate creation be restricted to recruiters."},
            {"id": "DEC-009", "source": "user",
             "decision": "Scheduling sends an email to the candidate.",
             "reason": "Interview scheduling notifies the candidate by email."},
        ],
        "requirements": [
            {"id": "REQ-002",
             "description": "All routes require a recruiter session; no candidate self-registration exists."},
            {"id": "REQ-014",
             "description": "Interview scheduling emails the candidate the date, time and location."},
        ],
    }


def test_why_question_cites_the_matching_decision():
    out = _cite_from_blueprint(
        _doc_with_decisions(),
        "Why did you decide that only recruiters can add candidates?")
    assert out is not None
    assert "DEC-004" in out
    assert "recruiters" in out.lower()
    # It cites, it does not deflect.
    assert "which screen" not in out.lower()


def test_why_question_falls_back_to_a_requirement_when_no_decision_matches():
    doc = {"requirements": [
        {"id": "REQ-014",
         "description": "Interview scheduling emails the candidate the date and time."},
    ]}
    out = _cite_from_blueprint(doc, "why does scheduling send an email to the candidate?")
    assert out is not None and "REQ-014" in out


def test_non_why_and_weak_matches_fall_through_to_the_model():
    doc = _doc_with_decisions()
    # Not a why-question at all.
    assert _cite_from_blueprint(doc, "add a candidates page") is None
    # A why-question with nothing distinctive to match → None (model handles it).
    assert _cite_from_blueprint(doc, "why not?") is None
    # A why-question about something the Blueprint doesn't cover → None, not a
    # wrong guess.
    assert _cite_from_blueprint(doc, "why did you pick postgres for billing invoices?") is None


# ── DEFECT-B-03 (recording): discovery answers become source=user decisions ──

from routers.blueprint_generate import _discovery_answers, _record_discovery_answers


def test_discovery_answers_pairs_questions_with_answers():
    turns = [
        ("user", "Build a recruitment tracker."),          # the brief, not an answer
        ("smith", "Which language should the interface be in?"),
        ("user", "English."),
        ("smith", "Who can add candidates?"),
        ("user", "Only recruiters."),
    ]
    pairs = _discovery_answers(turns)
    assert pairs == [
        ("Which language should the interface be in?", "English."),
        ("Who can add candidates?", "Only recruiters."),
    ]
    # The opening brief is never treated as an answer.
    assert all("Build a recruitment tracker" not in a for _q, a in pairs)


def test_record_discovery_answers_writes_source_user_decisions(tmp_path):
    import json
    from pathlib import Path
    from services.blueprint.service import BlueprintService
    from services.smith import decisions as dmod

    doc = json.loads((Path("fleet/blueprints/ats-live.json")).read_text())
    s = BlueprintService(output_dir=tmp_path)
    s.doc = doc
    s.root.mkdir(parents=True, exist_ok=True)
    s.save()

    before = len(dmod.by_user(s.doc))
    turns = [
        ("user", "Build a recruitment tracker."),
        ("smith", "Who can add candidates?"),
        ("user", "Only recruiters can add candidates."),
        ("smith", "Does scheduling send email?"),
        ("user", "Yes, scheduling emails the candidate."),
    ]
    n = _record_discovery_answers(str(tmp_path), turns)
    assert n == 2

    reloaded = BlueprintService.load(output_dir=str(tmp_path))
    after = dmod.by_user(reloaded.doc)
    assert len(after) == before + 2
    texts = " ".join(d.get("decision", "") for d in after)
    assert "Only recruiters" in texts and "scheduling emails" in texts
    assert reloaded.is_valid()

    # Idempotent: recording the same answers again adds nothing.
    _record_discovery_answers(str(tmp_path), turns)
    reloaded2 = BlueprintService.load(output_dir=str(tmp_path))
    assert len(dmod.by_user(reloaded2.doc)) == before + 2


def test_record_discovery_answers_is_safe_with_no_blueprint(tmp_path):
    # No current.json yet → nothing recorded, no raise.
    assert _record_discovery_answers(str(tmp_path), [("user", "x")]) == 0
