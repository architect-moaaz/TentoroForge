"""An agent's tools are checked against what the app will allow (services/agent_access.py).

The Movie Review agent was given tools that create a rating and a comment directly.
The app lets nobody write those tables through its data API — the SubmitRating and
PostComment workflows do it — so every chat attempt was a 403. These tests pin the
fix: a write tool on a closed entity becomes the app's own workflow, or is removed,
and everything else is left alone.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.agent_access import read_entity_access, read_workflows, reconcile_agent
from tests.services.test_agent_runtime_install import (
    by_name, graph, make_app, node, tool,
)
from services.agent_runtime_config import compile_agent
from services.agent_runtime_install import install_agent_runtime

ACCESS_TS = """// Generated from the Living Blueprint. Edit the Blueprint, not this file.
export const ENTITY_ACCESS: Record<string, { read: string[]; write: string[] }> = {
  "movies": { "read": ["Admin", "Reviewer"], "write": ["Admin", "Reviewer"] },
  "ratings": { "read": ["Admin", "Reviewer"], "write": [] },
  "comments": { "read": ["Admin", "Reviewer"], "write": [] },
  "tickets": { "read": ["Admin"], "write": [] }
};
"""


def workflow(wid: str, name: str, table: str, actions: list[str], required: list[str], records=()) -> dict:
    nodes = [{"id": f"n{i}", "type": "action", "data": {"config": {"actionType": a, "table": table}}}
             for i, a in enumerate(actions)]
    return {"id": wid, "name": name, "blueprintId": "FLOW-X", "recordInputs": list(records),
            "requiredInputs": required, "processVariables": [], "definition": {"nodes": nodes, "edges": []}}


def lay_down(app: Path) -> None:
    (app / "src" / "lib").mkdir(parents=True, exist_ok=True)
    (app / "src" / "lib" / "entity-access.ts").write_text(ACCESS_TS, encoding="utf-8")
    d = app / "src" / "lib" / "workflows" / "definitions"
    d.mkdir(parents=True, exist_ok=True)
    (d / "submit-rating.json").write_text(json.dumps(workflow(
        "submit-rating", "SubmitRating", "ratings", ["db_query", "db_insert", "db_update"],
        ["movie", "stars"], [{"name": "movie", "table": "movies"}])), encoding="utf-8")
    (d / "post-comment.json").write_text(json.dumps(workflow(
        "post-comment", "PostComment", "comments", ["db_query", "db_insert"],
        ["movie", "body"], [{"name": "movie", "table": "movies"}])), encoding="utf-8")


def cfg_with(*tools):
    return compile_agent(graph(node("sp", "system_prompt", "P", {"prompt": "You help."}), *tools)).config


def data_tool(nid, name, entity, op):
    return tool(nid, name, tool_type="data_engine", entity=entity, operation=op)


def test_the_access_list_and_workflows_are_read_from_the_app(tmp_path):
    _, app = make_app(tmp_path)
    lay_down(app)
    access = read_entity_access(app)
    assert access["ratings"]["write"] == [] and access["movies"]["write"] == ["Admin", "Reviewer"]
    wfs = {w["id"]: w for w in read_workflows(app)}
    assert wfs["submit-rating"]["writes"] == {"ratings": {"db_insert", "db_update"}}  # a read is not a write
    assert [i["name"] for i in wfs["submit-rating"]["inputs"]] == ["movie", "stars"]
    assert wfs["submit-rating"]["inputs"][0]["kind"] == "record"


def test_a_write_to_a_closed_entity_becomes_the_apps_own_workflow(tmp_path):
    _, app = make_app(tmp_path)
    lay_down(app)
    cfg = cfg_with(data_tool("t1", "rate_movie", "ratings", "create"),
                   data_tool("t2", "add_comment", "comments", "create"),
                   data_tool("t3", "list_movies", "movies", "list"),
                   data_tool("t4", "add_movie", "movies", "create"))
    notes = reconcile_agent(cfg, app)
    rate, comment = by_name(cfg, "rate_movie"), by_name(cfg, "add_comment")
    assert rate["kind"] == "workflow" and rate["workflowId"] == "submit-rating"
    assert "entity" not in rate and "operation" not in rate
    assert set(rate["inputSchema"]["properties"]) == {"movie", "stars"}
    assert rate["inputSchema"]["properties"]["movie"]["type"] == "object"
    assert comment["workflowId"] == "post-comment"
    assert len(notes) == 2 and all("does not allow anyone" in n for n in notes)
    # an entity the app does let people write, and a read, are untouched
    assert by_name(cfg, "list_movies")["kind"] == "data"
    assert by_name(cfg, "add_movie")["kind"] == "data" and by_name(cfg, "add_movie")["operation"] == "create"


def test_a_closed_entity_with_no_workflow_loses_the_tool_and_the_prompt_says_so(tmp_path):
    _, app = make_app(tmp_path)
    lay_down(app)
    cfg = cfg_with(data_tool("t1", "open_ticket", "tickets", "create"),
                   data_tool("t2", "list_movies", "movies", "list"))
    notes = reconcile_agent(cfg, app)
    assert [t["name"] for t in cfg["tools"]] == ["list_movies"]
    assert "was removed" in notes[0]
    assert "cannot do these in this app: create tickets" in cfg["systemPrompt"]


def test_reading_a_closed_entity_is_not_a_problem(tmp_path):
    _, app = make_app(tmp_path)
    lay_down(app)
    cfg = cfg_with(data_tool("t1", "list_tickets", "tickets", "list"))
    assert reconcile_agent(cfg, app) == []
    assert by_name(cfg, "list_tickets")["kind"] == "data"


def test_an_app_with_no_access_list_is_left_exactly_as_compiled(tmp_path):
    _, app = make_app(tmp_path)
    cfg = cfg_with(data_tool("t1", "rate_movie", "ratings", "create"))
    before = json.dumps(cfg, sort_keys=True)
    assert reconcile_agent(cfg, app) == []
    assert json.dumps(cfg, sort_keys=True) == before


def test_an_unreadable_access_file_gives_no_opinion(tmp_path):
    _, app = make_app(tmp_path)
    (app / "src" / "lib").mkdir(parents=True, exist_ok=True)
    (app / "src" / "lib" / "entity-access.ts").write_text("export const ENTITY_ACCESS = { not json", encoding="utf-8")
    assert read_entity_access(app) == {}


def test_install_applies_it_and_reports_it(tmp_path):
    project, app = make_app(tmp_path)
    lay_down(app)
    g = graph(node("sp", "system_prompt", "P", {"prompt": "You help."}),
              data_tool("t1", "rate_movie", "ratings", "create"))
    r = install_agent_runtime(project, graphs=[g])
    installed = json.loads((app / "src" / "agents" / "definitions" / "support.json").read_text())
    assert installed["tools"][0]["kind"] == "workflow" and installed["tools"][0]["workflowId"] == "submit-rating"
    assert any("submit-rating" in w or "SubmitRating" in w for w in r["agents"][0]["warnings"])
    # the builder's own graph is untouched: the project stays the source of truth
    saved = json.loads((project / "agent-definitions" / "support.json").read_text())
    assert saved["nodes"][1]["data"]["config"]["tool_type"] == "data_engine"
