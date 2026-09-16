"""A change that takes more than it was asked for says so, and waits.

"Get rid of complaints" retires the entity, the screens built on it, the
workflows that act on it and their buttons on every other screen. The
dependency set was computed one line before the removal started and shown to
nobody — the person found out by looking.
"""

from __future__ import annotations

import json

import pytest

from services.blueprint.ids import page_key
from services.blueprint.service import BlueprintService
from services.smith import confirm
from services.smith.entity_change import consequences as entity_consequences
from services.smith.field_change import consequences as field_consequences
from services.smith_session import SmithSession


@pytest.fixture()
def project(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Roster", domain="health")
    s.doc["data"] = {"entities": [
        {"id": "ENTITY-001", "name": "Nurse", "table": "nurses", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "fullName", "type": "string"},
            {"name": "location", "type": "string"}]},
        {"id": "ENTITY-002", "name": "Complaint", "table": "complaints", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "detail", "type": "string"}]}]}
    lst = s.upsert("pages", {"name": "Complaints", "route": "/complaints", "pattern": "entity_list",
                             "purpose": "All.", "data": {"primaryEntity": "ENTITY-002"}},
                   natural_key=page_key("/complaints"))
    s.upsert("workflows", {"name": "Log Complaint", "purpose": "Log.", "trigger": {"kind": "manual"},
                           "launchedFrom": [], "inputs": [],
                           "steps": [{"key": "start", "name": "Start", "type": "trigger",
                                      "config": {"type": "manual"}, "next": ["do"]},
                                     {"key": "do", "name": "Insert", "type": "action",
                                      "entity": "ENTITY-002",
                                      "config": {"actionType": "db_insert", "table": "complaints",
                                                 "values": {"detail": "{{detail}}"}}, "next": ["end"]},
                                     {"key": "end", "name": "End", "type": "end", "next": []}]},
              natural_key="Log Complaint")
    s.upsert("pageLayouts", {"page": lst["id"], "composedBy": "a2ui",
                             "dataSources": [{"name": "c", "entity": "Complaint", "op": "list"}],
                             "root": {"type": "Stack", "props": {}, "children": [
                                 {"type": "Table", "props": {"data": "{{c}}", "columns": [
                                     {"key": "detail", "label": "Detail"}]}, "children": []}]}},
              natural_key=lst["id"])
    s.save()
    return s


def _session(project, verb: str, **understanding) -> SmithSession:
    return SmithSession(
        project_id="p1", output_dir=str(project.output_dir), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {"verb": verb, **understanding},
        iteration_move_fn=lambda *a, **kw: None)


def test_what_a_removal_takes_with_it_is_computed_without_taking_it(project):
    said = entity_consequences(project.doc, "Complaint")
    assert said["found"] and said["name"] == "Complaint"
    assert said["pages"] == ["/complaints"] and said["workflows"] == ["Log Complaint"]
    # Nothing moved.
    fresh = BlueprintService.load(output_dir=str(project.output_dir))
    assert [e["name"] for e in fresh.doc["data"]["entities"]] == ["Nurse", "Complaint"]
    assert entity_consequences(project.doc, "Nothing")["found"] is False


def test_the_turn_shows_the_cascade_and_waits(project):
    result = _session(project, "remove_entity", entity="Complaint").run_iteration(
        user_message="get rid of complaints")
    assert result.status == "asked"
    assert "does not only remove what you named" in result.answer
    assert "/complaints" in result.answer and "Log Complaint" in result.answer
    assert result.options == [confirm.YES_LABEL, confirm.NO_LABEL]
    # Still there.
    fresh = BlueprintService.load(output_dir=str(project.output_dir))
    assert [e["name"] for e in fresh.doc["data"]["entities"]] == ["Nurse", "Complaint"]


def test_the_yes_lets_through_the_thing_that_was_shown(project):
    _session(project, "remove_entity", entity="Complaint").run_iteration(user_message="get rid of complaints")
    done = _session(project, "remove_entity", entity="Complaint").run_iteration(user_message="Go ahead")
    assert done.status == "resolved"
    fresh = BlueprintService.load(output_dir=str(project.output_dir))
    gone = next(e for e in fresh.doc["data"]["entities"] if e["name"] == "Complaint")
    assert gone["status"] == "DEPRECATED"


def test_a_yes_to_one_thing_is_not_a_yes_to_another(project):
    _session(project, "remove_entity", entity="Complaint").run_iteration(user_message="get rid of complaints")
    # The yes arrives, but for a different operation: it is asked about again.
    other = _session(project, "remove_field", entity="Complaint",
                     field={"name": "detail"}).run_iteration(user_message="Go ahead")
    assert other.status == "asked" and "does not only remove" in other.answer
    fresh = BlueprintService.load(output_dir=str(project.output_dir))
    assert all(e.get("status") != "DEPRECATED" for e in fresh.doc["data"]["entities"])
    assert [f["name"] for f in fresh.doc["data"]["entities"][1]["fields"]] == ["id", "detail"]


def test_the_permission_does_not_outlive_its_question(project):
    _session(project, "remove_entity", entity="Complaint").run_iteration(user_message="get rid of complaints")
    assert confirm.take(project.output_dir)                # read once…
    assert confirm.take(project.output_dir) == ""          # …and gone
    assert not confirm.granted(project.output_dir, "Go ahead", "remove_entity", "Complaint")


def test_only_a_whole_yes_is_a_yes():
    assert confirm.is_yes("Go ahead") and confirm.is_yes("yes") and confirm.is_yes("do it.")
    for said in ("yes but rename it first", "no", "not now", "yes to the other one", ""):
        assert not confirm.is_yes(said), said


def test_removing_a_box_names_the_data_that_goes_with_it(project):
    said = field_consequences(project.doc, "Complaint", "detail")
    assert said["found"] and said["used"] == ["the table on Complaints"]
    result = _session(project, "remove_field", entity="Complaint",
                      field={"name": "detail"}).run_iteration(user_message="drop the detail box")
    assert result.status == "asked"
    assert "cannot be brought back" in result.answer      # the column's data
    assert "the table on Complaints" in result.answer


def test_a_box_is_always_confirmed_because_its_data_always_goes(project):
    """Even a box no screen shows takes its column with it, and that is the
    one thing undo does not bring back."""
    result = _session(project, "remove_field", entity="Nurse",
                      field={"name": "location"}).run_iteration(user_message="drop location")
    assert result.status == "asked" and "cannot be brought back" in result.answer


def test_a_record_that_cascades_into_nothing_is_not_gated(project):
    """A question with nothing to show is friction, not safety — retiring a
    record no screen and no process stands on takes nothing with it."""
    from services.smith_session import SmithSession

    project.doc["data"]["entities"].append({"id": "ENTITY-003", "name": "Note", "table": "notes",
                                            "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]})
    project.save()
    session = SmithSession(
        project_id="p1", output_dir=str(project.output_dir), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {"verb": "remove_entity", "entity": "Note"},
        iteration_move_fn=lambda *a, **kw: None)
    result = session.run_iteration(user_message="we do not need notes")
    assert "does not only remove" not in result.answer
