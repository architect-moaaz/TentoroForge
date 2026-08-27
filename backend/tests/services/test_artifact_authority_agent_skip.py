"""Test the LLM page-schema agent skips collections+records under P6 flags."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agents import page_schema_agent


class TestCollectionRecordSkip:
    def _run(self, coro):
        return asyncio.run(coro)

    def _plan(self):
        return {"description": "x", "entities": {}, "pages": []}

    def _stub_gen(self, calls):
        async def _fake(plan, page, slug, domain_ctx, output_dir=None):  # noqa: ARG001
            calls["n"] += 1
            return {"id": slug, "route": page.get("route", "/x"),
                    "root": {"type": "Stack"}}
        return _fake

    def test_collection_flag_on_skips_kanban(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        page = {"route": "/sessions", "type": "kanban", "name": "Sessions"}
        self._run(page_schema_agent.run_page_schema_agent(str(tmp_path), self._plan(), page))
        assert calls["n"] == 0

    def test_collection_flag_on_skips_calendar_cards_timeline(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        for kind in ("calendar", "cards", "timeline", "list"):
            page = {"route": f"/{kind}s", "type": kind}
            self._run(page_schema_agent.run_page_schema_agent(str(tmp_path), self._plan(), page))
        assert calls["n"] == 0

    def test_collection_flag_on_still_runs_form_page(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        # Collection flag should ONLY skip collection-typed pages, not form pages.
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        page = {"route": "/sessions/new", "type": "form"}
        self._run(page_schema_agent.run_page_schema_agent(str(tmp_path), self._plan(), page))
        assert calls["n"] == 1

    def test_record_flag_on_skips_form_detail_edit(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "1")
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        for kind in ("form", "detail", "edit", "create"):
            page = {"route": f"/x/{kind}", "type": kind}
            self._run(page_schema_agent.run_page_schema_agent(str(tmp_path), self._plan(), page))
        assert calls["n"] == 0

    def test_record_flag_on_still_runs_list_page(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "1")
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        page = {"route": "/sessions", "type": "list"}
        self._run(page_schema_agent.run_page_schema_agent(str(tmp_path), self._plan(), page))
        assert calls["n"] == 1

    def test_flags_off_run_all(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        # Regression guard for the whole authority stack. The dashboard flag
        # defaults ON now, so every authority is disabled explicitly — an
        # unset dashboard flag would skip that page and leave the count short.
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "0")
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        for kind in ("list", "kanban", "form", "detail", "dashboard", "custom"):
            page = {"route": f"/{kind}", "type": kind}
            self._run(page_schema_agent.run_page_schema_agent(str(tmp_path), self._plan(), page))
        assert calls["n"] == 6

    def test_archetype_fallback_works_for_collection(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        # planner may write archetype: kanban instead of type.
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        page = {"route": "/sessions", "archetype": "kanban"}
        self._run(page_schema_agent.run_page_schema_agent(str(tmp_path), self._plan(), page))
        assert calls["n"] == 0
