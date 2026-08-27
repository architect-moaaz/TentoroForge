"""Test the LLM page-schema agent skips dashboards under the P3 authority flag."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agents import page_schema_agent


class TestDashboardSkip:
    def _run(self, coro):
        return asyncio.run(coro)

    def _minimal_plan(self):
        return {"description": "x", "entities": {}, "pages": []}

    def test_flag_off_still_runs_llm_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        # Regression guard: with the flag OFF the agent should NOT short-circuit
        # on a dashboard-typed page. We verify by patching the LLM entry-point
        # and asserting it gets called.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")  # explicit opt-out — the flag now defaults ON
        calls = {"n": 0}

        async def _fake_gen(plan, page, slug, domain_ctx, output_dir=None):  # noqa: ARG001
            calls["n"] += 1
            return {"id": slug, "route": "/dashboard", "root": {"type": "Stack"}}

        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", _fake_gen)
        # is_route_recipe_owned should return False in this test environment.
        page = {"route": "/dashboard", "type": "dashboard", "name": "Dashboard"}
        self._run(page_schema_agent.run_page_schema_agent(
            str(tmp_path), self._minimal_plan(), page,
        ))
        assert calls["n"] == 1

    def test_flag_on_dashboard_page_short_circuits(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        calls = {"n": 0}

        async def _fake_gen(plan, page, slug, domain_ctx, output_dir=None):  # noqa: ARG001
            calls["n"] += 1
            return {"id": slug, "route": "/dashboard", "root": {"type": "Stack"}}

        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", _fake_gen)
        page = {"route": "/dashboard", "type": "dashboard", "name": "Dashboard"}
        self._run(page_schema_agent.run_page_schema_agent(
            str(tmp_path), self._minimal_plan(), page,
        ))
        # LLM NOT invoked and no schema file written — composer is the authority.
        assert calls["n"] == 0
        assert not (tmp_path / "src" / "schemas" / "dashboard.json").is_file()

    def test_flag_on_unowned_page_still_runs_llm(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        # The dashboard flag must not over-reach. ``list`` is no longer a
        # valid probe — collection authority claims it — so opt the other
        # artifacts out and assert the dashboard flag alone leaves it alone.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "0")
        calls = {"n": 0}

        async def _fake_gen(plan, page, slug, domain_ctx, output_dir=None):  # noqa: ARG001
            calls["n"] += 1
            return {"id": slug, "route": "/notes", "root": {"type": "Stack"}}

        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", _fake_gen)
        page = {"route": "/notes", "type": "list", "name": "Notes"}
        self._run(page_schema_agent.run_page_schema_agent(
            str(tmp_path), self._minimal_plan(), page,
        ))
        assert calls["n"] == 1

    def test_archetype_dashboard_also_skipped(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        # Some planners emit `archetype` instead of `type`.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
        calls = {"n": 0}

        async def _fake_gen(plan, page, slug, domain_ctx, output_dir=None):  # noqa: ARG001
            calls["n"] += 1
            return {"id": slug, "route": "/x", "root": {"type": "Stack"}}

        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", _fake_gen)
        page = {"route": "/dashboard", "archetype": "dashboard", "name": "Dashboard"}
        self._run(page_schema_agent.run_page_schema_agent(
            str(tmp_path), self._minimal_plan(), page,
        ))
        assert calls["n"] == 0
