"""The domain reference — what a practitioner expects of such a product — is
written from the requirements before anything is modelled, is part of the
first review, and is declared end to end.

"Industry-standard and relevant to its domain and sub-domain" was a hope
nothing measured; now it is a section the model is held to and the finished
app is scored against (2026-10-11)."""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint import agent_contract, verification
from services.blueprint.orchestrator import DAG, is_foundational, levels
from services.blueprint.service import SINGLETON_SECTIONS
from services.smith.smith import DOMAIN_NODES, domain_nodes


def test_the_contract_carries_the_reference_and_where_artifacts_answer_it():
    schema = json.loads((Path(__file__).parents[2] / "contracts" / "blueprint.schema.json").read_text())
    ref = schema["properties"]["domainReference"]["properties"]
    assert set(ref) >= {"domain", "subdomain", "screens", "records", "processes", "rules", "integrations",
                        "conventions", "benchmarks", "sources", "declined"}
    assert ref["rules"]["items"]["properties"]["refusedCase"]
    assert ref["declined"]["items"]["required"] == ["kind", "name", "reason"] or \
        set(ref["declined"]["items"]["required"]) >= {"kind", "name", "reason"}
    for section in ("pages", "workflows", "businessRules", "integrations"):
        assert "reference" in schema["properties"][section]["items"]["properties"], section
    assert "reference" in schema["properties"]["data"]["properties"]["entities"]["items"]["properties"]


def test_the_section_is_registered_wherever_sections_are_known():
    assert "domainReference" in SINGLETON_SECTIONS
    assert "domainReference" in agent_contract.WRITABLE_SECTIONS
    assert agent_contract.capability_for("domain_intelligence").writes == {"domainReference"}
    assert "domainReference" in agent_contract.capability_for("smith").writes
    for agent in ("product_analysis", "solution_architecture", "data_model", "page_design", "workflow",
                  "business_rules", "security", "integration", "analytics"):
        assert "domainReference" in agent_contract.capability_for(agent).reads, agent
    assert verification.SECTION_OWNER["domainReference"] == "domain_intelligence"


def test_the_reference_node_runs_after_the_requirements_and_before_the_model():
    order = [k for lvl in levels() for k in lvl]
    assert order.index("requirements") < order.index("domain_reference") < order.index("application_model")
    assert DAG["domain_reference"].agent == "domain_intelligence"
    assert DAG["domain_reference"].produces == frozenset({"domainReference"})
    assert "domain_reference" in DAG["application_model"].depends_on
    assert is_foundational(DAG["domain_reference"])
    assert DOMAIN_NODES == ("requirements", "domain_reference")
    assert domain_nodes() == ["requirements", "domain_reference"]


def test_the_model_nodes_are_told_what_to_answer_and_how_to_decline():
    from services.blueprint.executors import REFERENCE_HOLD, reference_hold
    doc = {"domainReference": {"screens": [{"name": "Order book", "purpose": "every order"}],
                               "records": [{"name": "Invoice"}]}}
    held = reference_hold(doc, "page_contracts")
    assert "'Order book'" in held and "set `reference` on the page" in held
    assert '"kind": "screen"' in held and "change_request" in held
    assert "Invoice" in reference_hold(doc, "data_model")
    assert reference_hold(doc, "workflows") == ""              # no reference processes: nothing to hold to
    assert reference_hold({}, "page_contracts") == ""
    assert set(REFERENCE_HOLD) >= {"ux_architecture", "page_contracts", "data_model", "workflows",
                                   "business_rules", "security", "integrations"}
