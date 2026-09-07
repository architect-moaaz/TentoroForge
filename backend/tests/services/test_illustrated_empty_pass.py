"""Tests for services.illustrated_empty_pass (Spec C Slice 9)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import illustrated_empty_pass as pass_mod


@pytest.fixture(autouse=True)
def _s9_on(monkeypatch):
    monkeypatch.setenv("FORGE_POLISH_LOGO", "1")
    yield
    monkeypatch.delenv("FORGE_POLISH_LOGO", raising=False)


class TestKindPicker:
    @pytest.mark.parametrize("route,expected", [
        ("/search",     "search"),
        ("/candidates/search", "search"),
        ("/filter",     "filtered"),
        ("/advanced",   "filtered"),
        ("/welcome",    "first-use"),
        ("/get-started","first-use"),
        ("/dashboard",  "no-data"),
        ("/analytics",  "no-data"),
        ("/reports",    "no-data"),
        ("/offline",    "offline"),
        ("/forbidden",  "no-access"),
        ("/candidates", "list"),  # no rule → residual default
        ("/anything-random", "list"),
    ])
    def test_route_matches(self, route, expected):
        assert pass_mod._pick_kind(route) == expected

    def test_surrounding_text_disambiguates(self):
        assert pass_mod._pick_kind("/candidates", "Search results") == "search"
        assert pass_mod._pick_kind("/candidates", "Filter applied") == "filtered"

    def test_earlier_rule_wins(self):
        # "search" matches before "dashboard" in the rule table.
        assert pass_mod._pick_kind("/search-dashboard") == "search"

    def test_case_insensitive(self):
        assert pass_mod._pick_kind("/SEARCH") == "search"
        assert pass_mod._pick_kind("/Dashboard") == "no-data"

    def test_empty_inputs_yield_default(self):
        assert pass_mod._pick_kind("", "") == "list"


class TestBareEmptyStateDetection:
    def test_plain_empty_state_is_bare(self):
        n = {"type": "EmptyState", "props": {"title": "No items"}}
        assert pass_mod._is_bare_empty_state(n) is True

    def test_empty_state_with_illustration_prop_not_bare(self):
        n = {"type": "EmptyState", "props": {
            "title": "No items", "illustration": "sunset.svg",
        }}
        assert pass_mod._is_bare_empty_state(n) is False

    def test_wrong_type_not_bare(self):
        assert pass_mod._is_bare_empty_state({"type": "Text"}) is False
        assert pass_mod._is_bare_empty_state({"type": "IllustratedEmpty"}) is False

    def test_non_dict_not_bare(self):
        assert pass_mod._is_bare_empty_state("nope") is False
        assert pass_mod._is_bare_empty_state(None) is False


class TestUpgradeMutation:
    def test_upgrades_to_illustrated_empty(self):
        n = {"type": "EmptyState", "props": {
            "title": "No candidates yet",
            "message": "Add your first candidate to get started.",
        }}
        pass_mod._upgrade_empty_state(n, "list")
        assert n["type"] == "IllustratedEmpty"
        assert n["props"]["kind"] == "list"
        # Preserves author-supplied text.
        assert n["props"]["title"] == "No candidates yet"
        assert n["props"]["message"] == "Add your first candidate to get started."

    def test_preserves_action_prop(self):
        n = {"type": "EmptyState", "props": {
            "title": "T", "action": {"label": "Add", "workflow": "createX"},
        }}
        pass_mod._upgrade_empty_state(n, "first-use")
        assert n["props"]["action"] == {"label": "Add", "workflow": "createX"}

    def test_drops_stray_props(self):
        # style / motion belong; anything else should be shed to keep
        # the IllustratedEmpty schema clean.
        n = {"type": "EmptyState", "props": {
            "title": "T", "message": "M",
            "borderThickness": 4,  # not a valid IllustratedEmpty prop
        }}
        pass_mod._upgrade_empty_state(n, "list")
        assert "borderThickness" not in n["props"]


class TestPageSchemaUpgrade:
    def test_upgrades_bare_empty_in_list_page(self):
        schema = {
            "root": {"type": "Stack", "children": [
                {"type": "Heading", "props": {"text": "Candidates"}},
                {"type": "Table", "props": {}, "children": []},
                {"type": "EmptyState", "props": {"title": "No candidates"}},
            ]},
        }
        r = pass_mod.upgrade_page_schema(schema, route="/candidates")
        assert r["upgraded"] == 1
        assert r["kind_used"] == "list"
        assert schema["root"]["children"][2]["type"] == "IllustratedEmpty"
        assert schema["root"]["children"][2]["props"]["kind"] == "list"

    def test_dashboard_route_yields_no_data_kind(self):
        schema = {
            "root": {"type": "Stack", "children": [
                {"type": "EmptyState", "props": {"title": "No data yet"}},
            ]},
        }
        r = pass_mod.upgrade_page_schema(schema, route="/dashboard")
        assert r["kind_used"] == "no-data"
        assert schema["root"]["children"][0]["type"] == "IllustratedEmpty"

    def test_deep_nested_empty_state_upgrades(self):
        schema = {"root": {"type": "Stack", "children": [
            {"type": "Card", "children": [
                {"type": "Stack", "children": [
                    {"type": "EmptyState", "props": {"title": "T"}},
                ]},
            ]},
        ]}}
        r = pass_mod.upgrade_page_schema(schema, route="/search")
        assert r["upgraded"] == 1
        deep = schema["root"]["children"][0]["children"][0]["children"][0]
        assert deep["type"] == "IllustratedEmpty"
        assert deep["props"]["kind"] == "search"

    def test_idempotent(self):
        schema = {"root": {"type": "Stack", "children": [
            {"type": "EmptyState", "props": {"title": "T"}},
        ]}}
        r1 = pass_mod.upgrade_page_schema(schema, route="/x")
        r2 = pass_mod.upgrade_page_schema(schema, route="/x")
        assert r1["upgraded"] == 1
        assert r2["upgraded"] == 0

    def test_no_empty_states_no_upgrades(self):
        schema = {"root": {"type": "Stack", "children": [
            {"type": "Heading", "props": {"text": "Hi"}},
        ]}}
        r = pass_mod.upgrade_page_schema(schema, route="/hi")
        assert r["upgraded"] == 0

    def test_missing_root_safe(self):
        r = pass_mod.upgrade_page_schema({}, route="/x")
        assert r["upgraded"] == 0


class TestFilesystemRun:
    def test_run_no_op_when_flag_off(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("FORGE_POLISH_LOGO", raising=False)
        r = pass_mod.run(tmp_path)
        assert r["skipped_reason"] == "FORGE_POLISH_LOGO off"
        assert r["total_upgrades"] == 0

    def test_run_no_op_when_no_schemas_dir(self, tmp_path: Path):
        r = pass_mod.run(tmp_path)
        assert r["skipped_reason"] == "no src/schemas dir"

    def test_run_upgrades_real_files(self, tmp_path: Path):
        schemas = tmp_path / "src" / "schemas"
        schemas.mkdir(parents=True)
        # Two pages, one with a bare empty-state.
        (schemas / "candidates.json").write_text(json.dumps({
            "root": {"type": "Stack", "children": [
                {"type": "EmptyState", "props": {"title": "No candidates"}},
            ]},
        }), encoding="utf-8")
        (schemas / "settings.json").write_text(json.dumps({
            "root": {"type": "Stack", "children": [
                {"type": "Heading", "props": {"text": "Settings"}},
            ]},
        }), encoding="utf-8")
        r = pass_mod.run(tmp_path)
        assert r["pages_scanned"] == 2
        assert r["pages_upgraded"] == 1
        assert r["total_upgrades"] == 1
        # File was rewritten with the upgraded type.
        reloaded = json.loads((schemas / "candidates.json").read_text(encoding="utf-8"))
        assert reloaded["root"]["children"][0]["type"] == "IllustratedEmpty"

    def test_run_skips_shell_json(self, tmp_path: Path):
        schemas = tmp_path / "src" / "schemas"
        schemas.mkdir(parents=True)
        (schemas / "shell.json").write_text(json.dumps({
            "root": {"type": "Stack", "children": [
                # Deliberately place a bare EmptyState inside the shell to
                # prove the walker refuses to touch shell.json.
                {"type": "EmptyState", "props": {"title": "T"}},
            ]},
        }), encoding="utf-8")
        r = pass_mod.run(tmp_path)
        assert r["pages_scanned"] == 0  # shell.json is excluded
        # Shell content untouched.
        reloaded = json.loads((schemas / "shell.json").read_text(encoding="utf-8"))
        assert reloaded["root"]["children"][0]["type"] == "EmptyState"

    def test_route_derivation_from_file_path(self, tmp_path: Path):
        schemas = tmp_path / "src" / "schemas"
        (schemas / "candidates").mkdir(parents=True)
        (schemas / "candidates" / "search.json").write_text(json.dumps({
            "root": {"type": "Stack", "children": [
                {"type": "EmptyState", "props": {"title": "T"}},
            ]},
        }), encoding="utf-8")
        r = pass_mod.run(tmp_path)
        assert r["total_upgrades"] == 1
        upgraded = json.loads((schemas / "candidates" / "search.json").read_text(encoding="utf-8"))
        # Route "/candidates/search" matches _pick_kind's search rule.
        assert upgraded["root"]["children"][0]["props"]["kind"] == "search"
