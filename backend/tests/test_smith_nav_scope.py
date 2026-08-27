"""Tests for the SMITH-NAV "just answer" behavior.

Design: Smith does not punt on menu asks. Two coordinated paths:

  1. Deterministic fix — when the menu label doesn't match its current
     route AND a page whose route matches the label exists, we swap the
     route in shell.json ourselves and report what was done.
  2. Ambiguous fallback — when the fix isn't obvious, render the menu
     structure as a context block so Smith answers effectively on turn 0
     without a Read cycle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.smith_grounding import (
    _looks_like_nav_intent,
    _load_shell_menu_items,
    _match_menu_item,
    _label_stems,
    _route_base,
    try_fix_menu_route_mismatch,
    render_nav_context_block,
    build_deterministic_scope_check,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

def _write_shell(root: Path, groups: list[dict]) -> Path:
    p = root / "src" / "schemas" / "shell.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "schemaVersion": "2",
        "children": [{
            "type": "Row",
            "children": [{
                "type": "SideNav",
                "props": {"groups": groups},
            }],
        }],
    }, indent=2), encoding="utf-8")
    return p


def _write_navflow(root: Path, routes: list[str]) -> Path:
    p = root / "src" / "contracts" / "nav-flow.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "version": "1.0",
        "pages": [{"id": r.strip("/"), "route": r} for r in routes],
    }, indent=2), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# _looks_like_nav_intent                                                       #
# --------------------------------------------------------------------------- #

class TestLooksLikeNavIntent:
    def test_menu_word(self):
        assert _looks_like_nav_intent("Why recruiters menu is showing users page")

    def test_sidebar_word(self):
        assert _looks_like_nav_intent("sidebar link is broken")

    def test_navigation(self):
        assert _looks_like_nav_intent("fix the navigation")

    def test_sidenav_variants(self):
        assert _looks_like_nav_intent("SideNav has wrong entry")
        assert _looks_like_nav_intent("side-nav shows nothing")

    def test_no_nav_words(self):
        assert not _looks_like_nav_intent("clicking Recruiters shows Users")
        assert not _looks_like_nav_intent("Remove Department field from /employees/new")


# --------------------------------------------------------------------------- #
# _label_stems + _route_base                                                   #
# --------------------------------------------------------------------------- #

class TestStemsAndRouteBase:
    def test_label_stems_plural(self):
        stems = set(_label_stems("Recruiters"))
        assert "recruiter" in stems and "recruiters" in stems

    def test_label_stems_singular(self):
        stems = set(_label_stems("Recruiter"))
        assert "recruiter" in stems and "recruiters" in stems

    def test_label_stems_multiword(self):
        # Only the trailing noun matters — earlier tokens are ignored so
        # we don't over-match a 2-word label to a random single-word route.
        stems = set(_label_stems("Line Managers"))
        assert "manager" in stems and "managers" in stems

    def test_route_base_simple(self):
        assert _route_base("/recruiters") == "recruiters"

    def test_route_base_strips_dynamic_and_depth(self):
        assert _route_base("/recruiters/[id]/edit") == "recruiters"


# --------------------------------------------------------------------------- #
# try_fix_menu_route_mismatch — the deterministic "just answer" path            #
# --------------------------------------------------------------------------- #

class TestTryFixMenuRouteMismatch:
    def test_swaps_route_when_label_page_exists(self, tmp_path: Path):
        # Recruiters menu points to /users; /recruiters page also exists.
        # Expected: swap Recruiters → /recruiters, report the change.
        _write_shell(tmp_path, [
            {"label": "People", "items": [
                {"label": "Recruiters", "route": "/users", "icon": "users"},
            ]},
        ])
        _write_navflow(tmp_path, ["/users", "/recruiters", "/recruiters/[id]"])

        fix = try_fix_menu_route_mismatch(
            "Why recruiters menu is showing users page", str(tmp_path),
        )
        assert fix is not None
        assert fix["status"] == "fixed"
        assert "shell.json" in fix["edited_paths"][0]
        assert "/recruiters" in fix["message"]
        assert "/users" in fix["message"]

        # shell.json actually rewritten in place.
        shell = json.loads((tmp_path / "src/schemas/shell.json").read_text())
        rec = shell["children"][0]["children"][0]["props"]["groups"][0]["items"][0]
        assert rec["route"] == "/recruiters"

    def test_prefers_list_route_over_detail(self, tmp_path: Path):
        # When multiple candidate routes match the label stem, prefer
        # the list route (/recruiters) over detail (/recruiters/[id])
        # so the menu lands on the entity index.
        _write_shell(tmp_path, [
            {"label": "People", "items": [
                {"label": "Recruiters", "route": "/users", "icon": "users"},
            ]},
        ])
        _write_navflow(tmp_path, ["/recruiters/[id]/edit", "/recruiters/[id]", "/recruiters"])

        fix = try_fix_menu_route_mismatch(
            "recruiters menu shows the wrong page", str(tmp_path),
        )
        assert fix is not None
        shell = json.loads((tmp_path / "src/schemas/shell.json").read_text())
        rec = shell["children"][0]["children"][0]["props"]["groups"][0]["items"][0]
        assert rec["route"] == "/recruiters"

    def test_no_fix_when_route_already_matches_label(self, tmp_path: Path):
        # Menu label "Recruiters" already at /recruiters — nothing broken,
        # deterministic path returns None (LLM handles any real question).
        _write_shell(tmp_path, [
            {"label": "People", "items": [
                {"label": "Recruiters", "route": "/recruiters", "icon": "users"},
            ]},
        ])
        _write_navflow(tmp_path, ["/recruiters", "/users"])
        assert try_fix_menu_route_mismatch(
            "Why is the recruiters menu broken?", str(tmp_path),
        ) is None

    def test_no_fix_when_no_matching_page(self, tmp_path: Path):
        # Menu says Recruiters → /users, but no /recruiters page exists.
        # Deterministic fix can't figure it out safely — return None so
        # the LLM (with nav context injected) can propose a real fix.
        _write_shell(tmp_path, [
            {"label": "People", "items": [
                {"label": "Recruiters", "route": "/users", "icon": "users"},
            ]},
        ])
        _write_navflow(tmp_path, ["/users", "/candidates"])
        assert try_fix_menu_route_mismatch(
            "recruiters menu shows users page", str(tmp_path),
        ) is None

    def test_no_shell_returns_none(self, tmp_path: Path):
        assert try_fix_menu_route_mismatch(
            "the sidebar menu is broken", str(tmp_path),
        ) is None

    def test_non_nav_ask_returns_none(self, tmp_path: Path):
        # Nav-intent gate should skip — this isn't about a menu.
        _write_shell(tmp_path, [
            {"label": "People", "items": [
                {"label": "Recruiters", "route": "/users", "icon": "users"},
            ]},
        ])
        _write_navflow(tmp_path, ["/recruiters"])
        assert try_fix_menu_route_mismatch(
            "add a Salary field to Employee", str(tmp_path),
        ) is None


# --------------------------------------------------------------------------- #
# render_nav_context_block                                                     #
# --------------------------------------------------------------------------- #

class TestRenderNavContextBlock:
    def test_renders_full_menu(self, tmp_path: Path):
        _write_shell(tmp_path, [
            {"label": "Discover", "items": [
                {"label": "Recruiters", "route": "/users"},
                {"label": "Candidates", "route": "/candidates"},
            ]},
            {"label": "Admin", "items": [
                {"label": "Settings", "route": "/settings"},
            ]},
        ])
        block = render_nav_context_block(str(tmp_path))
        assert "Sidebar menu" in block
        assert "**Discover**" in block
        assert "**Admin**" in block
        assert "Recruiters" in block and "/users" in block
        assert "Settings" in block and "/settings" in block

    def test_empty_when_shell_missing(self, tmp_path: Path):
        assert render_nav_context_block(str(tmp_path)) == ""


# --------------------------------------------------------------------------- #
# build_deterministic_scope_check integration                                  #
# --------------------------------------------------------------------------- #

class TestScopeCheckNavIntegration:
    def test_nav_intent_returns_empty_not_page_enum(self, tmp_path: Path):
        # Nav-intent asks bypass the page-enum entirely so the router's
        # "just answer" nav path can take over.
        _write_shell(tmp_path, [
            {"label": "People", "items": [
                {"label": "Recruiters", "route": "/users"},
            ]},
        ])
        q = build_deterministic_scope_check(
            "Why recruiters menu is showing users page", str(tmp_path),
        )
        assert q == ""

    def test_non_nav_ask_falls_through_normally(self, tmp_path: Path):
        # A pure schema-level ask still short-circuits (unchanged behavior).
        q = build_deterministic_scope_check(
            "add a status field to Candidate", str(tmp_path),
        )
        assert q == ""
