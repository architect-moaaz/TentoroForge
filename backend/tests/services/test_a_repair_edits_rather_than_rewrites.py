"""An observer repair edits the accepted answer instead of writing it again.

MEASURED on a master-data build: the application model's first pass wrote
10,492 output tokens in 92 seconds; the observer flagged a few points; the
repair wrote 10,240 tokens in 80 seconds to change them. Five more nodes the
observer judges paid the same way, 163-238 seconds each. A repair now sends
back JSON Patch edits against the node's current output, and those go through
the same apply path a rewrite does. Anything unusable falls back to the
rewrite, so the change can only ever save a repair, never cost one.
"""
import json

import pytest

from services.blueprint.agent_contract import AgentResult
from services.blueprint.artifact_patch import (
    PATCH_SCHEMA, EditUnusable, apply_edits, editable_artifacts,
    patch_node_output,
)
from services.blueprint.executors import make_executor
from services.blueprint.observer import Observer
from services.blueprint.orchestrator import TaskSpec, run
from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="a",
                                name="Clinic", domain="health")
    s.doc["requirements"] = [{"id": "REQ-001", "description":
                              "Reception registers walk-in patients."}]
    s.save()
    return s


MODULE = {"section": "modules", "natural_key": "MODULE:intake",
          "body": {"name": "Intake", "description": "wrong"}}


def _edit(path, value, op="replace"):
    return {"op": op, "path": path, "value": json.dumps(value)}


# ----------------------------------------------------------- the edit itself

def test_an_edit_changes_only_what_it_names():
    out = apply_edits([MODULE], [_edit("/artifacts/0/body/description", "right")],
                      {"modules"})
    assert out[0]["body"] == {"name": "Intake", "description": "right"}
    assert out[0]["natural_key"] == "MODULE:intake"
    assert MODULE["body"]["description"] == "wrong", "the input must not be mutated"


def test_an_edit_may_add_an_artifact():
    new = {"section": "modules", "natural_key": "MODULE:billing",
           "body": {"name": "Billing", "description": "payments"}}
    out = apply_edits([MODULE], [_edit("/artifacts/-", new, op="add")], {"modules"})
    assert [a["body"]["name"] for a in out] == ["Intake", "Billing"]


@pytest.mark.parametrize("edits, why", [
    ([], "no edits"),
    ([_edit("/other/0", 1)], "outside"),
    ([_edit("/artifacts/0/natural_key", "MODULE:x")], "re-key"),
    ([_edit("/artifacts/0/section", "pages")], "re-key"),
    ([_edit("/artifacts/0/body", "not an object")], "lost its body"),
    ([{"op": "replace", "path": "/artifacts/0/body/name", "value": "{not json"}], "not JSON"),
    ([_edit("/artifacts/9/body/name", "x")], "does not apply"),
    ([_edit("/artifacts/0/body/x", i, op="add") for i in range(61)], "more than"),
    ([_edit("/artifacts/0/body/status", "DEPRECATED")], "document field"),
    ([_edit("/artifacts/0/body/capabilities/0/syncNote", "x", op="add")], "document field"),
])
def test_an_unusable_edit_is_refused_so_the_caller_rewrites(edits, why):
    with pytest.raises(EditUnusable) as caught:
        apply_edits([MODULE], edits, {"modules"})
    assert why in str(caught.value)


def test_an_edit_cannot_write_into_a_section_the_node_does_not_own():
    stray = {"section": "pages", "natural_key": "PAGE:/x", "body": {"route": "/x"}}
    with pytest.raises(EditUnusable):
        apply_edits([MODULE], [_edit("/artifacts/-", stray, op="add")], {"modules"})


# ------------------------------------------------ what the model is shown

def test_the_editable_output_is_exactly_what_the_subject_authored(svc):
    svc.upsert("modules", {"name": "Intake", "description": "d"}, natural_key="MODULE:intake")
    svc.upsert("modules", {"name": "Other", "description": "e"}, natural_key="MODULE:other")
    svc.doc["navigation"] = {"style": "sidebar", "tree": []}
    arts = editable_artifacts(svc.doc, ("navigation", "modules"),
                              {("id", "modules", "MODULE-001")},
                              output_dir=svc.output_dir)
    assert [a["section"] for a in arts] == ["modules", "navigation"]
    module = arts[0]
    assert module["body"]["name"] == "Intake"
    assert "id" not in module["body"] and "status" not in module["body"]
    # Nested rows carry document fields too; the model once edited those.
    svc.doc["product"] = {"name": "P", "capabilities": [
        {"name": "Nav", "status": "DRAFT", "syncNote": "n"}]}
    [product] = editable_artifacts(svc.doc, ("product",), set(), output_dir=svc.output_dir)
    assert product["body"]["capabilities"] == [{"name": "Nav"}]
    # The key the registry bound the id to, so an edit keeps the id.
    assert module["natural_key"] == "MODULE:intake"


# ------------------------------------------- the reply, parsed and applied

def _spec(**over):
    base = dict(task_id="TASK-x-observer1", node="ux_architecture",
                agent="solution_architecture", subject="",
                feedback="- [Observer↔Requirement] MODULE-001: wrong description",
                current=(MODULE,))
    base.update(over)
    return TaskSpec(**base)


def test_a_usable_reply_becomes_an_ordinary_result():
    reply = json.dumps({"edits": [_edit("/artifacts/0/body/description", "right")],
                        "note": "fixed"})
    result = patch_node_output(_spec(), lambda **_: reply, system="S",
                               produces={"modules", "navigation"}, task_id="T")
    assert isinstance(result, AgentResult)
    assert result.proposals[0].body["description"] == "right"
    assert "1 edit" in result.assumptions[0]


