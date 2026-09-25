"""Before there is an application: the clarifier as a read, the definition as a write.

The router used to run this phase as its own state machine — clarify one
question a turn, refuse a functionless brief, define. Those are a turn's moves
now, with the same structural rules: silence is the default, a cap stops the
clarifier, a page with nothing to do is refused with the reason, and the
definition runs the DAG's own domain nodes and stops at review.
"""
from __future__ import annotations

from services.smith import tools
from services.smith4 import definition
from services.smith4.context import opening
from services.smith4.verbs import Ctx
from tests.services._loop_fixtures import _Chooser, _repo


def _ctx(tmp_path, message="", history=(), evidence=()):
    return Ctx(output_dir=str(tmp_path), project_id="p1", message=message, ask=message,
               history=list(history), evidence=list(evidence), app_name="Roster")


# --------------------------------------------------------------------------- #
# The page and the catalogue
# --------------------------------------------------------------------------- #

def test_an_undefined_project_opens_on_the_brief_not_a_slice(tmp_path):
    _repo(tmp_path)
    page = opening("p1", str(tmp_path), "build me a roster", brief="build me a roster\n\nfor nurses")
    assert "THERE IS NO APPLICATION YET" in page and "for nurses" in page
    assert "`open_decisions`" in page and "`define_application`" in page


def test_the_definition_moves_are_tools_apart_from_the_verbs():
    assert tools.is_definition("open_decisions") and tools.is_definition("define_application")
    assert tools.is_tool("define_application") and not tools.is_write("define_application")
    assert "Before there is an application" in tools.render()


# --------------------------------------------------------------------------- #
# open_decisions — the clarifier as a read
# --------------------------------------------------------------------------- #

