"""A process a record change starts reads that record. The data engine hands
it over as `entity` (data-engine.ts `_persistEvent`, events/bus.ts
`_dispatchEvent`), and the engine reads dotted paths — but the checks knew
only declared inputs, so `{{guestName}}` (empty at run time) and
`{{entity.guestName}}` (right) were both refused: sixteen refusals in one of
Refund And Chargeback's processes (pah7lhfz, forge-v3 2026-10-20)."""
from __future__ import annotations

from services.blueprint import agent_contract as ac
from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.dispatch_contract import workflow_ref_findings
from services.blueprint.functional_completeness import template_findings

DOC = {"data": {"entities": [{"id": "ENTITY-004", "name": "RefundCase", "table": "refund_cases",
                              "fields": [{"name": "guestName", "type": "string"}, {"name": "status", "type": "string"}]}]}}


def _wf(*refs: str, on: str = "updated") -> dict:
    return {"id": "FLOW-001", "name": "Hand-off", "trigger": {"kind": "db_change", "entity": "ENTITY-004", "on": on},
            "steps": [{"key": "start", "type": "trigger", "config": {"type": "db_change"}},
                      {"key": "tell", "type": "action", "config": {"actionType": "send_notification", "recipientRole": "Finance",
                                                                    "message": " ".join(refs)}}]}


def _details(wf: dict) -> list[str]:
    doc = {**DOC, "workflows": [wf]}
    return [f["detail"] for f in template_findings(doc) + workflow_ref_findings(doc)]


def test_the_record_and_its_earlier_values_are_read_by_entity_and_previous_entity():
    assert _details(_wf("{{entity.guestName}}", "{{previousEntity.status}}", "{{entityId}}", "{{user.id}}")) == []


def test_a_field_the_record_does_not_have_is_refused_naming_its_fields():
    said = _details(_wf("{{entity.nickname}}"))
    assert any("'nickname' is not a field of RefundCase" in d and "guestName" in d for d in said)


def test_the_bare_field_is_refused_with_the_way_to_write_it():
    said = _details(_wf("{{guestName}}"))
    assert any("write `{{entity.guestName}}`" in d for d in said)


def test_previous_values_exist_only_on_an_update():
    assert any("previousEntity" in d for d in _details(_wf("{{previousEntity.status}}", on="created")))


def test_a_bare_field_of_the_changed_record_is_mended_before_the_checks():
    body = _wf("Case for {{guestName}} is {{status ?? \"open\"}}")
    result = AgentResult(task_id="t", agent="workflow",
                         proposals=[ArtifactProposal(section="workflows", natural_key="Hand-off", body=body)])
    said = ac.mend_mechanics(result, DOC)
    assert body["steps"][1]["config"]["message"] == 'Case for {{entity.guestName}} is {{entity.status ?? "open"}}'
    assert len([x for x in said if "changed record's" in x]) == 2
    ac.check_workflow_steps(result, DOC)        # nothing refused


def test_the_writer_is_told_how_a_record_change_process_reads_its_record():
    from services.blueprint.executors import NODE_TASKS
    assert any("{{entity.<field>}}" in str(v) for v in NODE_TASKS.values())
