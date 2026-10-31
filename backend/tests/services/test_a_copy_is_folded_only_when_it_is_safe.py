"""A workflow's own copy of a rule is taken out only when that is safe and
proven (PR #29 review, 2026-10-26):

1. nothing but other yes/no checks may sit between the check and the save —
   a payment or a value set on the way would run before the save is stopped;
2. the sample saves must be able to tell the two conditions apart — a check
   the samples cannot judge (`string length(title) >= 3`) is never taken for
   a rule that is weaker ("title is not blank");
3. the samples are never cut short;
4. Smith never takes out a check that differs from the rule unasked.

The gates here need no node: they decide before the rule lab is asked."""
from __future__ import annotations

import copy

import pytest

from services import rule_links as L
from tests.rule_lab_needed import needs_lab as needs_node  # node and esbuild
from tests.services.test_rules_are_linked_to_the_workflows_that_save_them import _doc

_STOP = {"key": "stop", "type": "end", "config": {"refused": True, "message": "No."}, "next": []}
_INSERT = {"key": "ins", "type": "action", "entity": "ENTITY-001",
           "config": {"actionType": "db_insert", "table": "expenses",
                      "values": {"title": "{{title}}", "amount": "{{amount}}", "category": "{{category}}",
                                 "status": "submitted"}}, "next": []}


def _one(rule: dict, steps: list[dict]) -> dict:
    doc = _doc()
    doc["businessRules"] = [rule]
    doc["workflows"] = [{"id": "FLOW-9", "name": "Pay", "steps": steps}]
    return doc


_POSITIVE = {"id": "RULE-001", "name": "Positive", "kind": "condition_action", "entity": "ENTITY-001",
             "when": "amount = null or amount <= 0", "then": [{"type": "show_error", "message": "More than zero."}],
             "otherwise": []}


def _check(expr: str, nxt: str) -> dict:
    return {"key": "chk", "type": "condition", "config": {"expression": expr}, "next": [nxt, "stop"]}


@pytest.mark.parametrize("between", [
    {"key": "mid", "type": "action", "config": {"actionType": "http_request", "url": "https://pay.example"}},
    {"key": "mid", "type": "action", "config": {"actionType": "set_variable", "name": "amount", "value": "1"}},
    {"key": "mid", "type": "action", "config": {"actionType": "send_email", "to": "a@b.c"}},
    {"key": "mid", "type": "action", "config": {"actionType": "db_insert", "table": "audit_log", "values": {}}},
])
def test_a_check_with_a_side_effect_before_the_save_is_never_a_copy(between):
    steps = [{"key": "start", "type": "trigger", "next": ["chk"]}, _check("amount > 0", "mid"), _STOP,
             {**between, "next": ["ins"]}, _INSERT]
    doc = _one(_POSITIVE, steps)
    assert L.candidates(doc, _POSITIVE) == []
    assert L.fold_copies(doc) == [] and len(doc["workflows"][0]["steps"]) == 5


def test_a_branch_on_the_way_is_not_passed_through():
    steps = [{"key": "start", "type": "trigger", "next": ["chk"]}, _check("amount > 0", "pick"), _STOP,
             {"key": "pick", "type": "condition", "config": {"expression": 'category = "travel"'},
              "next": ["ins", "other"]},
             {"key": "other", "type": "end", "config": {"refused": False}, "next": []}, _INSERT]
    assert L.candidates(_one(_POSITIVE, steps), _POSITIVE) == []


def test_other_yes_no_checks_on_the_way_are_passed_through():
    steps = [{"key": "start", "type": "trigger", "next": ["chk"]}, _check("amount > 0", "chk2"), _STOP,
             {"key": "chk2", "type": "condition", "config": {"expression": 'category != null'},
              "next": ["ins", "stop2"]},
             {"key": "stop2", "type": "end", "config": {"refused": True, "message": "Pick one."}, "next": []},
             _INSERT]
    cands = L.candidates(_one(_POSITIVE, steps), _POSITIVE)
    assert [c["step"] for c in cands] == ["chk"] and cands[0]["save"]["step"] == "ins"


@pytest.mark.parametrize("expr, ok", [
    ("amount > 0", True),
    ('amount = null or amount <= 0', True),
    ('not(category in ["travel", "meals"])', True),
    ('status = "rejected" and previous.status != "approved"', True),
    ('amount >= 10 or (category = "x" and amount < 3)', True),
    ("string length(title) >= 3", False),
    ('contains(title, "x")', False),
    ("amount * 2 > 10", False),
    ("amount between 1 and 5", False),
    ("amount in [1..5]", False),
    ('title > "m"', False),
    ("due < today()", False),
])
def test_only_conditions_the_samples_can_judge_are_compared(expr, ok):
    assert L.simple(expr) is ok


