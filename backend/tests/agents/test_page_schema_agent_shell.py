"""Regression tests for the page_schema_agent's shell-aware code path.

These tests guard the two bugs that left a generated project with shell.json
but zero page schemas:

  1. `_generate_schema_for_page` referenced `output_dir` without taking it
     as a parameter — every page-schema call raised NameError, the per-page
     loop's try/except swallowed it, and registry.ts ended up with only
     `/shell` as an entry.

  2. `slugify_route` raised ValueError on Express-style `:id` segments —
     planners that emit `/users/:id` (a common pattern) made the agent
     unable to compute a file path before the prompt was even built.

Approach: mock `_collect_llm_text` so the real LLM is not invoked, but
every other code path — prompt construction, shell.json detection,
filename resolution, file write — runs for real.
"""
from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agents.page_schema_agent import (
    _generate_schema_for_page,
    run_page_schema_agent,
)


_FAKE_SCHEMA_JSON = json.dumps({
    "schemaVersion": "2",
    "id": "test",
    "route": "/test",
    "layout": "main",
    "root": {"type": "Stack", "id": "r", "children": []},
})


def _patch_llm():
    """Patch the LLM-text fetch to return a fixed schema JSON."""
    return patch(
        "agents.page_schema_agent._collect_llm_text",
        new=AsyncMock(return_value=_FAKE_SCHEMA_JSON),
    )


# ── Bug 1: NameError on output_dir ─────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_schema_for_page_does_not_raise_nameerror_on_output_dir(tmp_path):
    """`_generate_schema_for_page` must accept output_dir as a kwarg.

    Before the fix, the function referenced `output_dir` in its shell-check
    block but the parameter wasn't declared — every call raised NameError.
    """
    with _patch_llm():
        result = await _generate_schema_for_page(
            plan={"entities": {}},
            page={"route": "/tasks", "type": "list", "name": "Tasks"},
            slug="tasks",
            domain_context=None,
            output_dir=str(tmp_path),
        )
    assert result is not None
    assert "schemaVersion" in result


@pytest.mark.asyncio
async def test_generate_schema_for_page_works_without_output_dir(tmp_path):
    """When output_dir is None, the shell-check is a no-op — function still
    completes (used by unit tests that don't need a real output dir)."""
    with _patch_llm():
        result = await _generate_schema_for_page(
            plan={"entities": {}},
            page={"route": "/tasks", "type": "list", "name": "Tasks"},
            slug="tasks",
            domain_context=None,
            output_dir=None,
        )
    assert result is not None


@pytest.mark.asyncio
async def test_run_page_schema_agent_writes_schema_file_for_simple_page(tmp_path):
    """End-to-end: run_page_schema_agent should write a schema file under
    src/schemas/. This is the path the per-page loop in
    run_schema_frontend_pipeline takes for every page.
    """
    with _patch_llm():
        await run_page_schema_agent(
            output_dir=str(tmp_path),
            plan={"entities": {}},
            page={"route": "/tasks", "type": "list", "name": "Tasks"},
        )
    written = tmp_path / "src" / "schemas" / "tasks.json"
    assert written.exists(), f"page schema not written at {written}"
    schema = json.loads(written.read_text(encoding="utf-8"))
    assert schema["id"] == "tasks"


# ── Bug 2: slugify_route raised ValueError on `:id` ─────────────────────

@pytest.mark.asyncio
async def test_run_page_schema_agent_handles_colon_param_route(tmp_path):
    """Routes with Express-style `:id` segments must not crash the agent.

    Before the fix, slugify_route('/users/:id') raised ValueError because
    the colon was not in the safe-segment regex. The agent caller swallowed
    the exception, leaving NO schema written for any parameterised page.
    """
    with _patch_llm():
        await run_page_schema_agent(
            output_dir=str(tmp_path),
            plan={"entities": {}},
            page={"route": "/users/:id", "type": "detail", "name": "User Detail"},
        )
    # slugify_route normalises :id → [id], so the file lands at users/[id].json
    written = tmp_path / "src" / "schemas" / "users" / "[id].json"
    assert written.exists(), f"page schema not written at {written}"


@pytest.mark.asyncio
async def test_run_page_schema_agent_handles_bracket_param_route(tmp_path):
    """Routes already in Next.js bracket convention work too (regression
    guard against the colon-fix accidentally breaking the bracket form)."""
    with _patch_llm():
        await run_page_schema_agent(
            output_dir=str(tmp_path),
            plan={"entities": {}},
            page={"route": "/users/[id]", "type": "detail", "name": "User Detail"},
        )
    written = tmp_path / "src" / "schemas" / "users" / "[id].json"
    assert written.exists()


