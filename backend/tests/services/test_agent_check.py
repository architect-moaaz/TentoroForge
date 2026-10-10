"""The builder says what is wrong with an agent before Apply (services/agent_check.py).

Each finding is pinned to the box it is about, in plain words, with a severity: error (will not work),
warning (works differently or in part), info (worth knowing). Checks against the app are skipped when
there is no built app, and the answer says so.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from services.agent_check import MANY_TOOLS, check_agent
from tests.services.test_agent_access_reconcile import data_tool, lay_down
from tests.services.test_agent_runtime_install import graph, make_app, node, tool

PROMPT = node("sp", "system_prompt", "Prompt", {"prompt": "You help.", "is_entry_point": True})


def by_code(result: dict, code: str) -> list[dict]:
    return [f for f in result["findings"] if f["code"] == code]


def clean_app(tmp_path):
    _, app = make_app(tmp_path)
    lay_down(app)
    (app / ".env.local").write_text("ANTHROPIC_API_KEY=sk-ant-test\n", encoding="utf-8")
    return app


def test_a_sound_agent_has_nothing_to_report(tmp_path):
    app = clean_app(tmp_path)
    g = graph(PROMPT, data_tool("t1", "list_movies", "movies", "list"),
              tool("t2", "submit_rating", tool_type="workflow", workflow_id="submit-rating"))
    r = check_agent(g, app)
    assert r["findings"] == [] and r["appChecked"] is True


def test_a_tool_with_no_code_is_pinned_to_its_box(tmp_path):
    g = graph(PROMPT, tool("tool_x", "recommend_similar", tool_type="function"))
    f = by_code(check_agent(g), "tool_unimplemented")
    assert len(f) == 1 and f[0]["nodeId"] == "tool_x" and f[0]["severity"] == "warning"
    assert "recommend_similar" in f[0]["message"]


def test_a_tool_that_cannot_be_built_is_an_error_on_its_box():
    g = graph(PROMPT, tool("tool_y", "orphan", tool_type="data_engine", operation="list"))  # no entity
    f = by_code(check_agent(g), "tool_dropped")
    assert len(f) == 1 and f[0]["severity"] == "error" and f[0]["nodeId"] == "tool_y"


def test_names_are_matched_even_when_two_boxes_share_one():
    g = graph(PROMPT, tool("a", "lookup", tool_type="function"), tool("b", "lookup", tool_type="function"))
    nodes = {f["nodeId"] for f in by_code(check_agent(g), "tool_unimplemented")}
    assert nodes == {"a", "b"}, "the second 'lookup' is compiled as lookup_2 and still points at its own box"


def test_a_router_says_it_does_nothing_yet():
    r = check_agent(graph(PROMPT, node("r", "router", "Route", {"strategy": "intent_classification"})))
    router = by_code(r, "router_not_running")[0]
    assert router["nodeId"] == "r" and router["severity"] == "info"
    assert not by_code(r, "compile"), "the compiler's generic line is not said a second time"


def test_a_missing_prompt_points_at_the_prompt_box():
    g = graph(node("sp", "system_prompt", "Prompt", {"prompt": "", "is_entry_point": True}))
    f = by_code(check_agent(g), "no_system_prompt")
    assert f and f[0]["nodeId"] == "sp" and f[0]["severity"] == "warning"


def test_an_agent_with_no_tools_can_only_chat():
    f = by_code(check_agent(graph(PROMPT)), "no_tools")
    assert len(f) == 1 and f[0]["nodeId"] == "sp"


def test_too_many_tools_is_a_warning():
    many = [tool(f"t{i}", f"fn_{i}", tool_type="function", code="return 1;") for i in range(MANY_TOOLS + 1)]
    f = by_code(check_agent(graph(PROMPT, *many)), "many_tools")
    assert len(f) == 1 and str(MANY_TOOLS + 1) in f[0]["message"]
    few = [tool(f"t{i}", f"fn_{i}", tool_type="function", code="return 1;") for i in range(MANY_TOOLS)]
    assert not by_code(check_agent(graph(PROMPT, *few)), "many_tools")


def test_a_direct_write_the_app_refuses_is_flagged_with_what_apply_will_do(tmp_path):
    app = clean_app(tmp_path)
    g = graph(PROMPT, data_tool("rate", "rate_movie", "ratings", "create"),
              data_tool("tk", "open_ticket", "tickets", "create"))
    r = check_agent(g, app)
    swapped = by_code(r, "write_refused_swapped")[0]
    removed = by_code(r, "write_refused_removed")[0]
    assert swapped["nodeId"] == "rate" and swapped["severity"] == "warning" and "SubmitRating" in swapped["message"]
    assert removed["nodeId"] == "tk" and removed["severity"] == "error"


def test_a_tool_for_a_workflow_the_app_does_not_have_is_an_error(tmp_path):
    app = clean_app(tmp_path)
    g = graph(PROMPT, tool("w", "refund", tool_type="workflow", workflow_id="refund-flow"))
    f = by_code(check_agent(g, app), "unknown_workflow")
    assert len(f) == 1 and f[0]["severity"] == "error" and f[0]["nodeId"] == "w" and "refund-flow" in f[0]["message"]


def test_a_tool_for_a_table_the_app_does_not_have_is_an_error(tmp_path):
    app = clean_app(tmp_path)
    g = graph(PROMPT, data_tool("t", "list_invoices", "invoices", "list"))
    f = by_code(check_agent(g, app), "unknown_table")
    assert len(f) == 1 and f[0]["nodeId"] == "t" and "invoices" in f[0]["message"]


def test_without_a_built_app_the_app_checks_are_skipped_and_it_says_so(tmp_path):
    g = graph(PROMPT, tool("w", "refund", tool_type="workflow", workflow_id="refund-flow"),
              data_tool("t", "list_invoices", "invoices", "list"))
    r = check_agent(g, tmp_path / "no-app-here")
    assert r["appChecked"] is False
    assert not by_code(r, "unknown_workflow") and not by_code(r, "unknown_table") and not by_code(r, "no_ai_key")


def test_a_missing_ai_key_is_a_warning_and_a_present_one_is_not(tmp_path):
    _, app = make_app(tmp_path)
    lay_down(app)
    g = graph(PROMPT, data_tool("t1", "list_movies", "movies", "list"))
    f = by_code(check_agent(g, app), "no_ai_key")
    assert len(f) == 1 and f[0]["severity"] == "warning" and f[0]["nodeId"] == "sp"
    (app / ".env.local").write_text("ANTHROPIC_API_KEY=sk-ant-test\n", encoding="utf-8")
    assert not by_code(check_agent(g, app), "no_ai_key")
    (app / ".env.local").write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")
    assert by_code(check_agent(g, app), "no_ai_key"), "an empty key is no key"


def test_findings_come_errors_first():
    g = graph(PROMPT, tool("a", "orphan", tool_type="data_engine", operation="list"),
              tool("b", "stub", tool_type="function"), node("r", "router", "R", {}))
    order = [f["severity"] for f in check_agent(g)["findings"]]
    assert order == sorted(order, key=["error", "warning", "info"].index) and order[0] == "error" and order[-1] == "info"


def test_checking_never_changes_the_graph(tmp_path):
    app = clean_app(tmp_path)
    g = graph(PROMPT, data_tool("rate", "rate_movie", "ratings", "create"))
    before = json.dumps(g, sort_keys=True)
    check_agent(g, app)
    assert json.dumps(g, sort_keys=True) == before


@pytest.mark.asyncio
async def test_the_endpoint_checks_the_graph_it_is_given_and_saves_nothing(tmp_path, monkeypatch):
    from routers.agent_builder import check_agent_definition
    from schemas.agent_builder import AgentDefinitionSave

    project, app = make_app(tmp_path)
    lay_down(app)
    proj = SimpleNamespace(id=uuid.uuid4(), output_dir=str(project))

    async def fake_get(project_id, user, db):
        return proj

    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", fake_get)
    g = graph(PROMPT, tool("tool_x", "recommend_similar", tool_type="function"))
    out = await check_agent_definition(proj.id, AgentDefinitionSave(**g), SimpleNamespace(id="u"), None)
    assert out["appChecked"] is True and by_code(out, "tool_unimplemented")[0]["nodeId"] == "tool_x"
    assert not (project / "agent-definitions").exists(), "a check is not a save"


def handoff_box(**cfg):
    return node("h", "human_handoff", "Hand over", {"handlers": {"roles": ["Admin"]}, **cfg})


def test_a_handoff_that_names_no_one_is_a_warning_on_its_box():
    f = by_code(check_agent(graph(PROMPT, node("h", "human_handoff", "Hand over", {}))), "handoff_no_handlers")
    assert len(f) == 1 and f[0]["nodeId"] == "h" and f[0]["severity"] == "warning" and "nobody is notified" in f[0]["message"]


def test_a_sound_handoff_has_nothing_to_report(tmp_path):
    app = clean_app(tmp_path)
    r = check_agent(graph(PROMPT, data_tool("t1", "list_movies", "movies", "list"), handoff_box()), app)
    assert [f for f in r["findings"] if f["code"].startswith("handoff_")] == []


def test_a_handoff_assignment_that_cannot_work_says_so():
    f = by_code(check_agent(graph(PROMPT, handoff_box(assignment="owner"))), "handoff_assignment")
    assert len(f) == 1 and f[0]["nodeId"] == "h" and "queue" in f[0]["message"]


def test_a_handoff_role_the_app_does_not_have_is_an_error(tmp_path):
    app = clean_app(tmp_path)
    g = graph(PROMPT, node("h", "human_handoff", "Hand over", {"handlers": {"roles": ["Admin", "Janitor"]}}))
    f = by_code(check_agent(g, app), "handoff_unknown_role")
    assert len(f) == 1 and f[0]["severity"] == "error" and "Janitor" in f[0]["message"] and f[0]["nodeId"] == "h"


def test_email_for_handoffs_is_optional_and_a_missing_setup_is_only_a_warning(tmp_path):
    _, app = make_app(tmp_path)
    lay_down(app)
    (app / ".env.local").write_text("ANTHROPIC_API_KEY=sk-ant-test\n", encoding="utf-8")
    g = graph(PROMPT, handoff_box(notify={"email": True}))
    f = by_code(check_agent(g, app), "handoff_email_not_set_up")
    assert len(f) == 1 and f[0]["severity"] == "warning" and "Handoffs still work" in f[0]["message"]
    (app / ".env.local").write_text("ANTHROPIC_API_KEY=sk-ant-test\nSMTP_HOST=smtp.example.test\n", encoding="utf-8")
    assert not by_code(check_agent(g, app), "handoff_email_not_set_up")
    (app / ".env.local").write_text("ANTHROPIC_API_KEY=sk-ant-test\n", encoding="utf-8")
    assert not by_code(check_agent(graph(PROMPT, handoff_box(notify={"email": False})), app), "handoff_email_not_set_up")
