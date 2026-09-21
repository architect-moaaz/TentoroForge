"""A finding at the end of a build goes back to the step that owns it; what is
still wrong after the rounds ships as a recorded issue, not a dead run.

0l133sp2 threw away thirty minutes of generation on one form the dry run said
would refuse its first click. The data model was never tried in a database.
"""
from __future__ import annotations

import pytest

from services.blueprint import build_repair, data_gate
from services.blueprint.assembly import BuildFailed, DispatchesRefused

PROBLEM = {"route": "/disputes/new", "control": "Form", "label": "Create", "workflow": "FLOW-013",
           "input": {"reason": "x"}, "node": "update_rental", "actionType": "db_update",
           "problem": "WHERE resolved to nothing"}


class _Svc:
    doc = {"data": {"entities": [{"id": "ENTITY-002", "name": "Tool", "table": "tools",
                                  "fields": [{"name": "quantity", "type": "integer"}]}]}}


def _wire(monkeypatch, verify_outcomes, repaired):
    import services.blueprint.assembly as assembly
    import services.blueprint.orchestrator as orchestrator
    import services.blueprint.projection as projection

    calls = {"repair": [], "project": 0}
    outcomes = iter(verify_outcomes)

    def verify(app_root):
        o = next(outcomes)
        if isinstance(o, Exception):
            raise o
        return o

    def fake_repair(svc, node, feedback, usage=None):
        calls["repair"].append((node, dict(feedback)))
        return repaired

    monkeypatch.setattr(assembly, "verify_dispatches", verify)
    monkeypatch.setattr(build_repair, "repair", fake_repair)
    monkeypatch.setattr(orchestrator, "_project_integration", lambda svc, root: calls.__setitem__("project", calls["project"] + 1))
    monkeypatch.setattr(projection, "project_dispatches", lambda doc, root: None)
    return calls


def test_a_refused_control_goes_to_the_step_author_and_is_proved_again(monkeypatch):
    calls = _wire(monkeypatch, [DispatchesRefused("no", [PROBLEM]), 7], ["FLOW-013"])
    issues: list[dict] = []
    assert build_repair.dispatches_with_repair(_Svc(), "/app", issues) == 7
    assert issues == []
    node, feedback = calls["repair"][0]
    assert node == "workflow_steps" and "WHERE resolved to nothing" in feedback["FLOW-013"]
    assert calls["project"] == 1, "the repaired workflow is projected before the re-run"


def test_what_is_still_wrong_ships_as_an_issue_not_a_dead_run(monkeypatch):
    refused = DispatchesRefused("no", [PROBLEM])
    _wire(monkeypatch, [refused, refused, refused], ["FLOW-013"])
    issues: list[dict] = []
    assert build_repair.dispatches_with_repair(_Svc(), "/app", issues) == 0
    assert issues and issues[0]["kind"] == "control" and issues[0]["workflow"] == "FLOW-013"


def test_a_refused_control_is_still_a_build_failure_to_anyone_else():
    assert issubclass(DispatchesRefused, BuildFailed)


def test_the_database_refusal_goes_to_the_entity_and_the_app_is_rebuilt(monkeypatch):
    import services.blueprint.assembly as assembly
    import services.blueprint.orchestrator as orchestrator
    import services.blueprint.projection as projection

    results = iter([{"ok": False, "push": {"ok": False, "error": 'invalid input syntax for type integer: "many" in "tools"'}},
                    {"ok": True, "push": {"ok": True}, "seed": {"ok": True, "failed": []}}])
    monkeypatch.setattr(data_gate, "run", lambda root, seed: next(results))
    asked = []
    monkeypatch.setattr(build_repair, "repair", lambda svc, node, fb, usage=None: asked.append((node, fb)) or list(fb))
    monkeypatch.setattr(orchestrator, "_project_data_layer", lambda svc, root: None)
    monkeypatch.setattr(projection, "project_seed", lambda doc, root: None)
    built = []
    monkeypatch.setattr(assembly, "verify_build", lambda root, **kw: built.append(kw) or {})
    issues: list[dict] = []
    out = build_repair.database_with_repair(_Svc(), "/app", issues)
    assert out["ok"] and out["rebuilt"] and issues == []
    assert asked[0][0] == "entity_fields" and "ENTITY-002" in asked[0][1]
    assert built == [{"install": False, "dispatches": False}]


def test_no_docker_is_a_skipped_look_not_a_failure(monkeypatch):
    monkeypatch.setattr(data_gate, "run", lambda root, seed: {"ok": True, "skipped": "docker is not installed"})
    issues: list[dict] = []
    out = build_repair.database_with_repair(_Svc(), "/app", issues)
    assert out["skipped"] and issues == []


def test_the_data_model_is_proved_in_a_database_when_it_is_judged():
    import inspect

    from services.blueprint import orchestrator
    assert "entity_fields" in orchestrator.DATABASE_CHECKED_NODES
    assert "_observe_with_database, observer_agent, key, app_root" in inspect.getsource(orchestrator)


def test_the_assemble_step_repairs_rather_than_raising_on_a_proof():
    import inspect

    from services.blueprint import orchestrator
    src = inspect.getsource(orchestrator._project_assemble)
    assert "dispatches=False" in src and "dispatches_with_repair" in src and "database_with_repair" in src
    assert '"passed_with_issues"' in src


@pytest.mark.parametrize("error, entity", [
    ('relation "tools" already exists', "ENTITY-002"),
    ('column "quantity" of relation "x" cannot be cast', "ENTITY-002"),
])
def test_a_database_error_names_its_entity(error, entity):
    found = data_gate.findings(_Svc.doc, {"push": {"ok": False, "error": error}})
    assert [f.artifact_id for f in found] == [entity]


def test_a_dry_run_that_cannot_start_is_a_look_not_taken(monkeypatch):
    _wire(monkeypatch, [BuildFailed("the dispatch dry run could not run (1): Cannot find module")], [])
    issues: list[dict] = []
    assert build_repair.dispatches_with_repair(_Svc(), "/app", issues) == 0
    assert issues[0]["kind"] == "check" and "could not run" in issues[0]["detail"]


def test_a_page_that_fails_to_project_does_not_take_the_colours_with_it(monkeypatch, tmp_path):
    """The tokens used to be written AFTER the page projection, so any page
    failure skipped them. HippieKit's route with a camelCase param was refused
    there, and its green (#17B65C) never reached tokens.css — the app ran on
    the scaffold's near-black and every button came out the wrong colour."""
    import services.blueprint.orchestrator as orchestrator
    import services.blueprint.projection as projection

    written = []
    monkeypatch.setattr(projection, "project_brand_logo", lambda doc, root: written.append("logo"))
    monkeypatch.setattr(projection, "project_design_tokens", lambda doc, root: written.append("tokens"))

    def refuse(svc, root):
        raise ValueError("route segment '[scanId]' contains unsafe characters")
    monkeypatch.setattr(projection, "apply_frontend_projection", refuse)

    with pytest.raises(ValueError):
        orchestrator._project_frontend(_Svc(), str(tmp_path))
    assert written == ["logo", "tokens"], "the look is written before anything about pages can fail"
