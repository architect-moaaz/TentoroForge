"""Integration-lite: install_agent_from_plan writes the AgentDefinition
file at the expected location AND installs the fixed agent runtime compiled
from it — with no model call at all.

The install is deterministic (services.agent_runtime_install), so these tests
need no patching: they run the real thing against a temp directory and read what
it wrote.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

# Register every model on Base.metadata before test_db.create_all.
import models  # noqa: F401  (side-effect import)


@pytest.mark.asyncio
async def test_install_writes_agent_definition_file(tmp_path, test_db):
    """Full path: JSON file lands under agent-definitions/ with the right shape,
    the runtime is installed from it, and the summary reflects the graph."""
    from services.agent_from_plan import install_agent_from_plan
    from database import async_session
    from models.org import Organization

    output_dir = tmp_path / "app"
    output_dir.mkdir()
    (output_dir / "package.json").write_text("{}", encoding="utf-8")  # a built app

    plan = {
        "name": "TestApp",
        "agent_graph": {
            "name": "TestAgent",
            "description": "Two-tool agent for the install test.",
            "system_prompt": {"prompt": "You are a test agent.",
                              "model": "claude-sonnet-4-5"},
            "tools": [
                {"name": "hello",   "tool_type": "function",
                 "description": "say hi"},
                {"name": "goodbye", "tool_type": "function",
                 "description": "say bye"},
            ],
        },
    }

    async with async_session() as db:
        # Seed a minimal org so foreign keys don't break — the service
        # itself only reads platform_mcp_servers scoped to org_id, so we
        # don't need a user/project row here.
        org = Organization(id=uuid.uuid4(), name="O", slug=f"o-{uuid.uuid4().hex[:6]}")
        db.add(org)
        await db.flush()
        org_id = org.id

        summary = await install_agent_from_plan(
            output_dir=str(output_dir),
            plan=plan,
            org_id=org_id,
            db=db,
        )

    # Summary correctness.
    assert summary is not None
    assert summary["name"] == "TestAgent"
    assert summary["tool_count"] == 2
    assert summary["node_count"] == 3  # system_prompt + 2 tools

    # File landed.
    defs_dir = output_dir / "agent-definitions"
    files = list(defs_dir.glob("*.json"))
    assert len(files) == 1, f"expected 1 agent JSON, got {[f.name for f in files]}"
    assert files[0].stem == summary["agent_id"]

    # File contents match the AgentDefinition envelope shape.
    data = json.loads(files[0].read_text())
    assert set(data.keys()) >= {"id", "name", "description", "nodes", "edges"}
    assert data["name"] == "TestAgent"
    node_types = sorted(n["data"]["nodeType"] for n in data["nodes"])
    assert node_types == ["system_prompt", "tool", "tool"]
    # Edges are wired: sp → t1 → t2
    assert len(data["edges"]) == 2

    # The runtime was installed from the definition — compiled, not generated.
    cfg = json.loads((output_dir / "src" / "agents" / "definitions" / f"{summary['agent_id']}.json").read_text())
    assert cfg["name"] == "TestAgent"
    assert cfg["systemPrompt"] == "You are a test agent."
    assert [t["name"] for t in cfg["tools"]] == ["hello", "goodbye"]
    assert (output_dir / "src" / "lib" / "agents" / "runtime.ts").is_file()
    assert (output_dir / "src" / "app" / "api" / "agent" / "chat" / "route.ts").is_file()
    # Tools that were only described say so rather than pretending.
    assert any("no code" in w for w in summary["warnings"])


@pytest.mark.asyncio
async def test_install_returns_none_and_writes_nothing_without_agent_graph(
    tmp_path, test_db,
):
    """No agent_graph in the plan → service is a no-op (no file, no
    runtime, returns None)."""
    from services.agent_from_plan import install_agent_from_plan
    from database import async_session
    from models.org import Organization

    output_dir = tmp_path / "app"
    output_dir.mkdir()
    (output_dir / "package.json").write_text("{}", encoding="utf-8")  # a built app

    async with async_session() as db:
        org = Organization(id=uuid.uuid4(), name="O2", slug=f"o-{uuid.uuid4().hex[:6]}")
        db.add(org)
        await db.flush()
        org_id = org.id

        summary = await install_agent_from_plan(
            output_dir=str(output_dir),
            plan={"name": "PlainApp"},  # no agent_graph
            org_id=org_id,
            db=db,
        )

    assert summary is None
    assert not (output_dir / "src" / "lib" / "agents").exists()
    assert not (output_dir / "agent-definitions").exists() or not list(
        (output_dir / "agent-definitions").glob("*.json")
    )


@pytest.mark.asyncio
async def test_install_is_idempotent_on_rerun(tmp_path, test_db):
    """Re-running with the same plan overwrites the same JSON file
    (agent_id is UUIDv5 of plan.name + agent.name) — no orphaned copies."""
    from services.agent_from_plan import install_agent_from_plan
    from database import async_session
    from models.org import Organization

    output_dir = tmp_path / "app"
    output_dir.mkdir()
    (output_dir / "package.json").write_text("{}", encoding="utf-8")  # a built app

    plan = {
        "name": "IdApp",
        "agent_graph": {
            "name": "IdAgent",
            "system_prompt": {"prompt": "..."},
            "tools": [{"name": "t", "tool_type": "function"}],
        },
    }

    async with async_session() as db:
        org = Organization(id=uuid.uuid4(), name="O3", slug=f"o-{uuid.uuid4().hex[:6]}")
        db.add(org)
        await db.flush()
        org_id = org.id

        s1 = await install_agent_from_plan(
            output_dir=str(output_dir), plan=plan, org_id=org_id, db=db,
        )
        s2 = await install_agent_from_plan(
            output_dir=str(output_dir), plan=plan, org_id=org_id, db=db,
        )

    assert s1["agent_id"] == s2["agent_id"]
    files = list((output_dir / "agent-definitions").glob("*.json"))
    assert len(files) == 1
    defs = list((output_dir / "src" / "agents" / "definitions").glob("*.json"))
    assert len(defs) == 1
