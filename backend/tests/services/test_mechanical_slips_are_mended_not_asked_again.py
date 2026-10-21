"""What has exactly one right answer is mended before the checks read it, so
a reply is never sent back for it. Refund And Chargeback's processes (pah7lhfz,
forge-v3 2026-10-20) were refused about ten times for these, two went to the
strongest model, and Import Excel Tracker shipped switched off — its second
try had only these left."""
from __future__ import annotations

from services.blueprint import agent_contract as ac
from services.blueprint.agent_contract import AgentResult, ArtifactProposal

DOC = {"data": {"entities": [{"id": "ENTITY-001", "name": "Exception", "table": "exceptions", "fields": [
    {"name": "id", "type": "uuid", "primaryKey": True},
    {"name": "createdAt", "type": "datetime", "required": True},
    {"name": "updatedAt", "type": "datetime", "required": True},
    {"name": "openedOn", "type": "datetime", "required": True},
    {"name": "note", "type": "string"}]}]},
       "mobile": {"push": False}}


def _flow(body: dict) -> AgentResult:
    return AgentResult(task_id="t", agent="workflow",
                       proposals=[ArtifactProposal(section="workflows", natural_key=body["name"], body=body)])


def test_a_sentinel_in_braces_is_written_bare_but_one_inside_a_sentence_is_left():
    body = {"name": "Snap", "trigger": {"kind": "manual"}, "steps": [
        {"key": "save", "type": "action", "config": {"actionType": "db_update", "values": {
            "by": "{{$user.id}}", "at": " {{ $now }} ", "note": "made {{$now}}", "other": "{{$nope}}"}}}]}
    said = ac.mend_mechanics(_flow(body), DOC)
    values = body["steps"][0]["config"]["values"]
    assert values == {"by": "$user.id", "at": "$now", "note": "made {{$now}}", "other": "{{$nope}}"}
    assert len(said) == 2


def test_a_new_record_takes_now_for_its_created_and_updated_times_and_nothing_else():
    body = {"name": "Raise", "trigger": {"kind": "manual"}, "steps": [
        {"key": "raise", "type": "action", "config": {"actionType": "db_insert", "table": "exceptions",
                                                       "values": {"note": "x"}}}]}
    ac.mend_mechanics(_flow(body), DOC)
    values = body["steps"][0]["config"]["values"]
    assert values["createdAt"] == "$now" and values["updatedAt"] == "$now"
    assert "openedOn" not in values          # a business date is the author's to decide


def test_a_start_step_takes_the_trigger_its_workflow_declares():
    body = {"name": "Poll", "trigger": {"kind": "schedule", "cron": "*/15 * * * *"}, "steps": [
        {"key": "start", "type": "trigger", "config": {}},
        {"key": "done", "type": "end", "config": {"refused": False}}]}
    ac.mend_mechanics(_flow(body), DOC)
    assert body["steps"][0]["config"] == {"type": "schedule", "cron": "*/15 * * * *"}
    watch = {"name": "Hand-off", "trigger": {"kind": "db_change", "entity": "ENTITY-001", "on": "updated"},
             "steps": [{"key": "start", "type": "trigger"}]}
    ac.mend_mechanics(_flow(watch), DOC)
    assert watch["steps"][0]["config"] == {"type": "db_change", "on": "updated", "table": "exceptions"}


def test_push_where_the_app_sends_none_is_sent_in_the_app():
    body = {"name": "Notify", "trigger": {"kind": "manual"}, "steps": [
        {"key": "a", "type": "action", "config": {"actionType": "send_notification", "channels": ["push"]}},
        {"key": "b", "type": "action", "config": {"actionType": "send_notification", "channels": ["in_app", "push"]}}]}
    ac.mend_mechanics(_flow(body), DOC)
    assert [s["config"]["channels"] for s in body["steps"]] == [["in_app"], ["in_app"]]
    on = {"name": "Notify", "trigger": {"kind": "manual"}, "steps": [
        {"key": "a", "type": "action", "config": {"actionType": "send_notification", "channels": ["push"]}}]}
    ac.mend_mechanics(_flow(on), {**DOC, "mobile": {"push": True}})
    assert on["steps"][0]["config"]["channels"] == ["push"]


def test_the_mends_run_before_any_check_when_a_reply_is_filed():
    import inspect
    src = inspect.getsource(ac.apply_agent_result)
    assert src.index("mend_mechanics(result, svc.doc)") < src.index("run(check_pattern_templates")
