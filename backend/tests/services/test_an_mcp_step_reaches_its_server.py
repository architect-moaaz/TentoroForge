"""SnapIT (forge-v3 ho6irnp6), 2026-09-28: "FireCrawl MCP: search, crawl,
extract: mcp_tool_call: no server matched (id= name=)".

The step author was told an MCP step needs only a tool name, so it named no
server, invented `firecrawl_search_and_extract` and put its inputs beside the
step instead of under `args`. Nothing wrote the organisation's servers into a
Blueprint app, the org-wide rewrite wrote them beside the app rather than in
it, and a publish never carried them.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from services.blueprint import mcp_catalog
from services.blueprint.agent_contract import (AgentResult, ArtifactProposal, InvalidWorkflowStep,
                                               check_workflow_steps)
from services.catalog import workflow_nodes

FIRECRAWL = [{"name": "Firecrawl", "tools": [
    mcp_catalog.tool_entry("firecrawl_search", "Search the web and return results.",
                           {"properties": {"query": {}, "limit": {}, "location": {}}, "required": ["query"]}),
    mcp_catalog.tool_entry("firecrawl_scrape", "Scrape one page.",
                           {"properties": {"url": {}, "formats": {}}, "required": ["url"]}),
]}]


def _step(config: dict) -> dict:
    return {"key": "search_firecrawl", "type": "action", "config": {"actionType": "mcp_tool_call", **config}}


SNAPIT_STEP = _step({"mcp_tool_name": "firecrawl_search_and_extract", "queries": "{{plan.output}}",
                     "maxPages": 50, "timeoutMs": 15000})
GOOD_STEP = _step({"mcp_server_name": "Firecrawl", "mcp_tool_name": "firecrawl_search",
                   "args": {"query": "{{plan.output}}", "limit": 10}})


# ── The step, held to what the server offers ────────────────────────────────

def test_snapits_step_is_refused_for_every_reason_it_failed():
    errors = " | ".join(mcp_catalog.step_errors(SNAPIT_STEP, FIRECRAWL))
    assert "the tool's inputs go in `config.args`" in errors and "maxPages, queries" in errors
    assert "`config.mcp_server_name` is None; the servers this application can call are: Firecrawl" in errors


def test_an_invented_tool_is_named_with_the_real_ones():
    step = _step({"mcp_server_name": "Firecrawl", "mcp_tool_name": "firecrawl_search_and_extract", "args": {}})
    assert mcp_catalog.step_errors(step, FIRECRAWL) == [
        "search_firecrawl: Firecrawl has no tool 'firecrawl_search_and_extract'; its tools are: "
        "firecrawl_search, firecrawl_scrape"]


def test_a_required_input_and_an_unknown_one_are_said():
    step = _step({"mcp_server_name": "Firecrawl", "mcp_tool_name": "firecrawl_search", "args": {"queries": "x"}})
    errors = mcp_catalog.step_errors(step, FIRECRAWL)
    assert any("requires query in `config.args`" in e for e in errors)
    assert any("takes no queries" in e for e in errors)


def test_a_right_step_passes():
    assert mcp_catalog.step_errors(GOOD_STEP, FIRECRAWL) == []


def test_an_organisation_without_a_server_is_told_to_do_it_another_way():
    assert "no MCP server connected" in mcp_catalog.step_errors(GOOD_STEP, [])[0]


def test_never_refreshed_still_holds_the_shape():
    """No catalogue read here yet: the server and `args` are still required."""
    assert mcp_catalog.step_errors(GOOD_STEP, None) == []
    errors = mcp_catalog.step_errors(SNAPIT_STEP, None)
    assert any("config.args" in e for e in errors) and any("name the server" in e for e in errors)


def test_the_catalog_requires_a_server():
    missing = workflow_nodes().missing("action", {"actionType": "mcp_tool_call", "mcp_tool_name": "x"})
    assert missing == ["mcp_server_name|mcp_server_id"]


def test_the_contract_refuses_the_step():
    body = {"name": "Identify Product From Text", "trigger": {"kind": "manual"},
            "steps": [{"key": "trigger", "type": "trigger", "name": "Start", "next": ["search_firecrawl"],
                       "config": {"type": "manual"}},
                      {**SNAPIT_STEP, "name": "Search", "next": []}]}
    result = AgentResult(task_id="t", agent="workflow_steps", proposals=[
        ArtifactProposal(section="workflows", natural_key="Identify Product From Text", body=body)])
    with pytest.raises(InvalidWorkflowStep) as e:
        check_workflow_steps(result, {"data": {"entities": []}}, FIRECRAWL)
    assert "the servers this application can call are: Firecrawl" in str(e.value)
    assert "the tool's inputs go in `config.args`" in str(e.value)


# ── The author is shown what exists ─────────────────────────────────────────

def test_the_author_is_shown_the_servers_and_their_tools():
    block = mcp_catalog.prompt_block(FIRECRAWL)
    assert "`mcp_server_name`" in block and "`args`" in block
    assert "firecrawl_search — Search the web and return results. (required: query; inputs: limit, location, query)" in block
    assert "no MCP server connected" in mcp_catalog.prompt_block([])
    assert mcp_catalog.prompt_block(None) == ""


def test_the_step_prompt_carries_the_catalogue(tmp_path):
    from services.blueprint.executors import _workflow_steps_prompt
    mcp_catalog.write(tmp_path, FIRECRAWL)
    system, _ = _workflow_steps_prompt({"workflows": [{"id": "FLOW-001", "name": "Search"}]}, "", "FLOW-001", "",
                                       output_dir=tmp_path)
    assert "MCP TOOLS" in system and "firecrawl_scrape" in system


def test_the_catalogue_has_no_address_or_key(tmp_path):
    mcp_catalog.write(tmp_path, FIRECRAWL)
    text = (tmp_path / mcp_catalog.PATH).read_text()
    assert "http" not in text and "fc-" not in text
    assert mcp_catalog.load(tmp_path) == json.loads(text)["servers"]


def test_a_refresh_reads_each_server_and_keeps_one_that_is_down(tmp_path, monkeypatch):
    rows = [SimpleNamespace(name="Firecrawl"), SimpleNamespace(name="Down")]

    class _Result:
        def scalars(self):
            return SimpleNamespace(all=lambda: rows)

    class _Db:
        async def execute(self, _q):
            return _Result()

    async def list_tools(row):
        if row.name == "Down":
            raise RuntimeError("timeout")
        return [SimpleNamespace(name="firecrawl_search", description="Search.",
                                input_schema={"properties": {"query": {}}, "required": ["query"]})]
    monkeypatch.setattr("services.mcp_client.list_tools", list_tools)
    servers = asyncio.run(mcp_catalog.refresh(tmp_path, "org", _Db()))
    assert servers[0]["tools"][0]["required"] == ["query"]
    assert servers[1]["tools"] is None and "timeout" in servers[1]["unreachable"]


# ── The app is given its servers, where it reads them ──────────────────────

def test_a_blueprint_apps_settings_are_written_in_the_app(tmp_path):
    from services.env_writer import app_env_dir
    assert app_env_dir(tmp_path) == tmp_path                      # an old-pipeline app is its own root
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text("{}")
    assert app_env_dir(tmp_path) == tmp_path / "app"


def test_each_enabled_server_becomes_the_apps_settings():
    import uuid
    from services.env_writer import mcp_env
    sid = uuid.UUID("b2c2e135-e8f2-4ae4-af3b-c763e9c0b914")
    env = mcp_env([SimpleNamespace(id=sid, server_url="https://mcp.example/x", transport="http",
                                   auth_kind="none", name="Firecrawl", enabled=True,
                                   auth_secret_ct=None, auth_secret_iv=None, auth_header_name=None),
                   SimpleNamespace(id=uuid.uuid4(), enabled=False)])
    assert env == {"MCP_SERVER_B2C2E135E8F2_URL": "https://mcp.example/x",
                   "MCP_SERVER_B2C2E135E8F2_TRANSPORT": "http",
                   "MCP_SERVER_B2C2E135E8F2_AUTH_KIND": "none",
                   "MCP_SERVER_B2C2E135E8F2_NAME": "Firecrawl"}


def test_a_turn_reads_the_servers_in(tmp_path, monkeypatch):
    import importlib
    router = importlib.import_module("routers.blueprint_generate")
    seen = []

    async def refresh(out, org, db):
        seen.append(("catalogue", out))
        return []

    async def write_env(out, org, db):
        seen.append(("settings", out))
    monkeypatch.setattr("services.blueprint.mcp_catalog.refresh", refresh)
    monkeypatch.setattr("services.env_writer.write_env_local_from_platform", write_env)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text("{}")
    asyncio.run(router._adopt_mcp_servers(tmp_path, SimpleNamespace(org_id="org"), None))
    assert seen == [("catalogue", tmp_path), ("settings", tmp_path)]