def test_a_check_the_samples_cannot_judge_is_never_folded_and_the_lab_is_not_asked(monkeypatch):
    from services.blueprint import rule_lab
    monkeypatch.setattr(rule_lab, "run", lambda *a, **k: pytest.fail("the lab must not be asked"))
    weaker = {"id": "RULE-009", "name": "Title", "kind": "condition_action", "entity": "ENTITY-001",
              "when": 'title = null or title = ""', "then": [{"type": "show_error", "message": "Title, please."}],
              "otherwise": []}
    steps = [{"key": "start", "type": "trigger", "next": ["chk"]}, _check("string length(title) >= 3", "ins"),
             _STOP, _INSERT]
    doc = _one(weaker, steps)
    L._JUDGED.clear(); L._UNJUDGED.clear()
    judged = L.review_all(doc)
    assert [(c["same"], bool(c.get("unproven"))) for c in judged] == [(False, True)]
    assert L.fold_copies(copy.deepcopy(doc)) == []
    # Shown as an older check for the person to decide, with the reason.
    assert [c["step"] for c in L.stale(doc, judged)] == ["chk"]


def test_a_save_that_works_out_its_values_is_not_compared(monkeypatch):
    from services.blueprint import rule_lab
    monkeypatch.setattr(rule_lab, "run", lambda *a, **k: pytest.fail("the lab must not be asked"))
    ins = copy.deepcopy(_INSERT)
    ins["config"]["values"]["amount"] = "{{amount}} * 2"
    doc = _one(_POSITIVE, [{"key": "start", "type": "trigger", "next": ["chk"]}, _check("amount > 0", "ins"),
                           _STOP, ins])
    L._JUDGED.clear(); L._UNJUDGED.clear()
    assert [c.get("unproven") for c in L.review_all(doc)] == [
        "the save works out its values in a way the comparison can't follow"]


def test_the_samples_are_never_cut_short():
    dims = [(f"in:f{i}", list(range(10))) for i in range(4)]  # 10 000 combinations
    assert L._cases(dims) is None
    assert len(L._cases(dims[:3])) == 1000


@needs_node
def test_the_reviewers_two_cases_on_the_real_engine():
    L._JUDGED.clear(); L._UNJUDGED.clear()
    # The plain copy is still proven and folded…
    doc = _one(_POSITIVE, [{"key": "start", "type": "trigger", "next": ["chk"]}, _check("amount > 0", "ins"),
                           _STOP, _INSERT])
    assert [c["same"] for c in L.review_all(doc)] == [True]
    assert [d["step"] for d in L.fold_copies(doc)] == ["chk"]
    assert [s["key"] for s in doc["workflows"][0]["steps"]] == ["start", "ins"]
    # …and a check that is stricter on a simple condition is found to differ, with the case.
    doc = _one(_POSITIVE, [{"key": "start", "type": "trigger", "next": ["chk"]}, _check("amount > 10", "ins"),
                           _STOP, _INSERT])
    (c,) = L.review_all(doc)
    assert c["same"] is False and c["differs"] and not c.get("unproven")
    assert "amount" in L.differs_said(c["differs"])


def test_smith_asks_before_taking_out_a_check_that_differs(tmp_path, monkeypatch):
    from services import business_rules as rules
    from services.blueprint.service import BlueprintService
    from services.smith4.verbs import Ctx, perform

    doc = _doc()
    svc = type("S", (), {})()
    svc.doc, svc.output_dir = doc, str(tmp_path)
    monkeypatch.setattr(BlueprintService, "load", classmethod(lambda cls, **_k: svc))
    old = {"rule": "RULE-001", "workflow": "FLOW-001", "name": "Log an expense", "step": "check_amount",
           "stepName": "check_amount", "expression": "amount > 0 and amount < 10000", "same": False,
           "differs": {"amount": 10000.0}}
    monkeypatch.setattr(L, "review_all", lambda d, *a, **k: [old])
    followed = []
    monkeypatch.setattr(rules, "follow_rule", lambda out, rid, **k: followed.append((rid, k["step"])) or {})
    ctx = Ctx(output_dir=str(tmp_path), project_id="p", message="", ask="")
    out = perform(ctx, "link_rule", {"verb": "link_rule", "rule": "positive amount", "workflow": "log an expense"})
    assert out.status == "needs_user" and not followed
    assert "amount < 10000" in out.said and "amount 10000" in out.said and "replace the old check" in out.said
    out = perform(ctx, "link_rule", {"verb": "link_rule", "rule": "positive amount", "workflow": "log an expense",
                                     "change": "replace the old check with the rule"})
    assert out.status == "resolved" and followed == [("RULE-001", "check_amount")]


