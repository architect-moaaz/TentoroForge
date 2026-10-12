"""The requirement agent's reply on an application with no requirements
must state at least one. One reply carried only the product summary, the
step reported success, and Smith told the person "0 requirements"
(6ysfw182, 2026-10-12). Now it is refused and the author asked again."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, AuthorRefusal, NoRequirements, check_requirements

PRODUCT = ArtifactProposal(section="product", natural_key="product", body={"objectives": ["x"]})
REQ = ArtifactProposal(section="requirements", natural_key="REQ-submit", body={"title": "Submit", "description": "d"})


def _result(*proposals, agent="requirement"):
    return AgentResult(task_id="T", agent=agent, proposals=list(proposals))


def test_a_product_with_no_requirements_is_refused_and_retried():
    with pytest.raises(NoRequirements) as e:
        check_requirements(_result(PRODUCT), {})
    assert isinstance(e.value, AuthorRefusal) and "requirements" in str(e.value)


def test_a_reply_with_requirements_or_an_app_that_has_them_passes():
    check_requirements(_result(PRODUCT, REQ), {})
    check_requirements(_result(PRODUCT), {"requirements": [{"id": "REQ-001", "status": "APPROVED"}]})
    check_requirements(_result(PRODUCT, agent="product_analysis"), {})


def test_only_retired_requirements_count_as_none():
    with pytest.raises(NoRequirements):
        check_requirements(_result(PRODUCT), {"requirements": [{"id": "REQ-001", "status": "REMOVED"}]})