@pytest.mark.parametrize("reply", ["{broken", json.dumps({"edits": [], "note": "can't"})])
def test_an_unusable_reply_means_rewrite(reply):
    assert patch_node_output(_spec(), lambda **_: reply, system="S",
                             produces={"modules"}, task_id="T") is None


def test_a_first_pass_or_a_retry_is_never_an_edit():
    """Only an observer repair carries the accepted answer."""
    assert patch_node_output(_spec(current=()), lambda **_: "{}", system="S",
                             produces={"modules"}, task_id="T") is None
    assert patch_node_output(_spec(feedback=""), lambda **_: "{}", system="S",
                             produces={"modules"}, task_id="T") is None


def test_the_edit_call_is_asked_for_edits_not_an_envelope():
    seen = {}
    def client(*, system, user, schema):
        seen.update(system=system, user=user, schema=schema)
        return json.dumps({"edits": [_edit("/artifacts/0/body/description", "r")], "note": ""})
    patch_node_output(_spec(), client, system="NODE RULES", produces={"modules"},
                      task_id="T", context="THE BLUEPRINT")
    assert seen["schema"] is PATCH_SCHEMA
    assert seen["system"].startswith("NODE RULES") and "REPAIR" in seen["system"]
    assert seen["user"].startswith("THE BLUEPRINT")
    assert "wrong description" in seen["user"] and '"MODULE:intake"' in seen["user"]


def test_the_edit_call_runs_at_edit_effort_not_the_nodes():
    """At the node's high effort an edit reasons as long as a rewrite writes."""
    import dataclasses
    from services.blueprint.artifact_patch import EDIT_EFFORT

    @dataclasses.dataclass(frozen=True)
    class Client:
        effort: str = "high"
        def __call__(self, *, system, user, schema):
            seen.append(self.effort)
            return json.dumps({"edits": [_edit("/artifacts/0/body/description", "r")], "note": ""})
    seen = []
    patch_node_output(_spec(), Client(), system="S", produces={"modules"}, task_id="T")
    assert seen == [EDIT_EFFORT] != ["high"]


# ------------------------------------- end to end: executor + orchestrator

@pytest.fixture()
def watched(monkeypatch):
    """`ux_architecture` is off the observer in a real run (zero rounds); the
    edit path is the same for any observed single-subject node, so these
    tests give it its rounds back to exercise it."""
    from services.blueprint import orchestrator
    monkeypatch.delitem(orchestrator.OBSERVER_ROUNDS_BY_NODE, "ux_architecture")


class _Critic:
    def __init__(self):
        self.calls = 0
        self.enforces_schema = True

    def __call__(self, *, system, user, schema):
        self.calls += 1
        if self.calls == 1:
            return json.dumps({"verdict": "fail", "findings": [{
                "section": "modules", "artifact": "MODULE-001",
                "requirement": "REQ-001",
                "detail": "the Intake module's description does not say what it does"}]})
        return json.dumps({"verdict": "pass", "findings": []})


def test_the_repair_arrives_as_an_edit_and_keeps_the_id(svc, watched):
    calls = []

    def model(*, system, user, schema):
        calls.append(schema)
        if schema is PATCH_SCHEMA:
            return json.dumps({"edits": [_edit(
                "/artifacts/0/body/description",
                "Registers walk-in patients at reception")], "note": "described it"})
        return json.dumps({
            "proposals": [{"section": "modules", "natural_key": "MODULE:intake",
                           "body": json.dumps({"name": "Intake", "description": "wrong"})}],
            "confidence": 0.9, "assumptions": [], "issues": [], "change_requests": []})

    report = run(svc, make_executor(svc, model), plan=["ux_architecture"],
                 observer_agent=Observer(critic=_Critic(), rounds=2))
    assert "ux_architecture" in report.completed
    assert calls[0] is not PATCH_SCHEMA, "the first pass authors"
    assert calls[1] is PATCH_SCHEMA, "the repair edits"
    assert len(calls) == 2, "no rewrite happened"
    modules = [m for m in svc.doc["modules"] if m.get("status") != "DEPRECATED"]
    assert [m["id"] for m in modules] == ["MODULE-001"], "the edit kept its id"
    assert modules[0]["description"] == "Registers walk-in patients at reception"
    assert report.repaired == ["ux_architecture"]
    assert not report.unrepaired


def test_an_edit_that_fails_falls_back_to_the_rewrite(svc, watched):
    calls = []

    def model(*, system, user, schema):
        calls.append(schema)
        if schema is PATCH_SCHEMA:
            return "{not json"
        desc = "wrong" if len(calls) == 1 else "Registers walk-in patients"
        return json.dumps({
            "proposals": [{"section": "modules", "natural_key": "MODULE:intake",
                           "body": json.dumps({"name": "Intake", "description": desc})}],
            "confidence": 0.9, "assumptions": [], "issues": [], "change_requests": []})

    run(svc, make_executor(svc, model), plan=["ux_architecture"],
        observer_agent=Observer(critic=_Critic(), rounds=2))
    assert [c is PATCH_SCHEMA for c in calls] == [False, True, False]
    live = [m for m in svc.doc["modules"] if m.get("status") != "DEPRECATED"]
    assert live[0]["description"] == "Registers walk-in patients"