@needs_node
def test_the_builds_fold_is_recorded_with_a_version_to_go_back_to(tmp_path, monkeypatch):
    """PR #29 review: the build folded in memory and saved with no change record."""
    import json
    from pathlib import Path

    from services.blueprint import orchestrator
    from services.blueprint.service import BlueprintService
    from tests.routers.test_business_rules_api import FIXTURE, _with_a_copy

    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(Path(FIXTURE).read_text())
    _with_a_copy(tmp_path)
    svc = BlueprintService.load(output_dir=str(tmp_path))
    v0, h0 = int(svc.doc.get("version") or 1), len(svc.doc.get("changeHistory") or [])
    projected = []
    monkeypatch.setattr(orchestrator, "_project_integration", lambda s, root: projected.append(s.doc))
    L._JUDGED.clear(); L._UNJUDGED.clear()
    orchestrator._project_integration_of_a_build(svc, str(tmp_path / "app"))
    saved = json.loads((tmp_path / ".forge" / "blueprint" / "current.json").read_text())
    assert saved["version"] == v0 + 1 and len(saved["changeHistory"]) == h0 + 1
    rec = saved["changeHistory"][-1]
    assert rec["userRequest"].startswith("Build:") and "FLOW-900" in rec["affectedArtifacts"]
    assert svc.versions() and projected and projected[0] is svc.doc
    flow = next(w for w in saved["workflows"] if w["id"] == "FLOW-900")
    assert [s["key"] for s in flow["steps"]] == ["add_role"]


def test_smiths_own_turn_may_link_a_rule_but_still_waits_for_a_build(tmp_path, monkeypatch):
    """Found in the browser (2026-10-28): Smith's link_rule called the rules
    service from inside its own turn, which made the app "busy", and was
    refused with "Smith is working on this app right now"."""
    import json
    from pathlib import Path

    from services import business_rules as rules
    from tests.routers.test_business_rules_api import FIXTURE, _with_a_copy

    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(Path(FIXTURE).read_text())
    _with_a_copy(tmp_path)
    path = tmp_path / ".forge" / "blueprint" / "current.json"
    doc = json.loads(path.read_text())   # the workflow's check is stricter than the rule: an old one
    next(w for w in doc["workflows"] if w["id"] == "FLOW-900")["steps"][0]["config"]["expression"] = "openingsCount >= 2"
    path.write_text(json.dumps(doc))
    L._JUDGED.clear(); L._UNJUDGED.clear()
    monkeypatch.setattr(rules, "TAB_LOCK_WAIT", 0)
    monkeypatch.setattr(rules, "busy", lambda out: "smith")
    with pytest.raises(rules.RuleError):
        rules.follow_rule(tmp_path, "RULE-900", workflow="FLOW-900", step="check_openings")
    rules.follow_rule(tmp_path, "RULE-900", workflow="FLOW-900", step="check_openings", actor="Smith",
                      in_turn=True)
    doc = json.loads((tmp_path / ".forge" / "blueprint" / "current.json").read_text())
    flow = next(w for w in doc["workflows"] if w["id"] == "FLOW-900")
    assert [s["key"] for s in flow["steps"]] == ["add_role"]
    monkeypatch.setattr(rules, "busy", lambda out: "building")
    with pytest.raises(rules.RuleError):
        rules.attach(tmp_path, "RULE-900", workflow="FLOW-900", after=None, in_turn=True)


def test_two_close_literals_get_a_sample_between_them():
    """PR #29 re-review: `amount >= 0.01` against the rule `amount <= 0` had
    no sample between 0 and 0.01, so the stricter check looked the same."""
    values = [v for v in L._sample_values({"name": "amount", "type": "number"}, [0.01, 0.0], [])
              if v is not None]
    assert any(0 < v < 0.01 for v in values)
    # Far-apart literals already have one between them; none are added there.
    far = [v for v in L._sample_values({"name": "amount", "type": "number"}, [5.0], []) if v is not None]
    assert all(b - a >= 0.5 for a, b in zip(far, far[1:]))


@needs_node
def test_a_check_stricter_by_a_hair_is_not_a_copy():
    L._JUDGED.clear(); L._UNJUDGED.clear()
    doc = _one(_POSITIVE, [{"key": "start", "type": "trigger", "next": ["chk"]}, _check("amount >= 0.01", "ins"),
                           _STOP, _INSERT])
    (judged,) = L.review_all(doc)
    assert judged["same"] is False and 0 < judged["differs"]["amount"] < 0.01
    assert L.fold_copies(copy.deepcopy(doc)) == []


def test_a_comparison_the_engine_could_not_make_is_not_asked_again_at_once(monkeypatch):
    """PR #29 re-review: a timed-out answer was not remembered, so a large app
    waited for the engine on every open of its Rules tab."""
    from services.blueprint import rule_lab
    asked = []

    def slow(*a, **k):
        asked.append(k.get("timeout"))
        raise rule_lab.LabUnavailable("the rule lab took too long")
    monkeypatch.setattr(rule_lab, "run", slow)
    doc = _one(_POSITIVE, [{"key": "start", "type": "trigger", "next": ["chk"]}, _check("amount > 0", "ins"),
                           _STOP, _INSERT])
    L._JUDGED.clear(); L._UNJUDGED.clear()
    assert [c["same"] for c in L.review_all(doc, timeout=20)] == [None]
    assert [c["same"] for c in L.review_all(doc, timeout=20)] == [None]
    assert asked == [20], "asked once, with the wait the caller gave"
    assert L.fold_copies(copy.deepcopy(doc)) == []  # not known is never folded
    # After a while it is asked again.
    monkeypatch.setattr(L, "_RETRY_AFTER", 0.0)
    L.review_all(doc)
    assert asked == [20, 90]
