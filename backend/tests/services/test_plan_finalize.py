"""Tests for the shared plan-finalize helpers (domain reclassify + maquette gate).

Both hooks run in the standard and Figma pipelines, so drift here silently
diverges the two entry points. These tests pin the contract.
"""
from __future__ import annotations

import pytest

from services.plan_finalize import (
    reclassify_plan_domain,
    author_dashboard_maquette_if_enabled,
)


class TestReclassifyPlanDomain:
    def test_yoga_studio_reclassified_from_generic(self):
        plan = {"domain": "general", "description": "A yoga studio for booking classes."}
        before, after, changed = reclassify_plan_domain(plan)
        assert before == "general"
        assert after != "general"
        assert changed is True
        assert plan["domain"] == after

    def test_recruitment_reclassified_from_generic(self):
        plan = {
            "domain": "general",
            "description": "A recruitment platform for candidate applications with role-based approvals.",
        }
        before, after, changed = reclassify_plan_domain(plan)
        assert changed is True
        # HR bucket
        assert "human" in after.lower() or "hr" in after.lower()

    def test_non_generic_domain_preserved(self):
        # Planner picked something real — don't second-guess it.
        plan = {"domain": "Healthcare & Medical", "description": "medical charts"}
        _, after, changed = reclassify_plan_domain(plan)
        assert changed is False
        assert after == "Healthcare & Medical"
        assert plan["domain"] == "Healthcare & Medical"

    def test_empty_description_leaves_plan_unchanged(self):
        plan = {"domain": "general", "description": ""}
        before, after, changed = reclassify_plan_domain(plan)
        assert changed is False
        assert before == after == "general"
        assert plan["domain"] == "general"

    def test_missing_description_uses_brief(self):
        plan = {"domain": "general", "brief": "commerce marketplace for indie designers"}
        _, after, changed = reclassify_plan_domain(plan)
        # Should classify from brief when description missing.
        assert changed is True

    def test_explicit_description_arg_wins(self):
        plan = {"domain": "general", "description": "irrelevant"}
        _, after, _ = reclassify_plan_domain(
            plan, description="A yoga studio for booking classes."
        )
        # Uses the arg's text, not plan.description.
        assert after != "general"

    def test_non_dict_plan_returns_empty_tuple(self):
        assert reclassify_plan_domain("not a dict") == ("", "", False)  # type: ignore
        assert reclassify_plan_domain(None) == ("", "", False)  # type: ignore

    def test_all_generic_synonyms_reclassify(self):
        # `""`, `general`, `generic`, `other`, `misc`, `app` are all considered
        # "the planner didn't really pick anything" — try to do better.
        for generic in ("", "general", "generic", "other", "misc", "app", "GENERAL"):
            plan = {"domain": generic, "description": "A yoga studio for booking classes."}
            _, after, changed = reclassify_plan_domain(plan)
            assert changed is True, f"expected {generic!r} to be reclassified"

    def test_classifier_returning_generic_leaves_plan_alone(self, monkeypatch):
        # If _classify_domain returns something we'd also treat as generic,
        # don't stamp the plan with it (nothing gained, log churn).
        monkeypatch.setattr(
            "services.domain_context._classify_domain",
            lambda text_lower, description: "General",
        )
        plan = {"domain": "general", "description": "some words"}
        _, after, changed = reclassify_plan_domain(plan)
        assert changed is False
        assert plan["domain"] == "general"

    def test_classifier_exception_fails_closed(self, monkeypatch):
        def _boom(*_args, **_kwargs):
            raise RuntimeError("classifier down")

        monkeypatch.setattr("services.domain_context._classify_domain", _boom)
        plan = {"domain": "general", "description": "some words"}
        _, after, changed = reclassify_plan_domain(plan)
        assert changed is False
        assert plan["domain"] == "general"


class TestAuthorDashboardMaquetteIfEnabled:
    """Gate is now profile-only — no env override (deleted in Phase 0)."""

    @staticmethod
    def _write_profile(tmp_path, profile_id: str) -> None:
        """Persist a real profile to disk so load_profile() picks it up."""
        from services.generation_profile import get_profile, persist_profile
        prof = get_profile(profile_id)
        assert prof is not None, f"unknown profile: {profile_id}"
        persist_profile(str(tmp_path), prof)

    @pytest.mark.asyncio
    async def test_disabled_when_no_profile(self, tmp_path):
        # No profile.json → gate stays off.
        result = await author_dashboard_maquette_if_enabled(
            {"description": "yoga"}, str(tmp_path)
        )
        assert result is None
        # Contract file must NOT be written when gate is off.
        assert not (tmp_path / "src" / "contracts" / "dashboard-maquette.json").exists()

    @pytest.mark.asyncio
    async def test_non_dict_plan_returns_none(self, tmp_path):
        assert await author_dashboard_maquette_if_enabled("not a plan", str(tmp_path)) is None  # type: ignore

    @pytest.mark.asyncio
    async def test_profile_gate_enables_maquette(self, monkeypatch, tmp_path):
        # With Fast profile (require_kpi_row + require_primary_chart both True)
        # the gate opens. Maquette author returns None here → verify flag
        # honoured and no file written on None.
        self._write_profile(tmp_path, "fast")

        async def _stub(*_args, **_kwargs):
            return None

        monkeypatch.setattr(
            "services.dashboard_maquette.author_dashboard_maquette", _stub
        )
        result = await author_dashboard_maquette_if_enabled(
            {"description": "yoga"}, str(tmp_path)
        )
        assert result is None
        assert not (tmp_path / "src" / "contracts" / "dashboard-maquette.json").exists()

    @pytest.mark.asyncio
    async def test_writes_contract_when_maquette_returned(self, monkeypatch, tmp_path):
        self._write_profile(tmp_path, "fast")

        class _FakeMaq:
            def to_dict(self):
                return {"kpis": [{"label": "Bookings"}], "primary_chart": None}

        async def _stub(*_args, **_kwargs):
            return _FakeMaq()

        monkeypatch.setattr(
            "services.dashboard_maquette.author_dashboard_maquette", _stub
        )
        result = await author_dashboard_maquette_if_enabled(
            {"description": "yoga"}, str(tmp_path)
        )
        assert result == {"kpis": [{"label": "Bookings"}], "primary_chart": None}
        written = tmp_path / "src" / "contracts" / "dashboard-maquette.json"
        assert written.is_file()

    @pytest.mark.asyncio
    async def test_maquette_exception_fails_closed(self, monkeypatch, tmp_path):
        self._write_profile(tmp_path, "fast")

        async def _boom(*_args, **_kwargs):
            raise RuntimeError("LLM down")

        monkeypatch.setattr(
            "services.dashboard_maquette.author_dashboard_maquette", _boom
        )
        result = await author_dashboard_maquette_if_enabled(
            {"description": "yoga"}, str(tmp_path)
        )
        assert result is None
