"""An agent naming a section it may not write is refused, not fatal.

UAT, 2026-09-18: `product_analysis` proposed the section
`product.capabilities` — a field inside a section it MAY write — and
`result.validate()` raised ContractViolation from a path that caught five
other refusal types and not that one. The whole turn died with a traceback
where one subject should have been asked again. The same shape took a build
down on 2026-09-06 (InvalidBusinessRule) and the fix then was this list.
"""
import json

import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, ContractViolation,
)
from services.blueprint.executors import make_executor
from services.blueprint.orchestrator import run
from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="a",
                                name="Clinic", domain="health")
    s.doc["requirements"] = [{"id": "REQ-001", "description": "Reception registers patients."}]
    s.save()
    return s


def test_the_refusal_names_the_section_that_does_exist():
    result = AgentResult(task_id="T", agent="product_analysis", proposals=[
        ArtifactProposal(section="product.capabilities", natural_key="CAP:nav",
                         body={"name": "Main Navigation"})])
    with pytest.raises(ContractViolation) as refused:
        result.validate()
    assert "write 'product'" in str(refused.value), "a retry needs the right answer"
    assert "'capabilities' inside its body" in str(refused.value)


def test_a_section_nobody_owns_is_told_what_may_be_written():
    result = AgentResult(task_id="T", agent="product_analysis", proposals=[
        ArtifactProposal(section="invented", natural_key="k", body={})])
    with pytest.raises(ContractViolation) as refused:
        result.validate()
    assert "the writable sections are:" in str(refused.value)
    assert "product" in str(refused.value)


def test_the_run_asks_again_instead_of_dying(svc):
    """The defect itself: the build survives and the node still lands."""
    calls = []

    def model(*, system, user, schema=None):
        calls.append(user)
        section = "product.capabilities" if len(calls) == 1 else "product"
        return json.dumps({
            "proposals": [{"section": section, "natural_key": "PRODUCT",
                           "body": json.dumps({"capabilities": [
                               {"name": "Register a patient"}]})}],
            "confidence": 0.9, "assumptions": [], "issues": [], "change_requests": []})

    report = run(svc, make_executor(svc, model), plan=["application_model"])

    assert len(calls) == 2, "the bad section was retried, not fatal"
    assert "application_model" in report.completed
    assert "product.capabilities" in calls[1], "the retry is told what was refused"
    assert (svc.doc.get("product") or {}).get("capabilities")
