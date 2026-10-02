"""A refusal the workflow-step author can actually answer.

UAT, 2026-09-18, a 46-page dental app: Book Appointment's step read
`{{endTime}}`, the reference check said "declare 'endTime' as an input", the
author did — and `pin_workflow_identity` put every declared field back from
the declaration, `inputs` included, so the input was thrown away, the same
refusal came back, and after two the author was not asked again. The app's
central workflow shipped with no steps. The same build's `composition` filled
exactly 32,000 output tokens four times and never produced a sketch.
"""
import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidWorkflowStep, check_workflow_steps,
)
from services.blueprint.executors import (
    _declared_plus_added, pin_workflow_identity,
)
from services.blueprint.service import BlueprintService

DECLARED = [{"name": "startTime", "kind": "field", "type": "timestamp", "required": True}]


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Dental", domain="health")
    s.doc["workflows"] = [{"id": "FLOW-005", "name": "Book Appointment", "status": "ACTIVE",
                           "trigger": {"kind": "manual"}, "inputs": list(DECLARED)}]
    return s


def _authored(inputs):
    return AgentResult(task_id="T", agent="workflow", proposals=[ArtifactProposal(
        section="workflows", natural_key="whatever the model chose",
        body={"name": "Book Appointment", "inputs": inputs, "steps": [
            {"key": "insert_appointment", "type": "action", "config": {
                "actionType": "db_insert", "table": "appointments",
                "values": {"startTime": "{{startTime}}", "endTime": "{{endTime}}"}}}]})])


def test_an_input_the_author_adds_survives_the_pin(svc):
    result = _authored(DECLARED + [{"name": "endTime", "kind": "field", "type": "timestamp"}])
    pin_workflow_identity(svc, "FLOW-005", result)
    names = [i["name"] for i in result.proposals[0].body["inputs"]]
    assert names == ["startTime", "endTime"], "declared first, the addition kept"


def test_the_refusal_is_answerable_once_the_input_survives(svc):
    """The exact refusal from the dental build, before and after the author
    does what it says."""
    without = _authored(DECLARED)
    pin_workflow_identity(svc, "FLOW-005", without)
    with pytest.raises(InvalidWorkflowStep, match="endTime"):
        check_workflow_steps(without, svc.doc)

    answered = _authored(DECLARED + [{"name": "endTime", "kind": "field", "type": "timestamp"}])
    pin_workflow_identity(svc, "FLOW-005", answered)
    check_workflow_steps(answered, svc.doc)          # no refusal now


def test_a_declared_input_cannot_be_changed_or_dropped():
    """Pages were designed against the declaration."""
    merged = _declared_plus_added(
        DECLARED, [{"name": "startTime", "type": "text", "required": False}])
    assert merged == DECLARED
    assert _declared_plus_added(DECLARED, []) == DECLARED

