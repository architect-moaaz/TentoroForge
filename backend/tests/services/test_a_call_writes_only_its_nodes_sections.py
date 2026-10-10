"""A node's call writes the node's sections, and a declared screen names
its module.

Ecommerce1 (forge-v3, 2026-10-10): the build ran `app_flows` before any
page set existed, and the flows writer — a `page_design` agent, which may
write pages — declared 33 pages of its own, with no module, no contract
and no requirements. Nothing composed them. The §30 boundary is the
agent's; what one call may write is the node's.
"""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import (AgentResult, ArtifactProposal, OutsideTheNodesWork,
                                               PageWithoutAModule, check_node_sections, check_page_modules,
                                               node_sections)


def _result(node: str, *sections: str, agent: str = "page_design") -> AgentResult:
    return AgentResult(task_id=f"TASK-{node}", agent=agent, node=node,
                       proposals=[ArtifactProposal(section=s, natural_key=f"k-{i}", body={"name": s})
                                  for i, s in enumerate(sections)])


def test_a_call_may_write_what_its_node_produces_and_also_writes():
    assert node_sections("app_flows") == {"flows"}
    assert node_sections("page_contracts") == {"pages", "navigation"}
    assert node_sections("entity_fields") == {"data"}
    assert node_sections("page_details") == {"pages", "widgets"}
    assert node_sections("security") == {"security", "roles", "permissions"}
    check_node_sections(_result("page_contracts", "pages", "navigation"))
    check_node_sections(_result("entity_fields", "data.entities", "data.constraints", agent="data_model"))
    check_node_sections(_result("page_details", "pages", "widgets"))


def test_the_flows_writer_may_not_declare_pages():
    with pytest.raises(OutsideTheNodesWork, match="this call is `app_flows`, which writes flows; it may not write "
                                                  "'pages' — `page_contracts`, `page_details` writes 'pages'"):
        check_node_sections(_result("app_flows", "flows", "pages"))
    with pytest.raises(OutsideTheNodesWork, match="may not write 'navigation'"):
        check_node_sections(_result("app_flows", "navigation"))


def test_a_reply_with_no_node_or_a_service_node_is_held_by_its_agent_alone():
    r = _result("", "pages")
    check_node_sections(r)
    check_node_sections(_result("auth_pages", "pages"))
    check_node_sections(_result("not-a-node", "pages"))


def test_the_scheduler_stamps_the_node_on_every_reply_before_it_is_applied(tmp_path, monkeypatch):
    from services.blueprint import orchestrator
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="shop", name="Shop", domain="retail")
    svc.doc["pages"] = [{"id": "PAGE-001", "route": "/", "name": "Home", "pattern": "dashboard", "purpose": "home",
                         "states": [{"name": "empty"}]}]
    svc.save()
    monkeypatch.delitem(orchestrator.OBSERVER_ROUNDS_BY_NODE, "app_flows", raising=False)

    def author(spec):
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9, proposals=[
            ArtifactProposal(section="pages", natural_key="/shop", body={"route": "/shop", "name": "Shop",
                                                                         "pattern": "entity_list", "purpose": "x"}),
            ArtifactProposal(section="flows", natural_key="browse", body={"name": "Browse", "goal": "see", "steps": []})])
    report = orchestrator.run(svc, author, plan=["app_flows"], commit=True, max_attempts=1)
    assert "app_flows" in report.failed
    assert "this call is `app_flows`" in report.failed_because["app_flows"]
    assert [p["route"] for p in svc.doc["pages"]] == ["/"], "nothing of the refused reply landed"


def _pages(*bodies: dict) -> AgentResult:
    return AgentResult(task_id="TASK-page_contracts", agent="page_design", node="page_contracts",
                       proposals=[ArtifactProposal(section="pages", natural_key=b.get("route", ""), body=b)
                                  for b in bodies])


MODULED = {"modules": [{"id": "MODULE-001", "name": "Catalogue"}, {"id": "MODULE-002", "name": "Cart"}]}


def test_a_declared_screens_module_is_one_the_application_has():
    """A screen in no module is allowed (ecom v4's /account cost two
    five-minute page sets when it was not, 2026-10-10); a screen naming a
    module the application does not have is refused."""
    check_page_modules(_pages({"route": "/products", "module": "MODULE-001"}, {"route": "/account"},
                              {"route": "/login", "pattern": "auth"}), MODULED)
    with pytest.raises(PageWithoutAModule, match="MODULE-001 \\(Catalogue\\), MODULE-002 \\(Cart\\) — or left out") as exc:
        check_page_modules(_pages({"route": "/products", "module": "MODULE-001"}, {"route": "/cart"},
                                  {"route": "/orders", "module": "MODULE-009"}), MODULED)
    assert "/orders: `module` 'MODULE-009' is not one" in str(exc.value) and "/cart" not in str(exc.value)


def test_the_module_is_asked_of_the_declaration_only():
    bare = _pages({"route": "/cart"})
    check_page_modules(bare, {"modules": []}), "an application without modules"
    bare.node = "page_details"
    check_page_modules(bare, MODULED), "a contract edits a declared page; the module was decided"
    bare.node = ""
    check_page_modules(bare, MODULED), "Smith's seams declare pages their own way"


def test_the_prompt_lists_the_nodes_sections_not_the_agents(tmp_path):
    """Told it could write `product`, the requirements call did, was refused
    and paid an edit turn (Ecom L1, 2026-10-11): the prompt and the check
    must name the same sections."""
    from services.blueprint.executors import build_prompt, call_writes
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="shop", name="Shop", domain="retail")
    assert call_writes("requirements", "requirement") == ["requirements"]
    assert call_writes("application_model", "product_analysis") == ["product"]
    system, _ = build_prompt(svc.doc, "requirements")
    boundary = system.split("You may write ONLY")[1].split("If the")[0]
    assert "requirements" in boundary and "product" not in boundary
    assert '"product": {' not in system, "no shape for a section the call may not write"