def test_open_decisions_reads_the_whole_exchange_as_the_brief(tmp_path, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr("services.smith.clarify_brief.clarify_brief",
                        lambda brief, **k: seen.update(brief=brief, **k) or
                        [{"question": "Which language?", "options": ["English", "Arabic"]}])
    ctx = _ctx(tmp_path, "and it should send reminders",
               history=[("user", "a noticeboard for the centre"), ("smith", "Which colour?"), ("user", "olive")])
    said = definition.open_decisions(ctx, {})
    assert "a noticeboard for the centre" in seen["brief"] and "olive" in seen["brief"]
    assert "Which colour?" not in seen["brief"]                 # Smith's questions are not the brief
    assert "Which language?" in said and "English; Arabic" in said


def test_silence_when_the_brief_stands_on_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr("services.smith.clarify_brief.clarify_brief", lambda brief, **k: [])
    said = definition.open_decisions(_ctx(tmp_path, "a roster for nurses with shifts and swaps"), {})
    assert "stands on its own" in said and "Define it" in said


def test_the_clarifier_is_capped_by_the_persons_turns(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("services.smith.clarify_brief.clarify_brief", lambda brief, **k: calls.append(1) or [{"question": "more?", "options": []}])
    history = [("user", f"answer {i}") for i in range(definition.MAX_CLARIFY_TURNS)]
    said = definition.open_decisions(_ctx(tmp_path, "one more", history=history), {})
    assert "Define with what is known" in said and calls == []


def test_nothing_asked_is_nothing_to_clarify(tmp_path):
    assert "no brief" in definition.open_decisions(_ctx(tmp_path, ""), {})


# --------------------------------------------------------------------------- #
# define_application — the definition as a write
# --------------------------------------------------------------------------- #

def test_a_page_with_nothing_to_do_is_refused_with_the_question_to_ask(tmp_path, monkeypatch):
    monkeypatch.setattr("services.smith.brief.is_functionless", lambda brief: True)
    out = definition.define_application(_ctx(tmp_path, "a page that just says welcome"), {})
    assert not out["applied"] and "nothing to do" in out["finding"] and "DO" in out["finding"]


def test_defining_runs_the_domain_nodes_and_stops_at_review(tmp_path, monkeypatch):
    ran: dict = {}

    class _Svc:
        def __init__(self): self.doc = {"application": {}, "requirements": [], "pages": [], "version": 1}
        def validate(self): pass
        def save(self): pass

    svc = _Svc()
    monkeypatch.setattr("services.blueprint.service.BlueprintService.create",
                        classmethod(lambda cls, **k: ran.update(create=k) or svc))
    monkeypatch.setattr("services.blueprint.orchestrator.completed_nodes", lambda doc, confirmed=None: set())
    monkeypatch.setattr("services.blueprint.orchestrator.nodes_recorded_done", lambda out: None)
    monkeypatch.setattr("services.blueprint.executors.RunUsage.for_app", classmethod(lambda cls, s: None))
    monkeypatch.setattr("services.blueprint.executors.tiered_router", lambda **k: object())
    monkeypatch.setattr("services.blueprint.executors.make_executor", lambda *a, **k: object())
    monkeypatch.setattr("services.blueprint.observer.anthropic_observer", lambda *a, **k: None)
    monkeypatch.setattr("services.smith.smith.domain_nodes", lambda: ["requirements", "data_model"])

    def run(s, executor, *, plan, commit, user_request, app_root, observer_agent):
        ran.update(plan=plan, request=user_request)
        s.doc["requirements"] = [{"id": "REQ-001"}]
        s.doc["product"] = {"capabilities": [{"name": "Shift Publishing"}, {"name": "Swap Requests"}]}
        return type("R", (), {"failed": []})()
    monkeypatch.setattr("services.blueprint.orchestrator.run", run)
    monkeypatch.setattr("services.smith.brief.advance_to_review", lambda s: ran.update(review=True))

    out = definition.define_application(_ctx(tmp_path, "a roster for nurses"), {})

    assert out["applied"] and not out["finding"]
    assert ran["create"]["name"] == "Roster" and ran["create"]["description"] == "a roster for nurses"
    assert ran["plan"] == ["requirements", "data_model"] and ran["review"] is True
    assert "1 requirement(s) and 2 capabilities — Shift Publishing, Swap Requests" in out["said"]
    assert "ready to review" in out["said"] and "nothing is built until then" in out["said"]


def test_a_definition_that_did_not_complete_is_a_finding_on_what_stands(tmp_path, monkeypatch):
    svc = type("S", (), {"doc": {"application": {}, "requirements": [{"id": "R"}], "pages": [], "version": 1},
                         "validate": lambda self: None, "save": lambda self: None})()
    monkeypatch.setattr("services.blueprint.service.BlueprintService.create", classmethod(lambda cls, **k: svc))
    monkeypatch.setattr("services.blueprint.orchestrator.completed_nodes", lambda doc, confirmed=None: set())
    monkeypatch.setattr("services.blueprint.orchestrator.nodes_recorded_done", lambda out: None)
    monkeypatch.setattr("services.blueprint.executors.RunUsage.for_app", classmethod(lambda cls, s: None))
    monkeypatch.setattr("services.blueprint.executors.tiered_router", lambda **k: object())
    monkeypatch.setattr("services.blueprint.executors.make_executor", lambda *a, **k: object())
    monkeypatch.setattr("services.blueprint.observer.anthropic_observer", lambda *a, **k: None)
    monkeypatch.setattr("services.smith.smith.domain_nodes", lambda: ["requirements", "data_model"])
    monkeypatch.setattr("services.blueprint.orchestrator.run", lambda *a, **k: type("R", (), {"failed": ["data_model"]})())
    monkeypatch.setattr("services.smith.brief.advance_to_review", lambda s: None)
    out = definition.define_application(_ctx(tmp_path, "a roster"), {})
    assert out["applied"] and "data_model" in out["finding"]


# --------------------------------------------------------------------------- #
# Through the loop
# --------------------------------------------------------------------------- #

def test_the_loop_reads_the_open_decisions_then_asks_one(tmp_path, monkeypatch):
    from services.smith4 import handle
    _repo(tmp_path)
    monkeypatch.setattr("services.smith.clarify_brief.clarify_brief",
                        lambda brief, **k: [{"question": "Which language?", "options": ["English", "Arabic"]}])
    chooser = _Chooser({"tool": "open_decisions", "args": {}, "why": ""},
                       {"tool": "ask_user", "args": {"question": "Which language?", "options": ["English", "Arabic"]}, "why": ""})
    out = handle(project_id="p1", output_dir=str(tmp_path), message="a noticeboard", choose=chooser,
                 move=lambda u, o: None)
    assert chooser.seen[1][-1].status == "read" and "Which language?" in chooser.seen[1][-1].said
    assert out.status == "asked" and out.options == ["English", "Arabic"]