# ── Shell-aware prompt augmentation ─────────────────────────────────────

@pytest.mark.asyncio
async def test_shell_context_added_to_prompt_when_shell_json_exists(tmp_path):
    """When shell.json is present in output_dir AND page is not auth, the
    agent prompt should include the 'this page renders INSIDE a shared app
    shell' instruction so the LLM emits content-only output.
    """
    # Pre-seed shell.json so the agent's existence check passes
    schemas_dir = tmp_path / "src" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "shell.json").write_text(json.dumps({"schemaVersion": "2", "children": []}), encoding="utf-8")

    with patch(
        "agents.page_schema_agent._collect_llm_text",
        new=AsyncMock(return_value=_FAKE_SCHEMA_JSON),
    ) as mock_llm:
        await _generate_schema_for_page(
            plan={"entities": {}},
            page={"route": "/tasks", "type": "list", "name": "Tasks"},
            slug="tasks",
            domain_context=None,
            output_dir=str(tmp_path),
        )
    # Inspect the prompt the LLM saw
    sent_prompt = mock_llm.call_args[0][0]
    assert "App shell context" in sent_prompt, (
        "Expected shell-aware instruction in prompt; not found.\n"
        f"prompt tail: ...{sent_prompt[-400:]}"
    )


@pytest.mark.asyncio
async def test_shell_context_NOT_added_for_auth_pages(tmp_path):
    """Auth pages render bare (no shell wrapper) — the shell-context block
    must NOT be appended to their prompt even if shell.json exists.
    """
    schemas_dir = tmp_path / "src" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "shell.json").write_text(json.dumps({"schemaVersion": "2", "children": []}), encoding="utf-8")

    with patch(
        "agents.page_schema_agent._collect_llm_text",
        new=AsyncMock(return_value=_FAKE_SCHEMA_JSON),
    ) as mock_llm:
        await _generate_schema_for_page(
            plan={"entities": {}},
            page={"route": "/login", "type": "auth", "name": "Login"},
            slug="login",
            domain_context=None,
            output_dir=str(tmp_path),
        )
    sent_prompt = mock_llm.call_args[0][0]
    assert "App shell context" not in sent_prompt, (
        "Auth pages should not get the shell-context block."
    )


@pytest.mark.asyncio
async def test_shell_context_NOT_added_when_shell_json_missing(tmp_path):
    """If shell.json doesn't exist (project didn't run the shell phase),
    the prompt should not pretend a shell will wrap the page."""
    with patch(
        "agents.page_schema_agent._collect_llm_text",
        new=AsyncMock(return_value=_FAKE_SCHEMA_JSON),
    ) as mock_llm:
        await _generate_schema_for_page(
            plan={"entities": {}},
            page={"route": "/tasks", "type": "list", "name": "Tasks"},
            slug="tasks",
            domain_context=None,
            output_dir=str(tmp_path),
        )
    sent_prompt = mock_llm.call_args[0][0]
    assert "App shell context" not in sent_prompt


# ── Consistency: nav-flow path matches where agent writes ───────────────

def test_nav_flow_schema_path_matches_agent_write_path():
    """nav_flow_from_plan declares a schemaFile path; the agent must write
    its output to the SAME path. Otherwise the editor's "open page" action
    looks for a file that doesn't exist.

    Covers simple routes, nested routes, root, and parameterised routes in
    both `:id` (Express) and `[id]` (Next.js bracket) conventions — all
    must agree across nav_flow_from_plan and slugify_route.
    """
    from services.nav_flow_from_plan import nav_flow_from_plan
    from services.route_slug import slugify_route

    plan = {"pages": [
        {"id": "home",     "route": "/",                  "name": "Home",     "type": "dashboard"},
        {"id": "tasks",    "route": "/tasks",             "name": "Tasks",    "type": "list"},
        {"id": "tasks-new", "route": "/tasks/new",        "name": "New",      "type": "form"},
        # Parameterised — colon convention from planner
        {"id": "leave-requests-:id", "route": "/leave-requests/:id", "name": "Leave Detail", "type": "detail"},
        # Parameterised — bracket convention
        {"id": "users", "route": "/users/[id]", "name": "User Detail", "type": "detail"},
    ]}
    nf = nav_flow_from_plan(plan)
    for page in nf["pages"]:
        nav_path = page["schemaFile"]
        agent_slug = slugify_route(page["route"])
        agent_path = f"src/schemas/{agent_slug}.json"
        assert nav_path == agent_path, (
            f"Mismatch for route {page['route']!r}:\n"
            f"  nav-flow says: {nav_path}\n"
            f"  agent writes:  {agent_path}\n"
            "Editor will get 'No schema at ...' when opening this page."
        )
