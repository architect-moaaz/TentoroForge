"""The statements are tried where the application changes (2026-10-08).

At the end of a build every statement of what must happen is tried; one that
does not hold goes to Smith with what was seen, and is tried again. After a
change in chat, the statements it reaches are tried. Smith can try one
(`try_expectation`), record a new one (`add_expectation`), and cannot edit
one to agree with the app. No browser here: the runner is replaced by what it
would report.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from services.expects import build

DOC = {
    "version": 3,
    "roles": [{"id": "ROLE-001", "name": "Patient"}, {"id": "ROLE-002", "name": "Admin"}],
    "data": {"entities": [{"id": "ENTITY-001", "name": "Slot", "table": "slots", "labelField": "label",
                           "fields": [{"name": "label", "type": "string"}]}]},
    "pages": [{"id": "PAGE-001", "name": "Slots", "route": "/slots", "access": "public"},
              {"id": "PAGE-002", "name": "Admin", "route": "/admin", "users": ["ROLE-002"]}],
    "expectations": [
        {"id": "EXP-001", "kind": "action", "says": "A patient books a slot and sees it.",
         "steps": [{"as": "ROLE-001", "act": "open", "page": "PAGE-001"},
                   {"as": "ROLE-001", "act": "do", "what": "book the first slot"}],
         "then": [{"check": "told", "told": "success"}]},
        {"id": "EXP-002", "kind": "arrival", "says": "The admin lands on the admin screen.",
         "steps": [{"as": "ROLE-002", "act": "sign_in"}], "then": [{"check": "on", "page": "PAGE-002"}]},
    ],
}


class _Svc:
    def __init__(self, doc: dict):
        self.doc = copy.deepcopy(doc)
        self.saved = 0

    def save(self) -> None:
        self.saved += 1


class _App:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None


def _result(sid: str, verdict: str, failure: str = "") -> dict:
    return {"id": sid, "says": next(e["says"] for e in DOC["expectations"] if e["id"] == sid), "verdict": verdict,
            "failures": [failure] if failure else [], "untried": [], "also": [], "log": ["x opened /slots"]}


def _refused(sid: str) -> dict:
    return {**_result(sid, "failed", "Patient was told refusal, not success"), "where": "PAGE-001",
            "sent": [{"method": "POST", "path": "/api/workflows/FLOW-001/execute", "status": 422, "body": "{}"}]}


def test_a_statement_that_does_not_hold_goes_back_once_to_whoever_wrote_that_part(tmp_path):
    svc = _Svc(DOC)
    rounds = [{"results": [_refused("EXP-001"), _result("EXP-002", "passed")]},
              {"results": [_result("EXP-001", "passed")]}]
    tried: list[list[str]] = []
    authored: list[tuple[str, str, str]] = []

    def trial(_app, _doc, _project, only=None):
        tried.append(list(only))
        return rounds.pop(0)
    out = build._prove(svc, str(tmp_path), app_factory=lambda _r: _App(), trial=trial,
                       author=lambda _s, _o, node, subject, brief: authored.append((node, subject, brief)) or ["x"])
    assert tried == [["EXP-001", "EXP-002"], ["EXP-001"]], "everything once, then what was sent back, once"
    assert [(n, s) for n, s, _b in authored] == [("workflow_steps", "FLOW-001")], \
        "a process that refused is its author's — not a repair turn"
    assert "A patient books a slot and sees it." in authored[0][2] and "do not change what they say" in authored[0][2]
    assert out["fixed"] == ["EXP-001"] and out["failing"] == [] and out["touched"] == ["x"]
    assert svc.doc["runtime"]["expectations"]["fixed"] == ["EXP-001"]


@pytest.mark.parametrize("res,owner", [
    (_refused("EXP-001"), ("workflow_steps", "FLOW-001")),
    ({"failures": ["no Visit with slotId='@ten' is stored"], "where": "PAGE-001",
      "sent": [{"method": "POST", "path": "/api/workflows/FLOW-002/execute", "status": 200}]}, ("workflow_steps", "FLOW-002")),
    ({"failures": ["Patient was told nothing, not success: nothing was sent"], "where": "PAGE-001", "sent": []},
     ("page_code", "PAGE-001")),
    ({"failures": ["Admin is on /, not /admin"], "where": "", "sent": []}, None),
])
def test_whose_part_a_failure_is_comes_from_what_was_sent(res, owner):
    assert build.owner_of(res) == owner


def test_one_failure_across_the_app_is_the_platforms_and_nobody_repairs_it(tmp_path):
    doc = copy.deepcopy(DOC)
    doc["expectations"] += [{**copy.deepcopy(doc["expectations"][0]), "id": f"EXP-00{i}", "says": f"Another {i}."}
                            for i in (3, 4)]
    svc = _Svc(doc)
    same = "Patient was told refusal, not success: POST /api/workflows/FLOW-001/execute 422 your account is disabled"
    authored: list = []

    def trial(_app, _doc, _project, only=None):
        return {"results": [{"id": s, "says": s, "verdict": "failed", "failures": [same], "where": "PAGE-001",
                             "sent": [{"method": "POST", "path": "/api/workflows/FLOW-001/execute", "status": 422}]}
                            if s != "EXP-002" else _result(s, "passed") for s in only]}
    out = build._prove(svc, str(tmp_path), app_factory=lambda _r: _App(), trial=trial,
                       author=lambda *a: authored.append(a) or [])
    assert authored == [], "three statements failing the same way are not three app faults"
    assert out["platform"] and sorted(out["platform"][0]["statements"]) == ["EXP-001", "EXP-003", "EXP-004"]
    kinds = [i["kind"] for i in svc.doc["runtime"]["issues"]]
    assert "platform" in kinds and "expectation" not in kinds


def test_what_still_fails_is_recorded_and_said_when_the_build_is_done(tmp_path):
    svc = _Svc(DOC)

    def trial(_app, _doc, _project, only=None):
        return {"results": [_result(s, "failed", "Admin is on /, not /admin") if s == "EXP-002"
                            else _result(s, "passed") for s in only]}
    build._prove(svc, str(tmp_path), app_factory=lambda _r: _App(), trial=trial, author=lambda *a: [])
    runtime = svc.doc["runtime"]
    assert runtime["expectations"]["failing"] == ["EXP-002"] and runtime["expectations"]["passed"] == 1
    issue = next(i for i in runtime["issues"] if i["kind"] == "expectation")
    assert issue["statement"] == "EXP-002" and "Admin is on /" in issue["detail"]
    from routers.blueprint_generate import _check_score
    said = _check_score(svc.doc)
    assert "1 of 2 statements of what must happen held" in said, "said with no page check at all"
    assert "Not doing what it must yet" in said and "The admin lands on the admin screen." in said


def test_a_change_tries_only_the_statements_it_reaches(tmp_path, monkeypatch):
    monkeypatch.setattr("services.blueprint.app_check.affected_pages", lambda doc, touched: {"PAGE-002"})
    assert build.reached(copy.deepcopy(DOC), ["src/app/admin/view.tsx"]) == ["EXP-002"]
    monkeypatch.setattr("services.blueprint.app_check.affected_pages", lambda doc, touched: set())
    assert build.reached(copy.deepcopy(DOC), ["README.md"]) == []


def test_smith_reads_each_statement_with_how_it_last_went_failing_first(tmp_path):
    (tmp_path / ".forge" / "expects").mkdir(parents=True)
    (tmp_path / ".forge" / "expects" / "results.json").write_text(json.dumps({"results": [
        _result("EXP-001", "passed"), _result("EXP-002", "failed", "Admin is on /, not /admin")]}))
    got = build.lines(copy.deepcopy(DOC), str(tmp_path))
    assert got[0].startswith("EXP-002 [does not hold] The admin lands") and "Admin is on /" in got[0]
    assert got[1].startswith("EXP-001 [holds]")


def test_a_statement_tried_by_smith_is_a_trial_that_fails_or_holds():
    from services.smith import trials
    from services.smith4.turn import _failed_alike
    assert "try_expectation" in trials.TRIAL_NAMES
    held = build.observation(_result("EXP-001", "passed"))
    broke = build.observation(_result("EXP-001", "failed", "Patient was told refusal, not success"))
    other = build.observation(_result("EXP-001", "failed", "Patient does not see 'Tuesday' on /visits"))
    assert not trials.failed(held) and trials.failed(broke)
    assert _failed_alike(broke, broke), "the same check failing again is still failing"
    assert not _failed_alike(broke, other), "a different check failing is what the change broke or uncovered"


def test_a_statement_that_is_not_there_is_named_as_not_there(tmp_path):
    from services.smith.trials import Bench, try_expectation
    said = try_expectation(Bench(str(tmp_path)), copy.deepcopy(DOC), "EXP-404")
    assert "no statement 'EXP-404'" in said and "EXP-001" in said


# --------------------------------------------------------------------------- #
# Smith records statements and never edits them
# --------------------------------------------------------------------------- #

@pytest.fixture
def shop(tmp_path):
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Clinic", domain="health")
    svc.doc["roles"] = [{"id": "ROLE-001", "name": "Patient"}, {"id": "ROLE-002", "name": "Admin"}]
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Slots", "route": "/slots", "purpose": "Book a slot",
                         "pattern": "entity_list", "access": "public"}]
    svc.save()
    return tmp_path


def test_a_reported_fault_is_recorded_as_a_statement_and_never_rewritten(shop):
    from services.blueprint.service import BlueprintService
    from services.smith import file_edit
    from services.smith.writes import add_expectation
    st = {"says": "A patient who opens the slots sees the slots screen.", "kind": "reach",
          "steps": [{"as": "ROLE-001", "act": "open", "page": "PAGE-001"}],
          "then": [{"check": "gets", "page": "PAGE-001", "gets": "shown"}]}
    out = add_expectation(str(shop), st, "report")
    assert out["applied"] and "try_expectation" in out["said"], out
    saved = BlueprintService.load(output_dir=shop).doc["expectations"]
    assert len(saved) == 1 and saved[0]["origin"] == "report" and saved[0]["id"].startswith("EXP-")
    again = add_expectation(str(shop), {**st, "says": "  a patient who opens the SLOTS sees the slots screen. "})
    assert not again["applied"] and "already says that" in again["finding"]
    bad = add_expectation(str(shop), {**st, "says": "Another", "steps": [{"as": "ROLE-009", "act": "open",
                                                                            "page": "PAGE-404"}]})
    assert not bad["applied"] and "PAGE-404" in bad["finding"]
    edit = file_edit.edit_definition(str(shop), f"expectations.{saved[0]['id']}", "shown", "not_found")
    assert not edit["applied"] and "not edited to fit the app" in edit["finding"]


def test_the_build_tries_the_statements_and_no_longer_runs_the_separate_checks():
    import importlib
    import inspect
    from routers import blueprint_generate
    src = inspect.getsource(blueprint_generate._finish_unfinished_pages)
    assert "prove_expectations(" in src
    assert "check_app(" not in src and "prove_processes(" not in src, \
        "process trials and the page check cost more than they found, and are gone from the build"
    handle = importlib.import_module("services.smith4.handle")
    checked = inspect.getsource(handle._checked)
    assert "services.expects.build" in checked and "app_check" not in checked


def test_a_process_handed_too_little_is_the_screens_fault_not_the_processs():
    doc = copy.deepcopy(DOC)
    doc["workflows"] = [{"id": "FLOW-002", "name": "Update Stock",
                         "inputs": [{"name": "variant", "required": True}, {"name": "quantity", "required": True}]}]
    ran = {"failures": ["no Variant with stockQuantity=20 is stored"], "where": "PAGE-001",
           "sent": [{"method": "POST", "path": "/api/workflows/FLOW-002/execute", "status": 200,
                     "request": '{"input": {"quantity": 20}}', "body": '{"status": "completed", "records": {}}'}]}
    assert build.owner_of(ran, doc) == ("page_code", "PAGE-001"), "the screen did not send the variant"
    brief = build.author_brief(doc, [({}, {**ran, "id": "EXP-009", "says": "x", "verdict": "failed"})],
                               "page_code", "PAGE-001")
    assert 'sent: {"input": {"quantity": 20}}' in brief and "did not send what the process needs: variant" in brief
    ran["sent"][0]["request"] = '{"input": {"variant": "v1", "quantity": 20}}'
    assert build.owner_of(ran, doc) == ("workflow_steps", "FLOW-002"), "given all it needs, it is the process's"


def test_an_author_gets_a_second_look_with_what_its_change_showed(tmp_path):
    svc = _Svc(DOC)
    rounds = [{"results": [_refused("EXP-001"), _result("EXP-002", "passed")]},
              {"results": [{**_refused("EXP-001"), "failures": ["Patient was told refusal: slot is closed"]}]},
              {"results": [_result("EXP-001", "passed")]}]
    briefs: list[str] = []

    def trial(_app, _doc, _project, only=None):
        return rounds.pop(0)
    out = build._prove(svc, str(tmp_path), app_factory=lambda _r: _App(), trial=trial,
                       author=lambda _s, _o, node, subject, brief: briefs.append(brief) or [])
    assert len(briefs) == 2 and "slot is closed" in briefs[1], "the second look carries what the first change showed"
    assert out["fixed"] == ["EXP-001"]


def test_no_review_is_offered_after_the_statements_were_tried():
    from routers.blueprint_generate import _announce_build_complete
    said: list[dict] = []
    doc = {"pages": [{"id": "PAGE-001", "route": "/slots"}],
           "runtime": {"expectations": {"statements": 2, "passed": 2, "fixed": [], "failing": [], "untried": []}}}
    _announce_build_complete(doc, lambda kind, data: said.append(data), offer_verify=True)
    assert said and not any(d.get("options") for d in said), "the build says what held; it does not offer a second pass"
