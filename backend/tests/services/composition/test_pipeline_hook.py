"""Slice 5 tests — pipeline_hook is off by default and only fires when
FORGE_COMPOSITION_RECIPES is on AND a matching recipe is in the brief."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.composition import pipeline_hook


# ────────────────────────────────────────────────────────────
# Flag handling
# ────────────────────────────────────────────────────────────

class TestFlagHandling:
    def test_flag_off_by_default(self, monkeypatch):
        monkeypatch.delenv("FORGE_COMPOSITION_RECIPES", raising=False)
        assert pipeline_hook.is_flag_on() is False
        assert pipeline_hook.is_strict() is False

    @pytest.mark.parametrize("val", ["warn", "strict", "1", "true", "on", "yes"])
    def test_flag_on_for_various_truthy(self, monkeypatch, val):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", val)
        assert pipeline_hook.is_flag_on() is True

    @pytest.mark.parametrize("val", ["", "0", "off", "false", "no", "asdf"])
    def test_flag_off_for_falsy(self, monkeypatch, val):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", val)
        assert pipeline_hook.is_flag_on() is False

    def test_strict_only_for_strict_value(self, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        assert pipeline_hook.is_strict() is False
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "strict")
        assert pipeline_hook.is_strict() is True


# ────────────────────────────────────────────────────────────
# load_page_recipes
# ────────────────────────────────────────────────────────────

class TestLoadPageRecipes:
    def test_missing_brief_returns_empty(self, tmp_path):
        assert pipeline_hook.load_page_recipes(tmp_path) == {}

    def test_brief_without_page_recipes_returns_empty(self, tmp_path):
        (tmp_path / "contracts").mkdir()
        (tmp_path / "contracts" / "brief.json").write_text(json.dumps({"identity": {}}))
        assert pipeline_hook.load_page_recipes(tmp_path) == {}

    def test_reads_page_recipes_dict(self, tmp_path):
        (tmp_path / "contracts").mkdir()
        (tmp_path / "contracts" / "brief.json").write_text(json.dumps({
            "page_recipes": {"/home": "member_home", "/console": "citizen_service"},
        }))
        assert pipeline_hook.load_page_recipes(tmp_path) == {
            "/home": "member_home",
            "/console": "citizen_service",
        }

    def test_malformed_entries_dropped(self, tmp_path):
        (tmp_path / "contracts").mkdir()
        (tmp_path / "contracts" / "brief.json").write_text(json.dumps({
            "page_recipes": {
                "/home": "member_home",
                "": "unnamed_route",         # empty key dropped
                "/x": "",                     # empty value dropped
                "/y": None,                   # non-str value dropped
            },
        }))
        assert pipeline_hook.load_page_recipes(tmp_path) == {"/home": "member_home"}

    def test_broken_json_returns_empty(self, tmp_path):
        (tmp_path / "contracts").mkdir()
        (tmp_path / "contracts" / "brief.json").write_text("{not-json")
        assert pipeline_hook.load_page_recipes(tmp_path) == {}


# ────────────────────────────────────────────────────────────
# try_build_recipe_page
# ────────────────────────────────────────────────────────────

def _write_brief(tmp_path: Path, recipes: dict[str, str]) -> None:
    (tmp_path / "contracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "contracts" / "brief.json").write_text(json.dumps(
        {"page_recipes": recipes},
    ))


class TestTryBuildRecipePage:
    def test_flag_off_always_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FORGE_COMPOSITION_RECIPES", raising=False)
        _write_brief(tmp_path, {"/home": "member_home"})
        assert pipeline_hook.try_build_recipe_page("/home", tmp_path) is None

    def test_flag_on_no_recipe_registered_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/other": "member_home"})
        assert pipeline_hook.try_build_recipe_page("/home", tmp_path) is None

    def test_flag_on_recipe_registered_returns_page(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/home": "member_home"})
        page = pipeline_hook.try_build_recipe_page("/home", tmp_path)
        assert page is not None
        assert page["schemaVersion"] == "2"
        assert page["route"] == "/home"
        assert page["meta"]["recipe"] == "member_home"

    def test_recipe_with_no_v1_anchors_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/ops": "citizen_service"})
        # operator_console has no v1-implemented anchors → build returns None
        # → hook returns None → caller falls back to classic path
        assert pipeline_hook.try_build_recipe_page("/ops", tmp_path) is None

    def test_empty_route_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_COMPOSITION_RECIPES", "warn")
        _write_brief(tmp_path, {"/home": "member_home"})
        assert pipeline_hook.try_build_recipe_page("", tmp_path) is None
