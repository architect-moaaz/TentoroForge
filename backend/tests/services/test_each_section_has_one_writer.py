"""Each Blueprint section has one writing node in the build DAG.

With two, an edit to what one wrote is undone by the other the next time it
runs. A section's owner is the one node that names it bare; anyone else
writes in it only a part the owner leaves to them by name.
"""
from __future__ import annotations

import json

from services.blueprint import brand_language
from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.orchestrator import (
    DAG, SETTLE, _n, levels, run, section_writers, write_overlaps,
)
from services.blueprint.service import BlueprintService


def _nodes(*nodes):
    return {n.key: n for n in nodes}


def test_no_two_nodes_in_the_dag_write_the_same_thing():
    assert write_overlaps(DAG) == []


def test_every_section_has_exactly_one_owner():
    for section, writers in section_writers(DAG).items():
        owners = [key for key, path in writers if path == section]
        assert len(owners) == 1, (section, writers)


def test_two_nodes_writing_a_whole_section_are_an_overlap():
    found = write_overlaps(_nodes(_n("a", "x", produces=("pages",)),
                                  _n("b", "x", produces=("pages",))))
    assert found == ["pages: a, b each write the whole section"]


def test_a_part_the_owner_did_not_leave_is_an_overlap():
    found = write_overlaps(_nodes(_n("a", "x", produces=("pages",)),
                                  _n("b", "x", produces=("pages/contract",))))
    assert found == ["pages/contract: b writes it, but a does not leave it to b"]


def test_a_part_left_to_one_node_and_written_by_another_is_an_overlap():
    found = write_overlaps(_nodes(
        _n("a", "x", produces=("pages",), delegates=(("pages/contract", "b"),)),
        _n("b", "x", produces=("pages/contract",)),
        _n("c", "x", produces=("pages/contract",))))
    assert "pages/contract: written by b, c" in found
    assert "pages/contract: c writes it, but a does not leave it to c" in found


def test_a_part_inside_another_part_is_an_overlap():
    found = write_overlaps(_nodes(
        _n("a", "x", produces=("pages",),
           delegates=(("pages/contract", "b"), ("pages/contract.states", "c"))),
        _n("b", "x", produces=("pages/contract",)),
        _n("c", "x", produces=("pages/contract.states",))))
    assert found == ["pages/contract and pages/contract.states overlap"]


def test_a_delegation_nobody_writes_is_reported():
    found = write_overlaps(_nodes(
        _n("a", "x", produces=("pages",), delegates=(("pages/contract", "b"),)),
        _n("b", "x")))
    assert found == ["a leaves pages/contract to b, which does not write it"]


def test_the_scheduler_sees_a_delegate_in_its_owners_section():
    """Resume, §72's impact and the observer think in whole sections."""
    assert DAG["page_details"].sections == {"pages"}
    assert DAG["entity_fields"].sections == {"data.entities"}
    assert DAG["imagery"].sections == {"designSystem"}


def test_the_design_languages_are_inputs_of_the_design_system_node():
    order = [k for lvl in levels() for k in lvl]
    assert "brand_design_system" not in DAG and "figma_design_system" not in DAG
    assert "design_system" in SETTLE
    assert {"design_system"} <= DAG["page_layouts"].depends_on
    assert order.index("design_system") < order.index("page_layouts")


def _design_answer(spec):
    return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.95, proposals=[
        ArtifactProposal(section="designSystem", natural_key="designSystem", body={
            "visualPersonality": "calm", "colors": {"primary": "#123456"},
            "accessibilityRules": ["contrast 4.5:1"]})])


def test_the_company_language_is_laid_over_the_agents_design_when_it_lands(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="A", domain="d")
    svc.doc.setdefault("application", {})["designLanguage"] = "company"
    svc.save()
    brand_language.adopt(tmp_path, design_md="# Acme", design={"colors": {"primary": "#ff0000"}},
                         company_name="Acme")
    report = run(svc, _design_answer, plan=["design_system"], commit=True)

    assert report.completed == ["design_system"]
    ds = json.loads(svc.current_path.read_text())["designSystem"]
    assert ds["colors"] == {"primary": "#ff0000"}          # the company's palette
    assert ds["accessibilityRules"] == ["contrast 4.5:1"]   # the agent's, which it does not state


def test_without_a_chosen_language_the_agents_design_stands(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="A", domain="d")
    brand_language.adopt(tmp_path, design_md="# Acme", design={"colors": {"primary": "#ff0000"}},
                         company_name="Acme")
    run(svc, _design_answer, plan=["design_system"], commit=True)
    assert svc.doc["designSystem"]["colors"] == {"primary": "#123456"}
