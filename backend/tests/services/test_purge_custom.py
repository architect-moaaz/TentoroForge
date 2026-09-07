"""Test the Phase 6d purge-custom gate in page_schema_agent."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agents import page_schema_agent


class TestPurgeCustom:
    def _run(self, coro):
        return asyncio.run(coro)

    def _plan(self):
        return {"description": "x", "entities": {}, "pages": []}

    def _stub_gen(self, calls: dict):
        async def _fake(plan, page, slug, domain_ctx, output_dir=None):  # noqa: ARG001
            calls["n"] += 1
            return {"id": slug, "route": page.get("route", "/x"),
                    "root": {"type": "Stack"}}
        return _fake

    def test_flag_off_unknown_type_still_runs_llm(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        # Regression guard: legacy behaviour is preserved with the flag off.
        monkeypatch.delenv("FORGE_PURGE_CUSTOM", raising=False)
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        page = {"route": "/report", "type": "custom-report"}
        self._run(page_schema_agent.run_page_schema_agent(
            str(tmp_path), self._plan(), page,
        ))
        assert calls["n"] == 1

    def test_flag_on_unknown_type_rejected_and_stub_emitted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        monkeypatch.setenv("FORGE_PURGE_CUSTOM", "1")
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        page = {"route": "/report", "type": "custom-report"}
        self._run(page_schema_agent.run_page_schema_agent(
            str(tmp_path), self._plan(), page,
        ))
        # LLM never invoked.
        assert calls["n"] == 0
        # A minimal-schema stub landed on disk so the REVISE loop has
        # something to work with.
        target = tmp_path / "src" / "schemas" / "report.json"
        assert target.is_file()
        doc = json.loads(target.read_text(encoding="utf-8"))
        assert doc.get("id") == "report"

    def test_flag_on_known_page_types_still_run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        # The three artifact kinds still author normally (or hit their
        # own P3/P6 skip if their flag is on).
        monkeypatch.setenv("FORGE_PURGE_CUSTOM", "1")
        # Ensure no artifact flags fire. FORGE_DASHBOARD_AUTHORITY now
        # defaults ON, so unsetting it is no longer the same as disabling
        # it — the opt-out has to be explicit or the dashboard page is
        # skipped here and the call count comes up one short.
        for env in ("FORGE_DASHBOARD_AUTHORITY", "FORGE_COLLECTION_AUTHORITY",
                    "FORGE_RECORD_AUTHORITY"):
            monkeypatch.setenv(env, "0")
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        for kind in ("dashboard", "list", "kanban", "form", "detail", "edit"):
            page = {"route": f"/{kind}", "type": kind}
            self._run(page_schema_agent.run_page_schema_agent(
                str(tmp_path), self._plan(), page,
            ))
        assert calls["n"] == 6

    def test_flag_on_bespoke_true_still_runs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        # Bespoke escape hatch: plan.pages[*].bespoke=True lets a
        # non-standard type through the LLM path.
        monkeypatch.setenv("FORGE_PURGE_CUSTOM", "1")
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        page = {"route": "/onboarding", "type": "welcome", "bespoke": True}
        self._run(page_schema_agent.run_page_schema_agent(
            str(tmp_path), self._plan(), page,
        ))
        assert calls["n"] == 1

    def test_flag_on_bespoke_false_still_rejected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        # bespoke: false / missing is NOT an escape.
        monkeypatch.setenv("FORGE_PURGE_CUSTOM", "1")
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        for bespoke_val in (False, None, 0, ""):
            page = {"route": f"/x{id(bespoke_val)}", "type": "weird", "bespoke": bespoke_val}
            self._run(page_schema_agent.run_page_schema_agent(
                str(tmp_path), self._plan(), page,
            ))
        assert calls["n"] == 0

    def test_flag_on_archetype_field_also_honored(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        """The purge gate must read `archetype` as well as `type`.

        Collection and record authority now default ON, and they are checked
        BEFORE the purge gate — so a kanban page is claimed by the composer and
        the LLM is never reached. The test asked whether the LLM ran, and the
        answer became "no" for a reason that has nothing to do with archetype.

        Turning the collection authority off is what puts the page back in
        front of the gate this test is about.
        """
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")
        monkeypatch.setenv("FORGE_PURGE_CUSTOM", "1")
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        page = {"route": "/tasks", "archetype": "kanban"}
        self._run(page_schema_agent.run_page_schema_agent(
            str(tmp_path), self._plan(), page,
        ))
        assert calls["n"] == 1

    def test_collection_authority_claims_the_page_before_the_purge_gate(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        """With the authority on (the default) the composer owns a kanban page
        and the LLM is not called at all."""
        monkeypatch.delenv("FORGE_COLLECTION_AUTHORITY", raising=False)
        monkeypatch.setenv("FORGE_PURGE_CUSTOM", "1")
        calls = {"n": 0}
        monkeypatch.setattr(page_schema_agent, "_generate_schema_for_page", self._stub_gen(calls))
        self._run(page_schema_agent.run_page_schema_agent(
            str(tmp_path), self._plan(), {"route": "/tasks", "archetype": "kanban"},
        ))
        assert calls["n"] == 0


class TestPurgeCustomFlagHelper:
    def test_off_by_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("FORGE_PURGE_CUSTOM", raising=False)
        assert page_schema_agent._purge_custom_enabled() is False

    def test_truthy_values(self, monkeypatch: pytest.MonkeyPatch):
        for val in ("1", "true", "yes", "on", "TRUE", "YES"):
            monkeypatch.setenv("FORGE_PURGE_CUSTOM", val)
            assert page_schema_agent._purge_custom_enabled() is True, val

    def test_falsy_values(self, monkeypatch: pytest.MonkeyPatch):
        for val in ("0", "false", "no", "off", "", "  "):
            monkeypatch.setenv("FORGE_PURGE_CUSTOM", val)
            assert page_schema_agent._purge_custom_enabled() is False, val
