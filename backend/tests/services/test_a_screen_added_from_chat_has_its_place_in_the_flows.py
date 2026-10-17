"""Mark 8 asked for a tax calculator (2026-10-17). Smith made the page, laid it
out, put it on the menu — and the App Flow view went on showing the app as it
was, because the flows are written once, at the build. Two faults from that
turn: the route the model named was the whole sentence (a page whose route WAS
the sentence was made, composed and then removed), and the new screen was never
placed in any flow."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.ids import page_key
from services.blueprint.service import BlueprintService
from services.smith import compose

SENTENCE = ("/tax — a new Indian income tax calculator screen: enter annual income (and optionally age group), "
            "choose the new or old tax regime, and see the tax payable")


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Mark 8", domain="tools")
    s.doc["roles"] = [{"id": "ROLE-001", "name": "Everyone"}]
    calc = s.upsert("pages", {"name": "Calculator", "route": "/", "pattern": "tool", "purpose": "Quick arithmetic.",
                              "primaryTasks": [], "entry": True}, natural_key=page_key("/"))
    s.doc["flows"] = [{"id": "JOURNEY-001", "name": "Compute a Calculation", "role": "ROLE-001", "goal": "A result",
                       "steps": [{"page": calc["id"], "does": "types a sum", "then": "menu"}], "ends": "The result shows."}]
    s.doc["navigation"] = {"style": "sidebar", "initialRoute": {"default": "/"}, "tree": [{"label": "Calculator", "page": calc["id"]}]}
    s.save()
    return s


def test_a_route_typed_as_a_sentence_is_the_path_and_the_sentence_is_the_ask():
    assert compose.split_route(SENTENCE) == ("/tax", "a new Indian income tax calculator screen: enter annual income (and optionally age group), choose the new or old tax regime, and see the tax payable")
    assert compose.split_route("/clients") == ("/clients", "")
    assert compose.split_route("add a /clients/[id] screen please") == ("/clients/[id]", "add a screen please")
    assert compose.split_route("clients") == ("clients", "")


def test_the_page_made_from_a_sentence_route_has_the_path_as_its_route(svc):
    page = compose._ensure_page(svc, SENTENCE, "can you add a page for tax calculation for Indian people")
    assert page["route"] == "/tax" and page["name"] == "Tax"
    assert "tax calculation for Indian people" in page["purpose"] and "annual income" in page["purpose"]
    # The same sentence again finds the same page: no second one.
    assert compose._ensure_page(svc, SENTENCE)["id"] == page["id"]
    assert [p["route"] for p in svc.doc["pages"]] == ["/", "/tax"]


def _executor(seen: list):
    """The build's executor, faked: a layout for the page node, a flow for the flows node."""
    def run(spec):
        seen.append(spec)
        if spec.node == "page_layouts":
            return AgentResult(task_id=spec.task_id, agent=spec.agent, proposals=[ArtifactProposal(
                section="pageLayouts", natural_key=spec.subject, body={"page": spec.subject, "root": {"type": "Stack", "props": {}, "children": []}})])
        if spec.node == "app_flows":
            assert "/tax" in (spec.brief or "") and "Return only the flows that are new or changed" in spec.brief
            return AgentResult(task_id=spec.task_id, agent=spec.agent, proposals=[ArtifactProposal(
                section="flows", natural_key="Work Out Income Tax",
                body={"name": "Work Out Income Tax", "role": "ROLE-001", "goal": "Tax payable",
                      "steps": [{"page": "PAGE-002", "does": "enters income and regime", "then": "menu"}], "ends": "The tax shows."})])
        return AgentResult(task_id=spec.task_id, agent=spec.agent, proposals=[])
    return run


def test_a_screen_added_from_chat_is_placed_in_the_flows(svc, monkeypatch):
    seen: list = []
    applied: list = []
    monkeypatch.setattr("services.smith.change.apply_change",
                        lambda s, request, **kw: applied.append((request, kw)) or SimpleNamespace(applied=True, committed=["x"], version=2))
    out = compose.compose_route(svc, SENTENCE, request="can you add a page for tax calculation", executor=_executor(seen))
    assert [sp.node for sp in seen] == ["page_layouts", "app_flows"]
    assert out.flows == ["Work Out Income Tax"]
    # The flows went through the same door every change does, with the flow proposals and no re-projection.
    layouts, flows = applied
    assert flows[1]["interpretation"] == "flows for /tax" and flows[1]["regenerate"] is False
    assert [p.section for p in flows[1]["proposals"]] == ["flows"]


def test_a_screen_that_already_existed_is_not_placed_again(svc, monkeypatch):
    seen: list = []
    monkeypatch.setattr("services.smith.change.apply_change",
                        lambda s, request, **kw: SimpleNamespace(applied=True, committed=[], version=2))
    out = compose.compose_route(svc, "/", request="lay the calculator out again", executor=_executor(seen))
    assert [sp.node for sp in seen] == ["page_layouts"]
    assert not getattr(out, "flows", None)


def test_the_tool_result_says_the_screen_was_placed(svc, monkeypatch):
    monkeypatch.setattr(compose, "compose_route",
                        lambda s, route, **kw: SimpleNamespace(applied=True, committed=["a"], version=3, flows=["Work Out Income Tax"]))
    out = compose.run(str(svc.output_dir), "compose_route", route="/tax", request="add a tax page")
    assert out["applied"] and "placed it in the app's flows: **Work Out Income Tax**" in out["diff_summary"]
