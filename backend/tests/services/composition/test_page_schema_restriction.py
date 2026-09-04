"""S6 tests — page-schema-agent restriction on recipe-owned routes.

Covers:
    1. recipe_owned_routes(): pure helper.
    2. is_route_recipe_owned(): thin predicate.
    3. run_page_schema_agent(): defence-in-depth — the LLM path bails
       out early when the route is recipe-owned so the recipe page
       written by schema_pipeline can't be silently overwritten.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from services.composition import pipeline_hook


def _write_brief(tmp_path: Path, recipes: dict[str, str]) -> None:
    (tmp_path / "contracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "contracts" / "brief.json").write_text(
        json.dumps({"page_recipes": recipes})
    )


# ────────────────────────────────────────────────────────────
# recipe_owned_routes
# ────────────────────────────────────────────────────────────

class TestRecipeOwnedRoutes:
    def test_flag_off_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FORGE_COMPOSITION_RECIPES", raising=False)
        _write_brief(tmp_path, {"/home": "member_home"})
        assert pipeline_hook.recipe_owned_routes(tmp_path) == set()

    def test_no_brief_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        assert pipeline_hook.recipe_owned_routes(tmp_path) == set()

    def test_v1_recipe_included(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/home": "member_home", "/x": "member_home"})
        got = pipeline_hook.recipe_owned_routes(tmp_path)
        assert got == {"/home", "/x"}

    def test_recipe_with_no_v1_anchors_excluded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        # operator_console has no v1 anchors — it should NOT be considered
        # owned, so the LLM path stays authoritative for it.
        _write_brief(tmp_path, {
            "/home": "member_home",     # v1 → owned
            "/ops": "citizen_service", # no v1 → not owned
        })
        assert pipeline_hook.recipe_owned_routes(tmp_path) == {"/home"}

    def test_unknown_recipe_excluded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {
            "/home": "member_home",
            "/junk": "does_not_exist",
        })
        assert pipeline_hook.recipe_owned_routes(tmp_path) == {"/home"}


class TestIsRouteRecipeOwned:
    def test_positive(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/home": "member_home"})
        assert pipeline_hook.is_route_recipe_owned("/home", tmp_path) is True

    def test_negative_unowned(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/home": "member_home"})
        assert pipeline_hook.is_route_recipe_owned("/other", tmp_path) is False

    def test_negative_flag_off(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FORGE_COMPOSITION_RECIPES", raising=False)
        _write_brief(tmp_path, {"/home": "member_home"})
        assert pipeline_hook.is_route_recipe_owned("/home", tmp_path) is False

    def test_empty_route(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/home": "member_home"})
        assert pipeline_hook.is_route_recipe_owned("", tmp_path) is False


# ────────────────────────────────────────────────────────────
# run_page_schema_agent short-circuit
# ────────────────────────────────────────────────────────────

class TestPageSchemaAgentSkip:
    def test_recipe_owned_route_skips_llm(self, tmp_path, monkeypatch):
        """When the route is recipe-owned, the LLM generator is NOT called
        and no schema file is written by the LLM path."""
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/home": "member_home"})

        from agents.page_schema_agent import run_page_schema_agent

        # If _generate_schema_for_page runs we'd see it in the mock — but the
        # skip should fire first and return without touching it.
        with patch(
            "agents.page_schema_agent._generate_schema_for_page",
        ) as mock_gen:
            asyncio.run(run_page_schema_agent(
                output_dir=str(tmp_path),
                plan={"entities": {}},
                page={"route": "/home", "type": "dashboard"},
            ))
        mock_gen.assert_not_called()

    def test_unowned_route_still_runs_llm(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        # Same reason the sibling test below disables the dashboard authority:
        # this is about recipe ownership, and the page under test is a `list`,
        # which the collection authority — also default ON, also checked before
        # the recipe path — claims for its composer. The LLM then does not run
        # for a reason that has nothing to do with recipes.
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")
        _write_brief(tmp_path, {"/home": "member_home"})

        from agents.page_schema_agent import run_page_schema_agent

        async def _fake_gen(*args, **kwargs):
            return {"schemaVersion": "2", "root": {"type": "Stack", "children": []}}

        with patch(
            "agents.page_schema_agent._generate_schema_for_page",
            side_effect=_fake_gen,
        ) as mock_gen:
            asyncio.run(run_page_schema_agent(
                output_dir=str(tmp_path),
                plan={"entities": {}},
                page={"route": "/other", "type": "list"},
            ))
        mock_gen.assert_called_once()

    def test_flag_off_never_skips(self, tmp_path, monkeypatch):
        """Even with page_recipes on disk, flag off = LLM path runs as usual."""
        monkeypatch.delenv("FORGE_COMPOSITION_RECIPES", raising=False)
        # This test is about the recipes flag, not the dashboard authority —
        # and that one now defaults ON, which would skip the dashboard page
        # under test for an unrelated reason. Disable it explicitly.
        monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")
        _write_brief(tmp_path, {"/home": "member_home"})

        from agents.page_schema_agent import run_page_schema_agent

        async def _fake_gen(*args, **kwargs):
            return {"schemaVersion": "2", "root": {"type": "Stack", "children": []}}

        with patch(
            "agents.page_schema_agent._generate_schema_for_page",
            side_effect=_fake_gen,
        ) as mock_gen:
            asyncio.run(run_page_schema_agent(
                output_dir=str(tmp_path),
                plan={"entities": {}},
                page={"route": "/home", "type": "dashboard"},
            ))
        mock_gen.assert_called_once()


# ────────────────────────────────────────────────────────────
# filter_pages_owned_by_recipes — planner-level filter
# ────────────────────────────────────────────────────────────

class TestFilterPagesOwnedByRecipes:
    def test_flag_off_returns_input_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FORGE_COMPOSITION_RECIPES", raising=False)
        _write_brief(tmp_path, {"/home": "member_home"})
        pages = [{"route": "/home"}, {"route": "/settings"}]
        kept, skipped = pipeline_hook.filter_pages_owned_by_recipes(pages, tmp_path)
        assert kept == pages
        assert skipped == []

    def test_flag_on_partitions_owned_vs_not(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/home": "member_home", "/shop": "shopper_home"})
        pages = [
            {"route": "/home", "type": "dashboard"},
            {"route": "/settings", "type": "settings"},
            {"route": "/shop", "type": "dashboard"},
            {"route": "/about", "type": "static"},
        ]
        kept, skipped = pipeline_hook.filter_pages_owned_by_recipes(pages, tmp_path)
        kept_routes = [p["route"] for p in kept]
        assert kept_routes == ["/settings", "/about"]
        assert sorted(skipped) == ["/home", "/shop"]

    def test_empty_pages_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        kept, skipped = pipeline_hook.filter_pages_owned_by_recipes([], tmp_path)
        assert kept == []
        assert skipped == []

    def test_non_v1_recipe_page_stays_in_llm_worklist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/console": "citizen_service"})  # no v1 anchors
        pages = [{"route": "/console"}]
        kept, skipped = pipeline_hook.filter_pages_owned_by_recipes(pages, tmp_path)
        assert kept == pages
        assert skipped == []

    def test_malformed_page_entries_stay_in_worklist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/home": "member_home"})
        pages = [{"route": "/home"}, "not-a-dict", {"noroute": True}]
        kept, skipped = pipeline_hook.filter_pages_owned_by_recipes(pages, tmp_path)
        assert "not-a-dict" in kept
        assert {"noroute": True} in kept
        assert skipped == ["/home"]
