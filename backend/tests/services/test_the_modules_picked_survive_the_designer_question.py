"""The modules a person picked at the product model are still the build's after the designer question.

Review of 3057b929: `_run_dag` stopped at `ui_designer.gate` BEFORE it recorded the module choice, and the
answer that started the build again called `_run_dag` with no `modules`, which means ALL. Someone who picked
one module at the review got the whole application, the waiting modules built too."""
from __future__ import annotations

import pytest

from routers import blueprint_generate as router
from services.blueprint import scope
from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_UI_DESIGNER", raising=False)
    s = BlueprintService.create(output_dir=tmp_path, app_id="kids", name="KidsCare", domain="health")
    s.doc["requirements"] = [{"id": "REQ-001", "description": "A parent books a visit.", "status": "VERIFIED"}]
    s.doc["modules"] = [{"id": "MODULE-001", "name": "Appointments", "description": "Booking visits."},
                        {"id": "MODULE-002", "name": "Clinic admin", "description": "Doctors and hours."},
                        {"id": "MODULE-003", "name": "Billing", "description": "Invoices."}]
    s.validate()
    s.save()
    return s


def _held(tmp_path):
    return scope.deferred_modules(BlueprintService.load(output_dir=tmp_path).doc)


def test_chosen_reads_back_what_choose_recorded(svc):
    assert scope.chosen(svc.doc) is None, "nothing waiting is the whole application"
    scope.choose(svc, ["MODULE-001", "MODULE-003"])
    assert scope.chosen(svc.doc) == ["MODULE-001", "MODULE-003"]
    assert scope.deferred_modules(svc.doc) == {"MODULE-002"}
    scope.choose(svc, None)
    assert scope.chosen(svc.doc) is None


def test_the_choice_is_recorded_even_when_the_build_stops_to_ask_who_designs(svc, tmp_path):
    said = []
    out = router._run_dag(str(tmp_path), str(tmp_path / "app"), "", approved=True,
                          emit=lambda kind, data: said.append((kind, data)), modules=["MODULE-001"])
    assert out["status"] == "asked", "nobody has said who designs the screens"
    assert _held(tmp_path) == {"MODULE-002", "MODULE-003"}, "the picked module survived the stop"


def test_the_answer_that_starts_the_build_again_carries_the_choice(svc, tmp_path):
    router._run_dag(str(tmp_path), str(tmp_path / "app"), "", approved=True, emit=lambda *a: None,
                    modules=["MODULE-001"])
    # the person answers; the continuation asks what was picked and passes it on
    picked = router._modules_picked(tmp_path)
    assert picked == ["MODULE-001"]
    again = BlueprintService.load(output_dir=tmp_path)
    scope.choose(again, picked)                        # what `_run_dag` does first when it starts again
    assert _held(tmp_path) == {"MODULE-002", "MODULE-003"}


def test_without_the_carried_choice_the_old_continuation_built_everything(svc, tmp_path):
    """The behaviour that was reported, so the cure is visibly the cure."""
    router._run_dag(str(tmp_path), str(tmp_path / "app"), "", approved=True, emit=lambda *a: None,
                    modules=["MODULE-001"])
    scope.choose(BlueprintService.load(output_dir=tmp_path), None)      # a continuation with no selection
    assert _held(tmp_path) == set(), "`None` is ALL: the waiting modules were put back"


def test_the_continuations_pass_the_selection(svc):
    import inspect

    chat = inspect.getsource(router.smith_chat)
    assert chat.count("modules=_modules_picked(output_dir)") == 3, "the Figma steps, the designer answer, the key saved"
