"""Journeys are written by the journeys step, once screens have ids. The
screens step was told it could write `flows`, wrote journeys through the
screens it was proposing by address, and every step was refused as "not a
screen" — the build failed (60v142ju, 2026-10-12)."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidAppFlow, check_flows
from services.blueprint.executors import build_prompt

DOC = {"application": {"name": "x"}, "pages": []}


def test_only_the_journeys_step_is_told_it_writes_journeys():
    assert "  - flows" not in build_prompt(DOC, "page_contracts")[0]
    assert "  - flows" not in build_prompt(DOC, "page_details")[0]
    assert "  - flows" in build_prompt(DOC, "app_flows")[0]


def test_journeys_beside_new_screens_are_refused_as_premature():
    res = AgentResult(task_id="T", agent="page_design", proposals=[
        ArtifactProposal(section="pages", natural_key="Form", body={"name": "Form", "route": "/"}),
        ArtifactProposal(section="flows", natural_key="Submit", body={"name": "Submit", "steps": [{"page": "/"}, {"page": "/done"}]})])
    with pytest.raises(InvalidAppFlow) as e:
        check_flows(res, {"pages": [{"id": "PAGE-001", "route": "/old"}]})
    assert "Leave `flows` out" in str(e.value)
