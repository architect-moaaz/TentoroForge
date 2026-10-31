"""The LangGraph spine gives an agent app its agent.

The relay installed `plan.agent_graph` after its validator; the spine — the default
since the rebuild — had no such step, so an app whose plan carried an agent shipped
without one. `_install_app_agent` is that step: same install as the Agent Builder's
Apply, no model, never fatal.
"""
from __future__ import annotations

import json
import uuid

import pytest

import models  # noqa: F401  (register every model before test_db.create_all)

PLAN = {
    "name": "SnapApp",
    "agent_graph": {
        "name": "PriceScan",
        "system_prompt": {"prompt": "You identify products."},
        "tools": [{"name": "identify_product", "tool_type": "function",
                   "description": "identify the product in an image"}],
    },
}


async def _project(db):
    from models.org import Organization
    from models.project import Project

    org = Organization(id=uuid.uuid4(), name="O", slug=f"o-{uuid.uuid4().hex[:6]}")
    db.add(org)
    await db.flush()
    p = Project(id=uuid.uuid4(), org_id=org.id, name="P", owner_id=uuid.uuid4())
    db.add(p)
    await db.commit()
    return p


def _events(config_queue) -> list[str]:
    out = []
    while not config_queue.empty():
        evt = config_queue.get_nowait()
        data = evt.get("data")
        out.append(data if isinstance(data, str) else json.dumps(data))
    return out


def _config():
    import asyncio

    q: asyncio.Queue = asyncio.Queue()
    return q, {"configurable": {"emit_queue": q}}


@pytest.mark.asyncio
async def test_a_plan_with_an_agent_gets_the_runtime(tmp_path, test_db):
    from database import async_session
    from services.pipeline_graph import _install_app_agent

    async with async_session() as db:
        project = await _project(db)
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")  # the foundation has been laid by now
    q, config = _config()
    summary = await _install_app_agent(
        {"output_dir": str(tmp_path), "plan": PLAN, "project_id": str(project.id)}, config)

    assert summary and summary["name"] == "PriceScan"
    assert (tmp_path / "src" / "lib" / "agents" / "runtime.ts").is_file()
    cfg = next((tmp_path / "src" / "agents" / "definitions").glob("*.json"))
    tool = json.loads(cfg.read_text())["tools"][0]
    assert tool["kind"] == "ai_action" and tool["aiAction"] == "identify_product"
    log = " ".join(_events(q))
    assert "[Agent] installed 'PriceScan'" in log


@pytest.mark.asyncio
async def test_a_plan_without_an_agent_gets_nothing(tmp_path, test_db):
    from database import async_session
    from services.pipeline_graph import _install_app_agent

    async with async_session() as db:
        project = await _project(db)
    q, config = _config()
    out = await _install_app_agent(
        {"output_dir": str(tmp_path), "plan": {"name": "Plain"}, "project_id": str(project.id)}, config)
    assert out is None
    assert not (tmp_path / "src").exists()


@pytest.mark.asyncio
async def test_no_project_row_is_not_an_error(tmp_path, test_db):
    from services.pipeline_graph import _install_app_agent

    q, config = _config()
    assert await _install_app_agent({"output_dir": str(tmp_path), "plan": PLAN}, config) is None
    assert await _install_app_agent(
        {"output_dir": str(tmp_path), "plan": PLAN, "project_id": str(uuid.uuid4())}, config) is None
    assert not (tmp_path / "src").exists()


@pytest.mark.asyncio
async def test_a_failing_install_is_reported_and_never_raises(tmp_path, test_db, monkeypatch):
    from database import async_session
    from services import agent_from_plan
    from services.pipeline_graph import _install_app_agent

    async def boom(**_):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(agent_from_plan, "install_agent_from_plan", boom)
    async with async_session() as db:
        project = await _project(db)
    q, config = _config()
    out = await _install_app_agent(
        {"output_dir": str(tmp_path), "plan": PLAN, "project_id": str(project.id)}, config)
    assert out is None
    assert "install skipped: disk on fire" in " ".join(_events(q))
